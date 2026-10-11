"""
Unified, trusted calculation service for cart subtotals, coupons, taxes, and shipping.
Uses integer minor-unit arithmetic (paise) to eliminate floating-point inaccuracies.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional


def to_paise(amount: Any) -> int:
    """Convert rupee float, int, string or decimal to integer paise safely."""
    if amount is None or amount == "":
        return 0
    try:
        d = Decimal(str(amount))
        return int((d * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0


def to_rupees(paise: Any) -> float:
    """Convert integer paise back to standard float rounded to 2 decimal places."""
    if paise is None or paise == "":
        return 0.0
    try:
        return float(Decimal(int(paise)) / Decimal(100))
    except Exception:
        return 0.0


def calculate_coupon_discount(
    subtotal_paise: int,
    coupon: Any
) -> Dict[str, Any]:
    """
    Validate coupon eligibility and calculate discount in paise.
    Accepts SQLAlchemy model instance, dictionary, or duck-typed object.
    """
    if not coupon:
        return {
            "valid": False,
            "discount_paise": 0,
            "discount_rupees": 0.0,
            "message": ""
        }

    if isinstance(coupon, dict):
        is_active = coupon.get("is_active", True)
        code = coupon.get("code", "")
        min_order = float(coupon.get("min_order_amount") or coupon.get("min_order") or 0.0)
        discount_type = str(coupon.get("discount_type") or coupon.get("type") or "").lower()
        val = float(coupon.get("discount_value") or coupon.get("value") or 0.0)
        max_discount = float(coupon.get("max_discount") or 0.0)
    else:
        is_active = getattr(coupon, "is_active", True)
        code = getattr(coupon, "code", "")
        min_order = float(getattr(coupon, "min_order_amount", 0.0) or 0.0)
        discount_type = str(getattr(coupon, "discount_type", "") or "").lower()
        val = float(getattr(coupon, "discount_value", 0.0) or 0.0)
        max_discount = float(getattr(coupon, "max_discount", 0.0) or 0.0)

    if not is_active:
        return {
            "valid": False,
            "discount_paise": 0,
            "discount_rupees": 0.0,
            "message": f"Coupon '{code}' is inactive or expired."
        }

    subtotal_rupees = to_rupees(subtotal_paise)
    if subtotal_rupees < min_order:
        return {
            "valid": False,
            "discount_paise": 0,
            "discount_rupees": 0.0,
            "message": f"Coupon '{code}' requires a minimum order of ₹{min_order:,.0f}."
        }

    if "percent" in discount_type or discount_type == "%":
        calc_discount_paise = int(round(subtotal_paise * (val / 100.0)))
    else:
        calc_discount_paise = to_paise(val)

    if max_discount > 0:
        calc_discount_paise = min(calc_discount_paise, to_paise(max_discount))

    # Discount cannot exceed subtotal
    discount_paise = max(0, min(subtotal_paise, calc_discount_paise))

    return {
        "valid": True,
        "discount_paise": discount_paise,
        "discount_rupees": to_rupees(discount_paise),
        "message": f"Coupon '{code}' applied successfully!"
    }


def calculate_bag_and_checkout(
    items: List[Dict[str, Any]],
    coupon_obj: Any = None,
    shipping_paise: int = 0,
    coupon_code: Optional[str] = None,
    dest_pincode: Optional[str] = None,
    payment_method: str = "FULL"
) -> Dict[str, Any]:
    """
    Execute trusted calculation order:
    1. Calculate items subtotal from product price * qty.
    2. Check coupon eligibility against subtotal.
    3. Calculate coupon discount amount (capped if applicable, never negative).
    4. Compute discounted subtotal.
    5. Add valid shipping amount.
    6. Compute final payable grand total, advance deposit, and balance due.
    """
    subtotal_paise = 0
    item_breakdown = []

    for item in items:
        product = item.get("product")
        qty = max(1, int(item.get("quantity", 1)))
        if not product:
            continue
        unit_price_paise = to_paise(product.price)
        line_subtotal_paise = unit_price_paise * qty
        subtotal_paise += line_subtotal_paise
        item_breakdown.append({
            "product": product,
            "quantity": qty,
            "unit_price_paise": unit_price_paise,
            "unit_price": to_rupees(unit_price_paise),
            "subtotal_paise": line_subtotal_paise,
            "subtotal": to_rupees(line_subtotal_paise),
            "size": item.get("size", "M"),
            "top_length": item.get("top_length", "30"),
            "sleeves_length": item.get("sleeves_length", "18"),
            "bust": item.get("bust", ""),
            "waist": item.get("waist", ""),
            "hip": item.get("hip", ""),
            "shoulder": item.get("shoulder", "")
        })

    # If coupon_obj not passed but coupon_code is, look up Coupon model if in Flask app context
    if not coupon_obj and coupon_code:
        try:
            from models.coupon import Coupon
            coupon_obj = Coupon.query.filter_by(code=coupon_code.strip().upper(), is_active=True).first()
        except Exception:
            coupon_obj = None

    coupon_res = calculate_coupon_discount(subtotal_paise, coupon_obj)
    discount_paise = coupon_res["discount_paise"]
    coupon_valid = coupon_res["valid"]
    coupon_message = coupon_res["message"]

    # Compute shipping if dest_pincode provided and shipping_paise not explicitly given
    shipping_info = {}
    if dest_pincode and shipping_paise == 0:
        try:
            from services.shipping_service import get_shipping_quote, get_order_package_specs
            specs = get_order_package_specs(items)
            quote = get_shipping_quote(
                dest_pincode=dest_pincode,
                physical_weight_kg=specs.get("billable_weight_kg", 0.5),
                length_cm=specs.get("length_cm", 30.0),
                width_cm=specs.get("width_cm", 25.0),
                height_cm=specs.get("height_cm", 5.0)
            )
            if quote.get("success"):
                shipping_paise = to_paise(quote.get("rate_rupees", 0.0))
                shipping_info = quote
        except Exception:
            pass

    discounted_subtotal_paise = max(0, subtotal_paise - discount_paise)
    grand_total_paise = discounted_subtotal_paise + max(0, shipping_paise)

    # Handle payment method breakdown (Full vs 25% Advance vs COD)
    pm = str(payment_method or "").upper()
    if "ADVANCE" in pm or "25" in pm:
        # 25% Advance deposit
        advance_paise = int(round(grand_total_paise * 0.25))
        balance_paise = max(0, grand_total_paise - advance_paise)
    elif "COD" in pm and "ADVANCE" not in pm:
        advance_paise = 0
        balance_paise = grand_total_paise
    else:
        # Full payment
        advance_paise = grand_total_paise
        balance_paise = 0

    return {
        "items": item_breakdown,
        "subtotal_paise": subtotal_paise,
        "subtotal": to_rupees(subtotal_paise),
        "discount_paise": discount_paise,
        "discount_amount": to_rupees(discount_paise),
        "discounted_subtotal_paise": discounted_subtotal_paise,
        "discounted_subtotal": to_rupees(discounted_subtotal_paise),
        "shipping_paise": shipping_paise,
        "shipping_fee": to_rupees(shipping_paise),
        "shipping_info": shipping_info,
        "grand_total_paise": grand_total_paise,
        "grand_total": to_rupees(grand_total_paise),
        "final_total": to_rupees(grand_total_paise),
        "total": to_rupees(grand_total_paise),
        "advance_paid_paise": advance_paise,
        "advance_paid": to_rupees(advance_paise),
        "balance_due_paise": balance_paise,
        "balance_due": to_rupees(balance_paise),
        "coupon_valid": coupon_valid,
        "coupon_message": coupon_message
    }
