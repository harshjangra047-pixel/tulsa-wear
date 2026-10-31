"""
Automated WhatsApp & Transactional Email Notification System for Tulsa Wear Atelier.
Provides:
1. Central 7–15 Day Delivery Timeline Calculation (Asia/Kolkata timezone).
2. Official Meta WhatsApp Business Cloud API Integration with consent verification.
3. Haute Couture Responsive Order Confirmation Email (Resend API & SMTP fallback).
4. Idempotency enforcement, Outbox auditing, and Admin resend capabilities.
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python fallback if zoneinfo tzdata is unavailable
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
    Normalize phone number to international 91XXXXXXXXXX format for Meta WhatsApp API.
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
# WHATSAPP BUSINESS CLOUD API INTEGRATION
# ==========================================================

def format_whatsapp_text_message(order, items, total_qty, delivery_window, tracking_link):
    """
    Construct the professional, friendly, and trustworthy transactional
    WhatsApp order confirmation message.
    """
    # 1. Format Payment Status accurately
    st = (order.status or "").lower()
    method = order.payment_method or "UPI / Online"
    if "cod" in st or "cash on delivery" in method.lower():
        payment_method_display = "Cash on Delivery"
        payment_status_display = "Pay on Delivery"
    elif "confirm" in st or order.razorpay_payment_id or order.manual_payment_verified_at:
        payment_method_display = method
        payment_status_display = "Paid"
    else:
        payment_method_display = method
        payment_status_display = "Payment Verification Pending"

    # 2. Format Itemized Garment List
    garment_lines = []
    for it in items:
        garment_lines.append(f"• {it['name']} – Size {it['size']} – Qty {it['quantity']} – ₹{it['price']:,.0f}")
    ordered_items_text = "\n".join(garment_lines)

    # 3. Assemble Complete Message
    lines = [
        f"Hello {order.customer_name}!",
        "Thank you for shopping with *TULSA WEAR*! 🌸",
        "",
        "Your order has been successfully recorded in our atelier archives.",
        "",
        "📦 *ORDER DETAILS*",
        f"Order ID: #{order.id}",
        "Items Ordered:",
        ordered_items_text,
        f"Total Pieces: {total_qty}",
        f"Order Total: ₹{order.price:,.0f}",
        f"Payment Method: {payment_method_display}",
        f"Payment Status: {payment_status_display}",
        "",
        "✨ *ESTIMATED DELIVERY*",
        "Your handcrafted silhouette is cut and tailored with artisanal precision.",
        "Your order is expected to arrive within 7–15 days from the confirmation date.",
        f"Estimated Delivery Window: *{delivery_window['display_window']}*",
        "",
        "🔍 *TRACK YOUR PIECE*",
        "You can inspect your order progress and live status here:",
        tracking_link,
        "",
        "Thank you for choosing Tulsa Wear slow fashion!",
        "For concierge questions, reply directly to this message."
    ]

    return "\n".join(lines)


def send_whatsapp_order_confirmation(order, event_type="order_confirmation", force_resend=False):
    """
    Execute transactional WhatsApp order confirmation via the official Meta
    WhatsApp Business Platform Cloud API.
    Enforces customer opt-in consent, idempotency, and non-blocking failure recovery.
    """
    idempotency_key = f"order_{order.id}_whatsapp_{event_type}" if not force_resend else f"order_{order.id}_whatsapp_{event_type}_resend_{int(datetime.utcnow().timestamp())}"

    # Verify customer consent
    if not order.whatsapp_opt_in and not force_resend:
        logger.info(f"Order #{order.id} skipped WhatsApp confirmation (Customer did not opt in)")
        # Check if record exists
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
                last_error="Customer did not check the WhatsApp updates consent checkbox at checkout."
            )
            db.session.add(notif)
            order.whatsapp_notification_status = "Not opted in"
            db.session.commit()
        return {"success": False, "status": "Not opted in", "message": "Customer did not opt in to WhatsApp updates."}

    # Check for existing successful dispatch (Idempotency)
    existing = OrderNotification.query.filter_by(idempotency_key=idempotency_key).first()
    if existing and existing.status in ("Sent", "Delivered") and not force_resend:
        logger.info(f"Order #{order.id} WhatsApp notification already sent (Idempotency key: {idempotency_key})")
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
        order.whatsapp_notification_status = "Failed"
        db.session.commit()
        return {"success": False, "status": "Failed", "error": err}

    # Compile order details & delivery window
    items, total_qty = build_order_items_list(order)
    delivery_window = calculate_delivery_window(order.created_at)
    tracking_link = f"{get_public_store_url()}/track-order?tracking_id={order.tracking_id or ('TW-TRACK-' + str(order.id))}"
    message_body = format_whatsapp_text_message(order, items, total_qty, delivery_window, tracking_link)

    existing.payload_snapshot = json.dumps({
        "to": recipient_phone,
        "items": items,
        "delivery_window": delivery_window["display_window"],
        "message": message_body
    })
    existing.attempt_count += 1
    db.session.commit()

    # Meta WhatsApp Business Cloud API Environment Credentials
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    template_name = os.getenv("WHATSAPP_TEMPLATE_NAME", "tulsa_order_confirmation").strip()
    template_lang = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US").strip()

    if not token or not phone_number_id:
        err = (
            "WhatsApp Cloud API credentials missing: Configure WHATSAPP_ACCESS_TOKEN and "
            "WHATSAPP_PHONE_NUMBER_ID in environment variables to send live WhatsApp notifications."
        )
        logger.warning(err)
        existing.status = "Pending"
        existing.last_error = err
        order.whatsapp_notification_status = "Pending"
        db.session.commit()
        return {"success": False, "status": "Pending", "error": err, "requires_credentials": True}

    # Attempt official Meta Cloud API dispatch
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Format payload (supports approved template or direct text during 24h window)
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
            order.whatsapp_notification_status = "Sent"
            db.session.commit()
            logger.info(f"WhatsApp order confirmation successfully dispatched to {recipient_phone} (Message ID: {msg_id})")
            return {"success": True, "status": "Sent", "message_id": msg_id}
        else:
            err_msg = json.dumps(res_data.get("error", res_data))
            existing.status = "Failed"
            existing.last_error = f"Meta API Error ({res.status_code}): {err_msg}"
            order.whatsapp_notification_status = "Failed"
            db.session.commit()
            logger.error(f"WhatsApp Cloud API error for order #{order.id}: {err_msg}")
            return {"success": False, "status": "Failed", "error": err_msg}

    except Exception as exc:
        err_msg = f"Network exception communicating with Meta WhatsApp API: {str(exc)}"
        existing.status = "Failed"
        existing.last_error = err_msg
        order.whatsapp_notification_status = "Failed"
        db.session.commit()
        logger.error(err_msg)
        return {"success": False, "status": "Failed", "error": err_msg}


# ==========================================================
# TRANSACTIONAL EMAIL NOTIFICATION (RESEND API & SMTP)
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

    # Compile order details & delivery window
    items, total_qty = build_order_items_list(order)
    delivery_window = calculate_delivery_window(order.created_at)
    tracking_url = f"{get_public_store_url()}/track-order?tracking_id={order.tracking_id or ('TW-TRACK-' + str(order.id))}"
    support_email = os.getenv("SUPPORT_EMAIL", "contact@tulsawear.com")
    support_phone = os.getenv("SUPPORT_PHONE", "919350439667")

    # Financial calculations
    subtotal = sum(it["subtotal"] for it in items)
    discount_amount = float(order.discount_amount or 0.0)
    shipping_fee = float(order.shipping_fee or 0.0)

    # Render HTML template
    try:
        render_kwargs = dict(
            order=order,
            items=items,
            total_qty=total_qty,
            delivery_window=delivery_window["display_window"],
            subtotal=subtotal,
            discount_amount=discount_amount,
            shipping_fee=shipping_fee,
            tracking_url=tracking_url,
            support_email=support_email,
            support_phone_clean=clean_indian_phone(support_phone)
        )
        if not has_request_context() and current_app:
            with current_app.test_request_context("/"):
                html_content = render_template("emails/order_confirmation.html", **render_kwargs)
        else:
            html_content = render_template("emails/order_confirmation.html", **render_kwargs)
    except Exception as exc:
        err = f"Failed to render order confirmation email template: {exc}"
        logger.error(err)
        existing.status = "Failed"
        existing.last_error = err
        order.email_notification_status = "Failed"
        db.session.commit()
        return {"success": False, "status": "Failed", "error": err}

    plain_text = (
        f"Namaste {order.customer_name},\n\n"
        f"Thank you for shopping with Tulsa Wear!\n"
        f"Your order #{order.id} has been successfully confirmed.\n\n"
        f"Estimated Delivery: {delivery_window['display_window']} (7–15 calendar days)\n"
        f"Order Total: ₹{order.price:,.0f}\n"
        f"Payment Method: {order.payment_method or 'UPI / Online'}\n"
        f"Tracking ID: {order.tracking_id or ('TW-TRACK-' + str(order.id))}\n\n"
        f"Track your order here: {tracking_url}\n\n"
        f"Concierge Support: {support_email} | WhatsApp: +91 93504 39667\n"
    )

    existing.payload_snapshot = json.dumps({
        "to": recipient_email,
        "subject": f"Order Confirmed: #{order.id} — Tulsa Wear Atelier",
        "delivery_window": delivery_window["display_window"]
    })
    existing.attempt_count += 1
    db.session.commit()

    subject = f"Order Confirmed: #{order.id} — Tulsa Wear Atelier"
    from_address = os.getenv("EMAIL_FROM_ADDRESS", "Tulsa Wear <orders@tulsawear.com>").strip()

    # Provider 1: Resend API
    resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
    if resend_api_key:
        try:
            res = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": from_address,
                    "to": [recipient_email],
                    "subject": subject,
                    "html": html_content,
                    "text": plain_text
                },
                timeout=12
            )
            res_data = res.json()
            if res.status_code in (200, 201) and res_data.get("id"):
                msg_id = res_data["id"]
                existing.status = "Sent"
                existing.provider_message_id = msg_id
                existing.sent_at = datetime.utcnow()
                existing.last_error = None
                order.email_notification_status = "Sent"
                db.session.commit()
                logger.info(f"Resend email dispatched successfully for order #{order.id} to {recipient_email} (ID: {msg_id})")
                return {"success": True, "status": "Sent", "provider": "resend", "message_id": msg_id}
            else:
                err_msg = f"Resend Error ({res.status_code}): {json.dumps(res_data)}"
                logger.warning(err_msg)
                existing.last_error = err_msg
        except Exception as exc:
            err_msg = f"Resend API network exception: {exc}"
            logger.warning(err_msg)
            existing.last_error = err_msg

    # Provider 2: Standard SMTP Fallback
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if smtp_host:
        try:
            import smtplib
            import ssl
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_user = os.getenv("SMTP_USER", "").strip()
            smtp_pass = os.getenv("SMTP_PASSWORD", "")
            smtp_sender = os.getenv("SMTP_FROM_EMAIL", "").strip() or from_address

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_sender
            msg["To"] = recipient_email

            msg.attach(MIMEText(plain_text, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=12, context=ssl.create_default_context()) as s:
                    if smtp_user and smtp_pass:
                        s.login(smtp_user, smtp_pass)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=12) as s:
                    s.ehlo()
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                    if smtp_user and smtp_pass:
                        s.login(smtp_user, smtp_pass)
                    s.send_message(msg)

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

    # If neither provider is configured, record status cleanly
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

def trigger_order_notifications(order_id, event_type="order_confirmation", force_resend=False, trigger_source="checkout"):
    """
    Master notification trigger called when an order is validated and saved.
    Dispatches both WhatsApp and Email notifications safely without blocking
    or failing checkout.
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

    # 1. WhatsApp confirmation
    try:
        results["whatsapp"] = send_whatsapp_order_confirmation(
            order,
            event_type=event_type,
            force_resend=force_resend
        )
    except Exception as exc:
        logger.exception(f"Unexpected WhatsApp dispatch exception for order #{order_id}: {exc}")
        results["whatsapp"] = {"success": False, "error": str(exc)}

    # 2. Email confirmation
    try:
        results["email"] = send_email_order_confirmation(
            order,
            event_type=event_type,
            force_resend=force_resend
        )
    except Exception as exc:
        logger.exception(f"Unexpected Email dispatch exception for order #{order_id}: {exc}")
        results["email"] = {"success": False, "error": str(exc)}

    return results


# ==========================================================
# OUTBOX PROCESSOR & RETRY MECHANISM
# ==========================================================

def process_pending_notifications(limit=25):
    """
    Processes pending or retryable failed notifications from the outbox table.
    Can be called via background cron task or endpoint.
    """
    from models.order import Order

    # Pick up pending records with attempt_count < 3
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
            res = send_whatsapp_order_confirmation(order, event_type=notif.event_type, force_resend=True)
            if res.get("success"):
                success_count += 1
        elif notif.channel == "email":
            res = send_email_order_confirmation(order, event_type=notif.event_type, force_resend=True)
            if res.get("success"):
                success_count += 1

    return {"processed": processed_count, "succeeded": success_count}
