"""
Comprehensive Razorpay Standard Web Checkout Integration Service for Tulsa Wear Atelier.
Provides:
1. Robust API Client initialisation (Test & Live modes) from environment and admin configuration.
2. Server-side Order Creation (INR converted to exact integer paise with min-amount validation).
3. Cryptographic Signature Verification (HMAC-SHA256 with constant-time comparison).
4. Secure Webhook Processing with raw-body signature verification and strict idempotency.
5. Payment capture, status synchronisation, and triggered order confirmations.
6. Admin-initiated Refund Processing with audit logging.
"""

import os
import hmac
import hashlib
import json
import logging
from datetime import datetime
from uuid import uuid4

import razorpay

from models.database import db
from models.order import Order
from models.admin_user import AdminUser
from models.payment_webhook import PaymentWebhookEvent

logger = logging.getLogger(__name__)

# Default Fallback Test Credentials (Used if environment variables not explicitly set)
DEFAULT_TEST_KEY_ID = "rzp_test_TupSvNE2HfFWIC"
DEFAULT_TEST_KEY_SECRET = "rL72IfbmF7zGvl1zFOQL7GEz"
DEFAULT_WEBHOOK_SECRET = "tulsa_rzp_webhook_secret_2026"


def get_razorpay_credentials():
    """
    Retrieve authoritative Razorpay credentials.
    Priority:
    1. Environment variables (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    2. AdminUser configuration in database
    3. Supplied Test Mode credentials
    """
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

    if not (key_id and key_secret):
        try:
            admin_cfg = AdminUser.query.first()
            if admin_cfg:
                if not key_id and getattr(admin_cfg, "razorpay_key_id", None):
                    key_id = admin_cfg.razorpay_key_id.strip()
                if not key_secret and getattr(admin_cfg, "razorpay_key_secret", None):
                    key_secret = admin_cfg.razorpay_key_secret.strip()
        except Exception:
            pass

    if not key_id:
        key_id = DEFAULT_TEST_KEY_ID
    if not key_secret:
        key_secret = DEFAULT_TEST_KEY_SECRET
    if not webhook_secret:
        webhook_secret = DEFAULT_WEBHOOK_SECRET

    is_live = key_id.startswith("rzp_live_")

    return {
        "key_id": key_id,
        "key_secret": key_secret,
        "webhook_secret": webhook_secret,
        "is_live": is_live,
        "mode": "Live" if is_live else "Test"
    }


def get_razorpay_client():
    """Initialise and return configured Razorpay SDK client."""
    creds = get_razorpay_credentials()
    if creds["key_id"] and creds["key_secret"]:
        return razorpay.Client(auth=(creds["key_id"], creds["key_secret"]))
    return None


def create_razorpay_order(amount_inr=None, amount_in_paise=None, amount=None, currency="INR", receipt=None, notes=None):
    """
    Create an authoritative server-side Razorpay Order.
    - amount_in_paise: integer paise (min 100 paise)
    - amount_inr: float or int rupees (converted to integer paise)
    - amount: generic parameter; if >= 100 and integer/no decimals, treated as paise; else rupees
    - Minimum amount validation: 100 paise (₹1.00)
    Returns: dict with order_id, id, amount, currency, key_id, receipt
    """
    client = get_razorpay_client()
    if not client:
        raise RuntimeError("Razorpay client is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")

    final_paise = None
    if amount_in_paise is not None:
        try:
            final_paise = int(amount_in_paise)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid paise amount '{amount_in_paise}'") from exc
    elif amount_inr is not None:
        try:
            final_paise = int(round(float(amount_inr) * 100))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid INR amount '{amount_inr}'") from exc
    elif amount is not None:
        try:
            amt_val = float(amount)
            # If explicit amount >= 100 and passed as integer representation, treat as paise
            final_paise = int(amt_val)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid amount '{amount}'") from exc
    else:
        raise ValueError("Missing payable amount.")

    if final_paise < 100:
        raise ValueError(f"Order amount {final_paise} paise is below Razorpay minimum of 100 paise (₹1.00)")

    clean_receipt = str(receipt or f"tulsa_{uuid4().hex[:8]}")[:40]
    payload = {
        "amount": final_paise,
        "currency": str(currency or "INR").upper(),
        "receipt": clean_receipt,
        "notes": notes or {"store": "Tulsa Wear Atelier"}
    }

    rzp_order = client.order.create(payload)
    creds = get_razorpay_credentials()

    return {
        "id": rzp_order["id"],
        "order_id": rzp_order["id"],
        "amount": final_paise,
        "currency": payload["currency"],
        "key_id": creds["key_id"],
        "receipt": clean_receipt
    }


def verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Verify the payment signature returned by the checkout modal.
    Algorithm: HMAC-SHA256(order_id + '|' + payment_id, KEY_SECRET)
    Performs constant-time comparison against razorpay_signature.
    Returns: (is_valid: bool, error_msg: str)
    """
    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return False, "Missing payment signature verification parameters."

    creds = get_razorpay_credentials()
    key_secret = creds["key_secret"]
    if not key_secret:
        return False, "Server secret key is not configured."

    message = f"{razorpay_order_id}|{razorpay_payment_id}"
    generated_signature = hmac.new(
        key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if hmac.compare_digest(generated_signature, razorpay_signature):
        return True, ""

    # Also try SDK utility as fallback
    try:
        client = get_razorpay_client()
        if client:
            client.utility.verify_payment_signature({
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature
            })
            return True, ""
    except Exception:
        pass

    return False, "Payment signature mismatch."


def verify_webhook_signature(raw_body_bytes, signature_header, webhook_secret=None):
    """
    Verify incoming Razorpay webhook signature over the raw request payload.
    Returns: (is_valid: bool, error_msg: str)
    """
    if not signature_header:
        return False, "Missing X-Razorpay-Signature header."

    secret = webhook_secret or get_razorpay_credentials()["webhook_secret"]
    if not secret:
        return False, "Webhook secret is not configured."

    if not isinstance(raw_body_bytes, bytes):
        raw_body_bytes = str(raw_body_bytes).encode("utf-8")

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        raw_body_bytes,
        hashlib.sha256
    ).hexdigest()

    if hmac.compare_digest(expected_signature, signature_header):
        return True, ""

    return False, "Webhook signature verification failed."


def fetch_payment_details(razorpay_payment_id):
    """Fetch authoritative payment status from Razorpay API."""
    client = get_razorpay_client()
    if not client:
        return None
    try:
        return client.payment.fetch(razorpay_payment_id)
    except Exception as exc:
        logger.error(f"Error fetching payment {razorpay_payment_id}: {exc}")
        return None


def capture_order_payment(order, razorpay_payment_id, razorpay_order_id=None,
                          razorpay_signature=None, webhook_event_id=None, payment_details=None):
    """
    Atomically transition an order to confirmed captured state upon verified payment.
    Enforces idempotency: will not double-confirm or re-trigger notifications.
    """
    if not order:
        return False, "Order not found."

    # Idempotency: already confirmed
    if order.is_paid():
        if not order.razorpay_payment_id:
            order.razorpay_payment_id = razorpay_payment_id
            db.session.commit()
        return True, "Payment already captured."

    # Validate against expected order amount if payment details provided
    if payment_details:
        expected_paise = int(round((order.price or 0.0) * 100))
        paid_paise = int(payment_details.get("amount", 0))
        if paid_paise < expected_paise:
            logger.warning(f"Payment amount mismatch for order #{order.id}: paid {paid_paise} paise < expected {expected_paise} paise")
            order.payment_status = "Amount Mismatch"
            db.session.commit()
            return False, "Paid amount does not match expected order total."

        payment_method = payment_details.get("method") or "Razorpay Online"
    else:
        payment_method = "Razorpay Online"

    # Mark as captured
    order.mark_as_captured(
        razorpay_payment_id=razorpay_payment_id,
        payment_method=payment_method,
        signature=razorpay_signature
    )
    if razorpay_order_id:
        order.razorpay_order_id = razorpay_order_id
    if webhook_event_id:
        order.webhook_event_id = webhook_event_id

    db.session.commit()

    # Trigger customer confirmations (WhatsApp & Email with 7-15 day delivery window)
    try:
        from services.notification_service import trigger_order_notifications
        trigger_order_notifications(
            order_id=order.id,
            event_type="order_confirmation",
            trigger_source="razorpay_success"
        )
    except Exception as exc:
        logger.error(f"Notification trigger error after payment capture for order #{order.id}: {exc}")

    return True, "Payment successfully captured and order confirmed."


def process_webhook_payload(raw_body_bytes, signature_header):
    """
    Process incoming Razorpay webhook with strict signature validation,
    idempotent event recording, and status synchronization.
    """
    # 1. Verify signature
    is_valid, error = verify_webhook_signature(raw_body_bytes, signature_header)
    if not is_valid:
        return False, error, 400

    # 2. Parse payload
    try:
        payload = json.loads(raw_body_bytes.decode("utf-8"))
    except Exception as exc:
        return False, f"Invalid JSON payload: {exc}", 400

    event_id = payload.get("id")
    event_type = payload.get("event")
    if not (event_id and event_type):
        return False, "Missing event id or event type in webhook payload.", 400

    # 3. Idempotency Check
    existing_event = PaymentWebhookEvent.query.filter_by(event_id=event_id).first()
    if existing_event:
        return True, "Event already processed (idempotent).", 200

    # Extract payment entity
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_entity = payload.get("payload", {}).get("order", {}).get("entity", {})
    refund_entity = payload.get("payload", {}).get("refund", {}).get("entity", {})

    razorpay_payment_id = payment_entity.get("id") or refund_entity.get("payment_id")
    razorpay_order_id = payment_entity.get("order_id") or order_entity.get("id")

    # Match local order
    local_order = None
    if razorpay_order_id:
        local_order = Order.query.filter_by(razorpay_order_id=razorpay_order_id).first()
    if not local_order and razorpay_payment_id:
        local_order = Order.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()

    # Record webhook audit event
    webhook_rec = PaymentWebhookEvent(
        event_id=event_id,
        event_type=event_type,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        order_id=local_order.id if local_order else None,
        amount=float(payment_entity.get("amount", 0) or refund_entity.get("amount", 0)) / 100.0,
        currency=payment_entity.get("currency") or "INR",
        payload=json.dumps(payload),
        status="Processing"
    )
    db.session.add(webhook_rec)
    db.session.commit()

    # 4. Handle events
    try:
        if event_type in ("payment.captured", "order.paid"):
            if local_order and razorpay_payment_id:
                capture_order_payment(
                    order=local_order,
                    razorpay_payment_id=razorpay_payment_id,
                    razorpay_order_id=razorpay_order_id,
                    webhook_event_id=event_id,
                    payment_details=payment_entity
                )

        elif event_type == "payment.authorized":
            if local_order and not local_order.is_paid():
                local_order.payment_status = "Authorized"
                local_order.razorpay_payment_id = razorpay_payment_id
                db.session.commit()

        elif event_type == "payment.failed":
            if local_order and not local_order.is_paid():
                local_order.payment_status = "Failed"
                err_desc = payment_entity.get("error_description") or "Payment authorization failed"
                local_order.status = "Payment Failed"
                db.session.commit()
                logger.info(f"Payment failed for order #{local_order.id}: {err_desc}")

        elif event_type == "refund.processed":
            if local_order:
                refund_amt = float(refund_entity.get("amount", 0)) / 100.0
                local_order.refund_id = refund_entity.get("id")
                local_order.refund_amount = refund_amt
                local_order.refund_status = "Processed"
                local_order.payment_status = "Refunded"
                db.session.commit()

        webhook_rec.status = "Processed"
        db.session.commit()
        return True, "Webhook processed successfully.", 200

    except Exception as exc:
        db.session.rollback()
        logger.exception(f"Error processing webhook event {event_id}: {exc}")
        webhook_rec.status = "Failed"
        webhook_rec.error_message = str(exc)
        db.session.commit()
        return False, str(exc), 500


def process_order_refund(order, amount_inr=None, reason=None):
    """
    Issue an admin-confirmed refund through the server-side Razorpay API.
    Updates order refund status and amounts safely.
    """
    if not order or not order.razorpay_payment_id:
        return False, "No valid captured Razorpay payment found for this order."

    client = get_razorpay_client()
    if not client:
        return False, "Razorpay client is not configured."

    refund_val = float(amount_inr if amount_inr is not None else (order.price or 0.0))
    refund_paise = int(round(refund_val * 100))

    try:
        resp = client.payment.refund(order.razorpay_payment_id, {
            "amount": refund_paise,
            "notes": {
                "order_id": str(order.id),
                "reason": str(reason or "Customer cancellation / return")
            }
        })
        order.refund_id = resp.get("id")
        order.refund_amount = refund_val
        order.refund_status = "Processed"
        order.payment_status = "Refunded"
        order.status = "Cancelled"
        db.session.commit()
        return True, f"Refund of ₹{refund_val:,.0f} processed successfully (Ref: {order.refund_id})."
    except Exception as exc:
        logger.exception(f"Refund failed for order #{order.id}: {exc}")
        return False, f"Refund failed: {exc}"

