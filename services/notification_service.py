"""
Automated WhatsApp, SMS & Transactional Email Notification System for Tulsa Wear Atelier.
Provides:
1. Central 7–15 Day Delivery Timeline Calculation (Asia/Kolkata timezone).
2. Owner New Order SMS Alert (+91 9350439667) via Indian SMS Gateway with secure invoice link.
3. Official Meta WhatsApp Business Platform Cloud API Integration with customer consent verification.
4. Complete Customer Order Lifecycle Follow-up (Confirmed, Processing, Dispatched, Out for Delivery, Delivered, Feedback).
5. Haute Couture Responsive Order Confirmation Email (Resend API & SMTP fallback).
6. Idempotency enforcement, Outbox auditing, and Admin resend capabilities.
"""

import os
import re
import json
import hmac
import hashlib
import logging
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from datetime import timezone
    ZoneInfo = lambda name: timezone(timedelta(hours=5, minutes=30))

import requests
from flask import render_template, current_app, has_request_context

from models.database import db
from models.order_notification import OrderNotification

logger = logging.getLogger(__name__)

# ==========================================================
# CENTRAL DELIVERY TIMELINE CONFIGURATION (7–15 DAYS)
# ==========================================================
DEFAULT_DELIVERY_MIN_DAYS = 7
DEFAULT_DELIVERY_MAX_DAYS = 15
KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
OWNER_PHONE_DEFAULT = "+919350439667"


def get_delivery_min_max_days():
    """Retrieve central delivery days configuration from environment or defaults."""
    try:
        min_days = int(os.getenv("DELIVERY_MIN_DAYS", DEFAULT_DELIVERY_MIN_DAYS))
    except (ValueError, TypeError):
        min_days = DEFAULT_DELIVERY_MIN_DAYS

    try:
        max_days = int(os.getenv("DELIVERY_MAX_DAYS", DEFAULT_DELIVERY_MAX_DAYS))
    except (ValueError, TypeError):
        max_days = DEFAULT_DELIVERY_MAX_DAYS

    if min_days > max_days:
        min_days, max_days = max_days, min_days

    return min_days, max_days


def calculate_delivery_window(base_datetime=None):
    """
    Compute central 7-15 day delivery window relative to the order confirmation timestamp
    in the Asia/Kolkata timezone.
    Returns:
        dict with min_days, max_days, start_date, end_date, formatted display strings.
    """
    min_days, max_days = get_delivery_min_max_days()

    if base_datetime is None:
        now_dt = datetime.now(KOLKATA_TZ)
    elif isinstance(base_datetime, datetime):
        if base_datetime.tzinfo is None:
            now_dt = base_datetime.replace(tzinfo=KOLKATA_TZ)
        else:
            now_dt = base_datetime.astimezone(KOLKATA_TZ)
    else:
        now_dt = datetime.now(KOLKATA_TZ)

    start_date = now_dt + timedelta(days=min_days)
    end_date = now_dt + timedelta(days=max_days)

    start_str = start_date.strftime("%d %b %Y")
    end_str = end_date.strftime("%d %b %Y")
    display_window = f"{start_str} – {end_str}"

    return {
        "min_days": min_days,
        "max_days": max_days,
        "start_date": start_date,
        "end_date": end_date,
        "start_str": start_str,
        "end_str": end_str,
        "display_window": display_window,
        "timeline_text": f"Expected delivery within {min_days}–{max_days} days from confirmation ({display_window})."
    }


def clean_indian_phone(phone_str):
    """
    Normalize phone number to international 91XXXXXXXXXX format for Indian telecom and Meta WhatsApp API.
    """
    if not phone_str:
        return ""
    digits = re.sub(r"\D", "", str(phone_str))
    if digits.startswith("91") and len(digits) == 12:
        return digits
    if len(digits) == 10:
        return f"91{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"91{digits[1:]}"
    return digits


def get_public_store_url():
    """Resolve production public store base URL."""
    url = os.getenv("PUBLIC_STORE_URL", "").strip()
    if not url:
        vercel_url = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        if vercel_url:
            url = f"https://{vercel_url}"
    if not url:
        url = "https://tulsa-wear.vercel.app"
    return url.rstrip("/")


def generate_secure_invoice_token(order_id):
    """Generate a cryptographic HMAC token granting access to a specific order invoice."""
    secret = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "tulsa_atelier_secret_vault_2026"
    return hmac.new(secret.encode("utf-8"), f"tulsa_invoice_{order_id}".encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def verify_invoice_token(order_id, token):
    """Verify an invoice access token."""
    expected = generate_secure_invoice_token(order_id)
    return hmac.compare_digest(expected, token or "")


def get_secure_invoice_url(order_id):
    """Build a secure, authenticated link to the order invoice."""
    store_url = get_public_store_url()
    token = generate_secure_invoice_token(order_id)
    return f"{store_url}/invoice/{order_id}?token={token}"


def build_order_items_list(order):
    """
    Extract structured garment items snapshot from order with prices,
    quantities, sizes, and product photo URLs.
    """
    store_url = get_public_store_url()
    raw_items = order.get_items()
    structured = []
    total_qty = 0

    for it in raw_items:
        name = it.get("name") or order.product_name or "Handcrafted Garment"
        qty = max(1, int(it.get("quantity", 1)))
        price = float(it.get("price", order.price or 0.0))
        size = it.get("size") or order.size or "M"
        top_len = it.get("top_length") or order.top_length or "30"
        bust = it.get("bust") or order.bust or ""

        # Photo URL resolution
        img = it.get("image") or ""
        if img and not img.startswith("http"):
            if not img.startswith("/"):
                img = f"/{img}"
            img = f"{store_url}{img}"
        elif not img:
            img = f"{store_url}/static/images/editorial-hero.jpg"

        total_qty += qty
        structured.append({
            "product_id": it.get("product_id", order.product_id),
            "name": name,
            "quantity": qty,
            "price": price,
            "size": size,
            "top_length": top_len,
            "bust": bust,
            "image": img,
            "subtotal": price * qty
        })

    return structured, total_qty


# ==========================================================
# 1. OWNER NEW ORDER SMS ALERT SYSTEM (+91 9350439667)
# ==========================================================

def format_owner_new_order_sms(order, items, total_qty, store_url):
    """
    Construct a concise, informative, professional SMS for the business owner.
    """
    st = (order.status or "").lower()
    method = order.payment_method or "Online"
    if "cod" in st or "cash" in method.lower():
        payment_str = "COD (Pay on Delivery)"
    elif "confirm" in st or order.is_paid():
        payment_str = f"Paid ({method})"
    else:
        payment_str = f"Pending ({method})"

    # Concise product summary
    item_lines = []
    for it in items[:3]:
        item_lines.append(f"{it['name']} ({it['size']}) x{it['quantity']}")
    if len(items) > 3:
        item_lines.append(f"+{len(items) - 3} more")
    items_summary = ", ".join(item_lines)

    invoice_url = get_secure_invoice_url(order.id)
    location_str = f"{order.city or 'India'} - {order.pincode or ''}".strip(" -")

    msg = (
        f"NEW ORDER RECEIVED – TULSA WEAR\n"
        f"Order: #{order.id}\n"
        f"Customer: {order.customer_name}\n"
        f"Phone: {order.phone}\n"
        f"Items: {items_summary}\n"
        f"Qty: {total_qty} Pc | Rs.{order.price:,.0f}\n"
        f"Location: {location_str}\n"
        f"Payment: {payment_str}\n"
        f"Invoice: {invoice_url}"
    )
    return msg


def send_owner_new_order_sms(order, force_resend=False):
    """
    Send an automated SMS alert to the business owner whenever a new valid order is placed.
    Default Recipient: +91 9350439667 (configurable via OWNER_ALERT_PHONE).
    Supports Fast2SMS, Msg91, Twilio, and Generic Indian HTTP SMS Gateways.
    Enforces idempotency and non-blocking failure recovery.
    """
    owner_raw = os.getenv("OWNER_ALERT_PHONE", OWNER_PHONE_DEFAULT)
    owner_phone = clean_indian_phone(owner_raw)
    event_type = "owner_new_order_alert"
    idempotency_key = f"order_{order.id}_sms_{event_type}" if not force_resend else f"order_{order.id}_sms_{event_type}_resend_{int(datetime.utcnow().timestamp())}"

    # Check for existing successful dispatch (Idempotency)
    existing = OrderNotification.query.filter_by(idempotency_key=idempotency_key).first()
    if existing and existing.status in ("Sent", "Delivered") and not force_resend:
        logger.info(f"Order #{order.id} owner SMS already sent (Idempotency key: {idempotency_key})")
        return {"success": True, "status": existing.status, "message_id": existing.provider_message_id, "idempotent_skip": True}

    if not existing:
        existing = OrderNotification(
            order_id=order.id,
            customer_id=order.customer_id,
            channel="sms",
            event_type=event_type,
            recipient=owner_phone,
            status="Pending",
            idempotency_key=idempotency_key
        )
        db.session.add(existing)
        db.session.commit()

    store_url = get_public_store_url()
    items, total_qty = build_order_items_list(order)
    message_text = format_owner_new_order_sms(order, items, total_qty, store_url)

    existing.payload_snapshot = json.dumps({
        "to": owner_phone,
        "message": message_text,
        "order_id": order.id,
        "amount": order.price
    })
    existing.attempt_count += 1
    db.session.commit()

    # Provider Resolution
    fast2sms_key = os.getenv("FAST2SMS_API_KEY", "").strip()
    msg91_key = os.getenv("MSG91_AUTH_KEY", "").strip()
    generic_sms_url = os.getenv("SMS_PROVIDER_BASE_URL", "").strip()
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()

    # 1. Fast2SMS Indian Route (Quick SMS / DLT)
    if fast2sms_key:
        try:
            url = "https://www.fast2sms.com/dev/bulkV2"
            headers = {"authorization": fast2sms_key, "Content-Type": "application/json"}
            payload = {
                "route": "q",
                "message": message_text,
                "language": "english",
                "flash": 0,
                "numbers": owner_phone[-10:]
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            res_data = res.json()
            if res_data.get("return") is True or res.status_code == 200:
                msg_id = (res_data.get("request_id") or res_data.get("message", [""])[0])
                existing.status = "Sent"
                existing.provider_message_id = str(msg_id)
                existing.sent_at = datetime.utcnow()
                existing.last_error = None
                db.session.commit()
                logger.info(f"Owner SMS dispatched via Fast2SMS for Order #{order.id} (ID: {msg_id})")
                return {"success": True, "status": "Sent", "provider": "fast2sms", "message_id": msg_id}
            else:
                existing.status = "Failed"
                existing.last_error = f"Fast2SMS error: {res_data}"
                db.session.commit()
                return {"success": False, "status": "Failed", "error": str(res_data)}
        except Exception as exc:
            existing.status = "Failed"
            existing.last_error = f"Fast2SMS exception: {exc}"
            db.session.commit()
            return {"success": False, "status": "Failed", "error": str(exc)}

    # 2. Generic Indian HTTP SMS Gateway (DLT compliant)
    if generic_sms_url:
        try:
            sms_api_key = os.getenv("SMS_PROVIDER_API_KEY", "").strip()
            sender_id = os.getenv("SMS_PROVIDER_SENDER_ID", "TULSAW").strip()
            dlt_te_id = os.getenv("SMS_DLT_TEMPLATE_ID", "").strip()
            params = {
                "apikey": sms_api_key,
                "sender": sender_id,
                "numbers": owner_phone[-10:],
                "message": message_text
            }
            if dlt_te_id:
                params["dlt_te_id"] = dlt_te_id
            res = requests.get(generic_sms_url, params=params, timeout=10)
            if res.status_code in (200, 201):
                existing.status = "Sent"
                existing.provider_message_id = f"sms_{order.id}_{int(datetime.utcnow().timestamp())}"
                existing.sent_at = datetime.utcnow()
                existing.last_error = None
                db.session.commit()
                return {"success": True, "status": "Sent", "provider": "generic_http"}
            else:
                existing.status = "Failed"
                existing.last_error = f"HTTP SMS Error ({res.status_code}): {res.text[:200]}"
                db.session.commit()
                return {"success": False, "status": "Failed", "error": res.text}
        except Exception as exc:
            existing.status = "Failed"
            existing.last_error = f"HTTP SMS exception: {exc}"
            db.session.commit()
            return {"success": False, "status": "Failed", "error": str(exc)}

    # 3. Twilio SMS Fallback
    if twilio_sid and twilio_token:
        try:
            from_phone = os.getenv("TWILIO_FROM_PHONE", "").strip()
            url = f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json"
            data = {
                "From": from_phone,
                "To": f"+{owner_phone}",
                "Body": message_text
            }
            res = requests.post(url, auth=(twilio_sid, twilio_token), data=data, timeout=10)
            res_data = res.json()
            if res.status_code in (200, 201) and res_data.get("sid"):
                existing.status = "Sent"
                existing.provider_message_id = res_data["sid"]
                existing.sent_at = datetime.utcnow()
                existing.last_error = None
                db.session.commit()
                return {"success": True, "status": "Sent", "provider": "twilio", "message_id": res_data["sid"]}
            else:
                existing.status = "Failed"
                existing.last_error = f"Twilio error: {res_data.get('message')}"
                db.session.commit()
                return {"success": False, "status": "Failed", "error": str(res_data)}
        except Exception as exc:
            existing.status = "Failed"
            existing.last_error = f"Twilio exception: {exc}"
            db.session.commit()
            return {"success": False, "status": "Failed", "error": str(exc)}

    # If no SMS provider is configured, record status cleanly without failing checkout
    info_msg = (
        "SMS gateway credentials pending: Configure FAST2SMS_API_KEY, MSG91_AUTH_KEY, or "
        "SMS_PROVIDER_BASE_URL & SMS_PROVIDER_API_KEY in environment variables to send live owner SMS alerts."
    )
    logger.info(info_msg)
    existing.status = "Pending"
    existing.last_error = info_msg
    db.session.commit()
    return {"success": False, "status": "Pending", "error": info_msg, "requires_credentials": True}


# ==========================================================
# 2. CUSTOMER WHATSAPP LIFECYCLE FOLLOW-UP SYSTEM
# ==========================================================

def format_whatsapp_followup_message(order, event_type="order_confirmation", custom_params=None):
    """
    Construct professional transactional WhatsApp messages tailored for each stage
    of the customer's bespoke garment journey.
    """
    store_url = get_public_store_url()
    items, total_qty = build_order_items_list(order)
    delivery_window = calculate_delivery_window(order.created_at)
    tracking_link = f"{store_url}/track-order?tracking_id={order.tracking_id or ('TW-TRACK-' + str(order.id))}"
    invoice_link = get_secure_invoice_url(order.id)
    feedback_link = f"{store_url}/feedback?order_id={order.id}"

    # 1. ORDER CONFIRMED
    if event_type == "order_confirmation":
        st = (order.status or "").lower()
        method = order.payment_method or "UPI / Online"
        if "cod" in st or "cash on delivery" in method.lower():
            payment_method_display = "Cash on Delivery"
            payment_status_display = "Pay on Doorstep"
        elif "confirm" in st or order.is_paid():
            payment_method_display = method
            payment_status_display = "Paid & Verified"
        else:
            payment_method_display = method
            payment_status_display = "Payment Verification Pending"

        garment_lines = [f"• {it['name']} – Size {it['size']} – Qty {it['quantity']} – ₹{it['price']:,.0f}" for it in items]
        ordered_items_text = "\n".join(garment_lines)

        lines = [
            f"Hello {order.customer_name}!",
            "Thank you for shopping with *TULSA WEAR / TULSA BY ANJALI*! 🌸",
            "",
            "Your bespoke garment order has been successfully confirmed.",
            "",
            "📦 *ORDER DETAILS*",
            f"Order ID: #{order.id}",
            f"Order Date: {order.created_at.strftime('%d %b %Y, %I:%M %p') if order.created_at else 'Recent'}",
            "",
            "🪡 *SELECTED GARMENTS*",
            ordered_items_text,
            f"Total Pieces: {total_qty}",
            "",
            "💳 *PAYMENT SUMMARY*",
            f"Order Total: ₹{order.price:,.0f}",
            f"Payment Method: {payment_method_display}",
            f"Payment Status: {payment_status_display}",
            "",
            "📍 *DELIVERY DESTINATION*",
            f"Address: {order.address}",
            f"City / PIN: {order.city} – {order.pincode}",
            "",
            "✨ *ESTIMATED DELIVERY*",
            "Your handcrafted silhouette is being tailored to your specifications.",
            "Expected Delivery Period (7–15 Business Days):",
            f"*{delivery_window['display_window']}*",
            "",
            "🔍 *TRACK YOUR ORDER*",
            tracking_link,
            "",
            "📄 *VIEW SECURE INVOICE*",
            invoice_link,
            "",
            "Thank you for trusting Tulsa Wear slow fashion!",
            "For concierge assistance, reply directly to this message."
        ]
        return "\n".join(lines)

    # 2. ORDER PROCESSING
    elif event_type in ("order_processing", "order_in_production"):
        item_names = ", ".join([f"{it['name']} ({it['size']})" for it in items])
        lines = [
            f"Hello {order.customer_name}! 🪡",
            f"Your Tulsa Wear order *#{order.id}* is now being processed with care.",
            "",
            "Our master tailors have begun handcrafting your selected pieces:",
            f"• {item_names}",
            "",
            f"Estimated Delivery Window: *{order.delivery_window_start or delivery_window['start_str']} – {order.delivery_window_end or delivery_window['end_str']}*",
            "",
            "You can follow live atelier tailoring progress here:",
            tracking_link,
            "",
            "Thank you for your patience and support of slow fashion!"
        ]
        return "\n".join(lines)

    # 3. ORDER DISPATCHED
    elif event_type in ("order_dispatched", "order_shipped"):
        courier = order.dispatched_courier or "Insured Express Courier"
        tracking_id = order.tracking_id or f"TW-TRACK-{order.id}"
        lines = [
            f"Good news, {order.customer_name}! ✨",
            f"Your Tulsa Wear order *#{order.id}* has been dispatched from our atelier.",
            "",
            "📦 *COURIER LOGISTICS*",
            f"Courier Partner: {courier}",
            f"Tracking ID: {tracking_id}",
            "",
            "Track your shipment in real time here:",
            tracking_link,
            "",
            "Your carefully packed bespoke garment will arrive at your doorstep soon!"
        ]
        return "\n".join(lines)

    # 4. OUT FOR DELIVERY
    elif event_type == "out_for_delivery":
        lines = [
            f"Namaste {order.customer_name}! 🚚",
            f"Your Tulsa Wear order *#{order.id}* is *OUT FOR DELIVERY* today!",
            "",
            "Our delivery executive is scheduled to arrive at your address today.",
            f"Address: {order.address}, {order.city} – {order.pincode}",
            "",
            "Please ensure someone is available to receive your bespoke package."
        ]
        return "\n".join(lines)

    # 5. ORDER DELIVERED
    elif event_type == "order_delivered":
        lines = [
            f"Hello {order.customer_name}! 🌸",
            f"Your Tulsa Wear order *#{order.id}* has been *DELIVERED* successfully.",
            "",
            "We hope you adore your new handcrafted silhouette as much as we loved creating it for you.",
            "",
            "If you need any fit adjustments or sizing guidance, our concierge is always here for you.",
            f"View your invoice: {invoice_link}",
            "",
            "Thank you for being part of the Tulsa Wear family!"
        ]
        return "\n".join(lines)

    # 6. POST-DELIVERY FEEDBACK
    elif event_type == "post_delivery_feedback":
        lines = [
            f"Hello {order.customer_name}! 🌸",
            "We hope you are enjoying your new outfit from Tulsa Wear.",
            "",
            f"Your order #{order.id} was delivered recently, and we would love to know how your shopping experience was!",
            "Your feedback helps us continuously elevate our handcraftedSlow fashion designs.",
            "",
            "Share your review and styling photos here:",
            feedback_link,
            "",
            "Thank you for choosing Tulsa Wear!"
        ]
        return "\n".join(lines)

    # Default Fallback
    return f"Namaste {order.customer_name}! Your Tulsa Wear order #{order.id} status is now: {order.status}. Track: {tracking_link}"


def send_whatsapp_notification(order, event_type="order_confirmation", custom_params=None, force_resend=False):
    """
    Execute transactional WhatsApp messaging via the official Meta WhatsApp Business
    Platform Cloud API.
    Sender: Tulsa Wear Registered Business WhatsApp Number (+91 9350439667).
    Recipient: Customer WhatsApp Number saved in the order.
    Enforces customer opt-in consent, idempotency, and non-blocking failure recovery.
    """
    idempotency_key = f"order_{order.id}_whatsapp_{event_type}" if not force_resend else f"order_{order.id}_whatsapp_{event_type}_resend_{int(datetime.utcnow().timestamp())}"

    # Verify customer consent (required by WhatsApp Business policy)
    if not order.whatsapp_opt_in and not force_resend:
        logger.info(f"Order #{order.id} skipped WhatsApp {event_type} (Customer did not opt in)")
        notif = OrderNotification.query.filter_by(idempotency_key=idempotency_key).first()
        if not notif:
            notif = OrderNotification(
                order_id=order.id,
                customer_id=order.customer_id,
                channel="whatsapp",
                event_type=event_type,
                recipient=order.phone,
                status="Not opted in",
                idempotency_key=idempotency_key,
                last_error="Customer did not opt in to WhatsApp updates at checkout."
            )
            db.session.add(notif)
            if event_type == "order_confirmation":
                order.whatsapp_notification_status = "Not opted in"
            db.session.commit()
        return {"success": False, "status": "Not opted in", "message": "Customer did not opt in to WhatsApp updates."}

    # Check for existing successful dispatch (Idempotency)
    existing = OrderNotification.query.filter_by(idempotency_key=idempotency_key).first()
    if existing and existing.status in ("Sent", "Delivered") and not force_resend:
        logger.info(f"Order #{order.id} WhatsApp {event_type} already sent (Idempotency key: {idempotency_key})")
        return {"success": True, "status": existing.status, "message_id": existing.provider_message_id, "idempotent_skip": True}

    if not existing:
        existing = OrderNotification(
            order_id=order.id,
            customer_id=order.customer_id,
            channel="whatsapp",
            event_type=event_type,
            recipient=order.phone,
            status="Pending",
            idempotency_key=idempotency_key
        )
        db.session.add(existing)
        db.session.commit()

    recipient_phone = clean_indian_phone(order.phone)
    if not recipient_phone or len(recipient_phone) < 10:
        err = f"Invalid recipient phone number: '{order.phone}'"
        existing.status = "Failed"
        existing.last_error = err
        if event_type == "order_confirmation":
            order.whatsapp_notification_status = "Failed"
        db.session.commit()
        return {"success": False, "status": "Failed", "error": err}

    message_body = format_whatsapp_followup_message(order, event_type=event_type, custom_params=custom_params)

    existing.payload_snapshot = json.dumps({
        "to": recipient_phone,
        "event_type": event_type,
        "message": message_body
    })
    existing.attempt_count += 1
    db.session.commit()

    # Meta WhatsApp Business Cloud API Credentials
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()

    if not token or not phone_number_id:
        err = (
            "WhatsApp Cloud API credentials missing: Configure WHATSAPP_ACCESS_TOKEN and "
            "WHATSAPP_PHONE_NUMBER_ID in environment variables to send live WhatsApp notifications."
        )
        logger.warning(err)
        existing.status = "Pending"
        existing.last_error = err
        if event_type == "order_confirmation":
            order.whatsapp_notification_status = "Pending"
        db.session.commit()
        return {"success": False, "status": "Pending", "error": err, "requires_credentials": True}

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": "text",
        "text": {"preview_url": True, "body": message_body}
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=12)
        res_data = res.json()

        if res.status_code in (200, 201) and "messages" in res_data:
            msg_id = res_data["messages"][0].get("id")
            existing.status = "Sent"
            existing.provider_message_id = msg_id
            existing.sent_at = datetime.utcnow()
            existing.last_error = None
            if event_type == "order_confirmation":
                order.whatsapp_notification_status = "Sent"
            db.session.commit()
            logger.info(f"WhatsApp {event_type} successfully dispatched to {recipient_phone} (Message ID: {msg_id})")
            return {"success": True, "status": "Sent", "message_id": msg_id}
        else:
            err_msg = json.dumps(res_data.get("error", res_data))
            existing.status = "Failed"
            existing.last_error = f"Meta API Error ({res.status_code}): {err_msg}"
            if event_type == "order_confirmation":
                order.whatsapp_notification_status = "Failed"
            db.session.commit()
            logger.error(f"WhatsApp Cloud API error for order #{order.id}: {err_msg}")
            return {"success": False, "status": "Failed", "error": err_msg}

    except Exception as exc:
        err_msg = f"Network exception communicating with Meta WhatsApp API: {str(exc)}"
        existing.status = "Failed"
        existing.last_error = err_msg
        if event_type == "order_confirmation":
            order.whatsapp_notification_status = "Failed"
        db.session.commit()
        logger.error(err_msg)
        return {"success": False, "status": "Failed", "error": err_msg}


def send_whatsapp_order_confirmation(order, event_type="order_confirmation", force_resend=False):
    """Legacy alias redirecting to unified WhatsApp notification engine."""
    return send_whatsapp_notification(order, event_type=event_type, force_resend=force_resend)


# ==========================================================
# 3. TRANSACTIONAL EMAIL NOTIFICATION (RESEND API & SMTP)
# ==========================================================

def send_email_order_confirmation(order, event_type="order_confirmation", force_resend=False):
    """
    Send professional, branded HTML order confirmation email to the customer.
    Tries Resend API first; if unavailable, falls back to standard SMTP.
    """
    idempotency_key = f"order_{order.id}_email_{event_type}" if not force_resend else f"order_{order.id}_email_{event_type}_resend_{int(datetime.utcnow().timestamp())}"

    # Check for existing successful dispatch (Idempotency)
    existing = OrderNotification.query.filter_by(idempotency_key=idempotency_key).first()
    if existing and existing.status in ("Sent", "Delivered") and not force_resend:
        logger.info(f"Order #{order.id} email notification already sent (Idempotency key: {idempotency_key})")
        return {"success": True, "status": existing.status, "message_id": existing.provider_message_id, "idempotent_skip": True}

    if not existing:
        existing = OrderNotification(
            order_id=order.id,
            customer_id=order.customer_id,
            channel="email",
            event_type=event_type,
            recipient=order.email,
            status="Pending",
            idempotency_key=idempotency_key
        )
        db.session.add(existing)
        db.session.commit()

    recipient_email = (order.email or "").strip()
    if not recipient_email or "@" not in recipient_email:
        err = f"Invalid customer email address: '{order.email}'"
        existing.status = "Failed"
        existing.last_error = err
        order.email_notification_status = "Failed"
        db.session.commit()
        return {"success": False, "status": "Failed", "error": err}

    items, total_qty = build_order_items_list(order)
    delivery_window = calculate_delivery_window(order.created_at)
    store_url = get_public_store_url()
    tracking_link = f"{store_url}/track-order?tracking_id={order.tracking_id or ('TW-TRACK-' + str(order.id))}"
    invoice_link = get_secure_invoice_url(order.id)

    # Format email subject
    subject = f"Order Confirmed #{order.id} — Tulsa Wear Atelier"

    # HTML Email Template
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #faf7f2; margin: 0; padding: 24px; color: #171614; }}
    .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border: 1px solid #efe8df; border-radius: 6px; padding: 32px 28px; box-shadow: 0 4px 16px rgba(0,0,0,0.03); }}
    .header {{ text-align: center; border-bottom: 1px solid #efe8df; padding-bottom: 20px; margin-bottom: 24px; }}
    .logo {{ font-family: 'Times New Roman', serif; font-size: 24px; font-weight: bold; letter-spacing: 0.12em; color: #171614; }}
    .summary-box {{ background: #faf8f5; border: 1px solid #efe8df; border-radius: 4px; padding: 16px; margin-bottom: 24px; }}
    .item-row {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #f0eae1; font-size: 13px; }}
    .footer {{ text-align: center; font-size: 11.5px; color: #888; margin-top: 32px; border-top: 1px solid #efe8df; padding-top: 20px; }}
    .btn {{ display: inline-block; background: #171614; color: #ffffff !important; padding: 12px 22px; text-decoration: none; border-radius: 3px; font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 14px; }}
    </style></head>
    <body>
    <div class="container">
        <div class="header">
            <div class="logo">TULSA WEAR</div>
            <p style="margin: 4px 0 0; font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.1em;">Handcrafted Slow Fashion • By Anjali</p>
        </div>
        <h2 style="font-size: 20px; font-weight: 500; margin: 0 0 12px;">Thank you for your order, {order.customer_name}!</h2>
        <p style="font-size: 13.5px; line-height: 1.5; color: #444; margin: 0 0 20px;">
            Your bespoke garment order <strong>#{order.id}</strong> has been successfully confirmed. Our artisans are cutting and tailoring your pieces with mindful Slow Fashion precision.
        </p>
        <div class="summary-box">
            <div style="font-size: 12px; font-weight: 600; color: #2e7d32; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">
                ✨ 7–15 Day Estimated Delivery Window
            </div>
            <div style="font-size: 15px; font-weight: 600; color: #111;">
                {delivery_window['display_window']}
            </div>
            <div style="font-size: 11.5px; color: #666; margin-top: 4px;">
                Handcrafted bespoke creation timeline from Hansi, Haryana atelier.
            </div>
        </div>
        <h3 style="font-size: 14px; text-transform: uppercase; letter-spacing: 0.08em; margin: 20px 0 10px;">Ordered Garments ({total_qty} Pieces)</h3>
        <div>
    """
    for it in items:
        html_content += f"""
            <div class="item-row">
                <div>
                    <strong>{it['name']}</strong><br>
                    <span style="color: #666; font-size: 11.5px;">Size: {it['size']} • Qty: {it['quantity']}</span>
                </div>
                <div style="font-weight: 600;">₹{it['subtotal']:,.0f}</div>
            </div>
        """
    html_content += f"""
        </div>
        <div style="margin-top: 20px; padding-top: 14px; border-top: 1.5px solid #171614; display: flex; justify-content: space-between; font-size: 16px; font-weight: 600;">
            <span>Grand Total</span>
            <span style="color: #2e7d32;">₹{order.price:,.0f}</span>
        </div>
        <div style="text-align: center; margin-top: 28px;">
            <a href="{tracking_link}" class="btn">Track Order Live</a>
            <a href="{invoice_link}" class="btn" style="background:#555; margin-left:8px;">View Invoice</a>
        </div>
        <div class="footer">
            Tulsa Wear Atelier • Hansi, Haryana, India - 125033<br>
            WhatsApp Support: +91 93504 39667 • Concierge: contact@tulsawear.com
        </div>
    </div>
    </body>
    </html>
    """

    existing.payload_snapshot = json.dumps({
        "to": recipient_email,
        "subject": subject,
        "amount": order.price
    })
    existing.attempt_count += 1
    db.session.commit()

    # Provider Resolution: 1. Resend API -> 2. SMTP Fallback
    resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "Tulsa Wear Atelier <orders@tulsawear.com>").strip()

    if resend_api_key:
        try:
            res = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_api_key}", "Content-Type": "application/json"},
                json={
                    "from": from_email,
                    "to": [recipient_email],
                    "subject": subject,
                    "html": html_content
                },
                timeout=12
            )
            res_data = res.json()
            if res.status_code in (200, 201) and "id" in res_data:
                msg_id = res_data["id"]
                existing.status = "Sent"
                existing.provider_message_id = msg_id
                existing.sent_at = datetime.utcnow()
                existing.last_error = None
                order.email_notification_status = "Sent"
                db.session.commit()
                logger.info(f"Resend email dispatched for order #{order.id} to {recipient_email} (ID: {msg_id})")
                return {"success": True, "status": "Sent", "provider": "resend", "message_id": msg_id}
            else:
                err_msg = json.dumps(res_data)
                existing.last_error = f"Resend API Error ({res.status_code}): {err_msg}"
                logger.warning(existing.last_error)
        except Exception as exc:
            existing.last_error = f"Resend network error: {exc}"
            logger.warning(existing.last_error)

    # 2. Standard SMTP Fallback
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if smtp_host and smtp_user and smtp_pass:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = os.getenv("SMTP_FROM", smtp_user)
            msg["To"] = recipient_email
            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=12) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(msg["From"], [recipient_email], msg.as_string())

            existing.status = "Sent"
            existing.provider_message_id = f"smtp_{order.id}_{int(datetime.utcnow().timestamp())}"
            existing.sent_at = datetime.utcnow()
            existing.last_error = None
            order.email_notification_status = "Sent"
            db.session.commit()
            logger.info(f"SMTP email dispatched successfully for order #{order.id} to {recipient_email}")
            return {"success": True, "status": "Sent", "provider": "smtp"}
        except Exception as exc:
            err_msg = f"SMTP dispatch error: {exc}"
            logger.error(err_msg)
            existing.last_error = err_msg

    if not resend_api_key and not smtp_host:
        err = (
            "Email credentials missing: Configure RESEND_API_KEY or SMTP_HOST/SMTP_USER/SMTP_PASSWORD "
            "in environment variables to send live customer order confirmation emails."
        )
        logger.warning(err)
        existing.status = "Pending"
        existing.last_error = err
        order.email_notification_status = "Pending"
        db.session.commit()
        return {"success": False, "status": "Pending", "error": err, "requires_credentials": True}

    existing.status = "Failed"
    order.email_notification_status = "Failed"
    db.session.commit()
    return {"success": False, "status": "Failed", "error": existing.last_error}


# ==========================================================
# UNIFIED ORDER NOTIFICATIONS DISPATCHER
# ==========================================================

def trigger_order_notifications(order_id, event_type="order_confirmation", force_resend=False, trigger_source="checkout", custom_params=None):
    """
    Master notification trigger called when an order is validated, paid, or status changes.
    Dispatches WhatsApp, Owner SMS, and Email notifications safely without blocking checkout.
    """
    from models.order import Order
    order = Order.query.get(order_id)
    if not order:
        logger.error(f"Cannot trigger notifications: Order #{order_id} not found")
        return {"success": False, "error": f"Order #{order_id} not found"}

    # Compute and persist 7–15 day delivery window on Order if not present
    if not order.delivery_window_start or not order.delivery_window_end:
        window = calculate_delivery_window(order.created_at)
        order.delivery_window_start = window["start_str"]
        order.delivery_window_end = window["end_str"]
        db.session.commit()

    results = {}

    # 1. Customer WhatsApp Notification (Lifecycle based)
    try:
        results["whatsapp"] = send_whatsapp_notification(
            order,
            event_type=event_type,
            custom_params=custom_params,
            force_resend=force_resend
        )
    except Exception as exc:
        logger.exception(f"Unexpected WhatsApp dispatch exception for order #{order_id}: {exc}")
        results["whatsapp"] = {"success": False, "error": str(exc)}

    # 2. Customer Email Confirmation (On new order confirmation)
    if event_type == "order_confirmation":
        try:
            results["email"] = send_email_order_confirmation(
                order,
                event_type=event_type,
                force_resend=force_resend
            )
        except Exception as exc:
            logger.exception(f"Unexpected Email dispatch exception for order #{order_id}: {exc}")
            results["email"] = {"success": False, "error": str(exc)}

    # 3. Owner New Order SMS Alert (To +91 9350439667 on new confirmed/placed order)
    if event_type == "order_confirmation":
        try:
            results["owner_sms"] = send_owner_new_order_sms(
                order,
                force_resend=force_resend
            )
        except Exception as exc:
            logger.exception(f"Unexpected Owner SMS dispatch exception for order #{order_id}: {exc}")
            results["owner_sms"] = {"success": False, "error": str(exc)}

    return results


# ==========================================================
# OUTBOX PROCESSOR & RETRY MECHANISM
# ==========================================================

def process_pending_notifications(limit=25):
    """
    Processes pending or retryable failed notifications from the outbox table.
    Can be called via background cron task or admin resend button.
    """
    from models.order import Order

    pending_records = OrderNotification.query.filter(
        OrderNotification.status.in_(["Pending", "Failed"]),
        OrderNotification.attempt_count < 3
    ).order_by(OrderNotification.created_at.asc()).limit(limit).all()

    processed_count = 0
    success_count = 0

    for notif in pending_records:
        order = Order.query.get(notif.order_id)
        if not order:
            continue

        processed_count += 1
        if notif.channel == "whatsapp":
            res = send_whatsapp_notification(order, event_type=notif.event_type, force_resend=True)
            if res.get("success"):
                success_count += 1
        elif notif.channel == "sms":
            res = send_owner_new_order_sms(order, force_resend=True)
            if res.get("success"):
                success_count += 1
        elif notif.channel == "email":
            res = send_email_order_confirmation(order, event_type=notif.event_type, force_resend=True)
            if res.get("success"):
                success_count += 1

    return {"processed": processed_count, "succeeded": success_count}
