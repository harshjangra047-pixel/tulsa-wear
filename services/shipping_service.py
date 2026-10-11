"""
Shipping Calculation & Provider Integration Service for Tulsa Wears.
Supports warehouse origin, product dimensions, volumetric weight, and carrier quotations.
"""

import os
import re
import time
import logging
import requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Default Atelier Warehouse Location (Tulsa Wears Studio)
DEFAULT_WAREHOUSE = {
    "name": "Tulsa Wears Atelier",
    "address": "Tulsa Wears Atelier, Hansi",
    "city": "Hansi",
    "state": "Haryana",
    "pincode": "125033",
    "country": "India",
    "phone": "+91 93504 39667"
}

# Standard apparel box default packaging (cm and kg)
DEFAULT_PRODUCT_WEIGHT_KG = 0.5
DEFAULT_PACKAGE_LENGTH_CM = 30.0
DEFAULT_PACKAGE_WIDTH_CM = 25.0
DEFAULT_PACKAGE_HEIGHT_CM = 5.0


def calculate_volumetric_weight(length_cm: float, width_cm: float, height_cm: float) -> float:
    """Calculate volumetric weight using industry standard divisor 5000."""
    return round((length_cm * width_cm * height_cm) / 5000.0, 3)

# Alias for compatibility
calculate_volumetric_weight_kg = calculate_volumetric_weight


def get_indian_postal_zone(pincode: str) -> str:
    """Classify 6-digit Indian PIN code into postal logistics zones relative to Hansi, Haryana (125033)."""
    clean = re.sub(r"\D", "", pincode or "")
    if len(clean) != 6:
        return "Unknown"

    prefix2 = clean[:2]
    prefix3 = clean[:3]

    # Local / Intra-Haryana
    if prefix3.startswith("125") or prefix2 in {"12", "13"}:
        return "Zone A (Local / Haryana)"

    # Regional North (Delhi, NCR, Punjab, HP, Chandigarh, Western UP)
    if prefix2 in {"11", "14", "15", "16", "17", "20", "24", "25", "26", "28"}:
        return "Zone B (Regional North)"

    # Metros (Mumbai, Kolkata)
    if prefix2 in {"40", "70"}:
        return "Zone C (Metro)"

    # Remote / Special (J&K, North-East, Island territories)
    if prefix2 in {"18", "19", "78", "79", "74", "73", "90"}:
        return "Zone E (Special / Remote)"

    # Rest of India (South, East, Central, West non-metro)
    return "Zone D (Rest of India)"


def get_order_package_specs(products_with_qty: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Calculate consolidated chargeable weight and packaging dimensions for an order.
    Chargeable weight = max(dead weight, volumetric weight).
    """
    total_dead_weight = 0.0
    total_volume_cm3 = 0.0
    max_length = DEFAULT_PACKAGE_LENGTH_CM
    max_width = DEFAULT_PACKAGE_WIDTH_CM
    stacked_height = 0.0

    for item in products_with_qty:
        p = item.get("product")
        qty = max(1, int(item.get("quantity", 1)))
        if not p:
            continue
        weight = float(getattr(p, "weight_kg", None) or DEFAULT_PRODUCT_WEIGHT_KG)
        length = float(getattr(p, "length_cm", None) or DEFAULT_PACKAGE_LENGTH_CM)
        width = float(getattr(p, "width_cm", None) or DEFAULT_PACKAGE_WIDTH_CM)
        height = float(getattr(p, "height_cm", None) or DEFAULT_PACKAGE_HEIGHT_CM)

        max_length = max(max_length, length)
        max_width = max(max_width, width)
        stacked_height += height * qty

        total_dead_weight += weight * qty
        total_volume_cm3 += (length * width * height) * qty

    est_height = max(5.0, stacked_height if stacked_height > 0 else 5.0)
    est_length = max_length
    est_width = max_width

    volumetric_weight = round(total_volume_cm3 / 5000.0, 3)
    chargeable_weight = max(total_dead_weight, volumetric_weight)

    return {
        "dead_weight_kg": round(total_dead_weight, 2),
        "physical_weight_kg": round(total_dead_weight, 2),
        "volumetric_weight_kg": volumetric_weight,
        "chargeable_weight_kg": round(chargeable_weight, 2),
        "billable_weight_kg": round(chargeable_weight, 2),
        "length_cm": est_length,
        "width_cm": est_width,
        "height_cm": est_height
    }


def get_shiprocket_token(email: str, password: str) -> Optional[str]:
    """Authenticate with Shiprocket and retrieve bearer auth token."""
    if not email or not password:
        return None
    try:
        res = requests.post(
            "https://apiv2.shiprocket.in/v1/external/auth/login",
            json={"email": email, "password": password},
            timeout=8
        )
        if res.status_code == 200:
            data = res.json()
            return data.get("token")
    except Exception as e:
        logger.error(f"Shiprocket auth request failed: {e}")
    return None


def get_shipping_quote(
    destination_pincode: Optional[str] = None,
    destination_country: str = "India",
    products_with_qty: Optional[List[Dict[str, Any]]] = None,
    warehouse_info: Optional[Dict[str, Any]] = None,
    shiprocket_creds: Optional[Dict[str, Any]] = None,
    fallback_enabled: bool = True,
    fallback_amount: float = 0.0,
    **kwargs
) -> Dict[str, Any]:
    """
    Compute live shipping quote.
    - Validates postal code and country.
    - Connects to carrier API if configured.
    - If provider is not configured or in sandbox, uses distance/zone pricing calculated
      from Hansi, Haryana warehouse (125033) based on actual Indian PIN code routing prefix.
    - Supports flexible keyword parameters (dest_pincode, physical_weight_kg, etc.).
    """
    pincode = destination_pincode or kwargs.get("dest_pincode") or ""
    clean_pincode = re.sub(r"\D", "", pincode or "")
    country = (destination_country or kwargs.get("dest_country") or "India").strip()

    # International destination check
    if country.lower() not in {"india", "in"}:
        msg = f"Automated international shipping to '{country}' is currently not available. Please contact our atelier concierge via WhatsApp for bespoke international courier quotes."
        return {
            "success": False,
            "serviceable": False,
            "rate_rupees": 0.0,
            "shipping_fee": 0.0,
            "provider": "International Courier",
            "service": "Unavailable",
            "message": msg,
            "error": msg,
            "estimated_days": None
        }

    # Validate 6-digit Indian PIN code
    if len(clean_pincode) != 6 or clean_pincode.startswith("0"):
        msg = "Please enter a valid 6-digit Indian PIN code to check shipping serviceability."
        return {
            "success": False,
            "serviceable": False,
            "rate_rupees": 0.0,
            "shipping_fee": 0.0,
            "provider": "Courier",
            "service": "Unavailable",
            "message": msg,
            "error": msg,
            "estimated_days": None
        }

    specs = get_order_package_specs(products_with_qty or [])
    weight = float(kwargs.get("physical_weight_kg") or kwargs.get("chargeable_weight_kg") or specs["chargeable_weight_kg"])
    weight = max(0.5, weight)

    # Check Shiprocket API if live credentials supplied
    if shiprocket_creds and shiprocket_creds.get("token"):
        try:
            pickup_pin = (warehouse_info or {}).get("pincode", DEFAULT_WAREHOUSE["pincode"])
            headers = {"Authorization": f"Bearer {shiprocket_creds['token']}"}
            params = {
                "pickup_postcode": pickup_pin,
                "delivery_postcode": clean_pincode,
                "weight": weight,
                "cod": 0
            }
            res = requests.get(
                "https://apiv2.shiprocket.in/v1/external/courier/serviceability/",
                params=params,
                headers=headers,
                timeout=6
            )
            if res.status_code == 200:
                data = res.json()
                courier_data = data.get("data", {}).get("available_courier_companies", [])
                if courier_data:
                    cheapest = min(courier_data, key=lambda c: float(c.get("rate", 9999)))
                    fee = float(cheapest.get("rate", 0.0))
                    provider = f"Shiprocket ({cheapest.get('courier_name', 'Express')})"
                    service = cheapest.get("courier_name", "Express Surface")
                    etd = int(cheapest.get("etd", 5))
                    return {
                        "success": True,
                        "serviceable": True,
                        "rate_rupees": fee,
                        "shipping_fee": fee,
                        "provider": provider,
                        "courier": provider,
                        "service": service,
                        "estimated_days": etd,
                        "message": "Quote calculated via Shiprocket.",
                        "package_specs": specs
                    }
        except Exception as e:
            logger.warning(f"Live Shiprocket quote query error: {e}")

    # Standard Zone-Based Quotation from Hansi, Haryana (Zone A / B / C / D / E)
    zone_label = get_indian_postal_zone(clean_pincode)

    zone_table = {
        "Zone A (Local / Haryana)": {"base_rate": 80.0, "per_kg": 40.0, "etd": 3},
        "Zone B (Regional North)": {"base_rate": 100.0, "per_kg": 50.0, "etd": 4},
        "Zone C (Metro)": {"base_rate": 130.0, "per_kg": 60.0, "etd": 5},
        "Zone D (Rest of India)": {"base_rate": 160.0, "per_kg": 75.0, "etd": 6},
        "Zone E (Special / Remote)": {"base_rate": 180.0, "per_kg": 85.0, "etd": 7},
    }

    zone_info = zone_table.get(zone_label)
    if not zone_info:
        if fallback_enabled and fallback_amount > 0:
            return {
                "success": True,
                "serviceable": True,
                "rate_rupees": float(fallback_amount),
                "shipping_fee": float(fallback_amount),
                "provider": "Standard Insured Courier",
                "courier": "Standard Insured Courier",
                "service": "Pan-India Surface",
                "estimated_days": 7,
                "zone": "Pan-India Flat",
                "message": "Calculated via standard insured fallback.",
                "package_specs": specs
            }
        return {
            "success": False,
            "serviceable": False,
            "rate_rupees": 0.0,
            "shipping_fee": 0.0,
            "provider": "Carrier",
            "courier": "Carrier",
            "service": "Unavailable",
            "error": f"Destination PIN {clean_pincode} is not currently in standard delivery zones.",
            "message": f"Destination PIN {clean_pincode} is not currently in standard delivery zones.",
            "estimated_days": None
        }

    base_rate = zone_info["base_rate"]
    extra_half_kgs = max(0, int(round((weight - 0.5) / 0.5)))
    calculated_shipping = base_rate + (extra_half_kgs * (zone_info["per_kg"] / 2.0))

    provider_name = f"Express Insured Courier ({zone_label})"

    return {
        "success": True,
        "serviceable": True,
        "rate_rupees": round(calculated_shipping, 2),
        "shipping_fee": round(calculated_shipping, 2),
        "provider": provider_name,
        "courier": provider_name,
        "zone": zone_label,
        "service": "Express Air & Surface",
        "estimated_days": zone_info["etd"],
        "message": f"Calculated for {zone_label}",
        "package_specs": specs
    }
