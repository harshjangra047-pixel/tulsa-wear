"""
Comprehensive Test Suite for Tulsa Wear Razorpay Payment Gateway Integration.
Validates:
1. Razorpay credentials resolution (Test & Live modes).
2. Integer paise conversion & minimum amount validation (>= 100 paise).
3. HMAC-SHA256 signature verification (valid, tampered, missing).
4. Webhook raw body signature verification and idempotent deduplication.
5. Payment capture state decoupling (payment_status vs ERP production status).
6. Order confirmation & notification trigger behavior on captured payment.
7. Cash on Delivery (COD) workflow remains fully operational.
8. Server-side refund initiation and state transitions.
"""

import os
import json
import hmac
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch, MagicMock

TEST_DB_DIR = Path(tempfile.gettempdir()) / "tulsa-rzp-tests"
TEST_DB_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DB_DIR / f"{uuid4().hex}.db")
os.environ["FLASK_SECRET_KEY"] = "rzp-test-session-secret"
os.environ["ADMIN_PASSWORD"] = "Admin-Test-Pass-9944"
os.environ["ADMIN_USERNAME"] = "test-rzp-admin"
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_TupSvNE2HfFWIC"
os.environ["RAZORPAY_KEY_SECRET"] = "rL72IfbmF7zGvl1zFOQL7GEz"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "tulsa_rzp_webhook_secret_2026"
os.environ["FLASK_ENV"] = "testing"

import app as site
from models.database import db
from models.order import Order
from models.product import Product
from models.admin_user import AdminUser
from models.payment_webhook import PaymentWebhookEvent
from models.order_notification import OrderNotification
from services.payment_service import (
    get_razorpay_credentials,
    get_razorpay_client,
    create_razorpay_order,
    verify_razorpay_signature,
    verify_webhook_signature,
    capture_order_payment,
    process_webhook_payload,
    process_order_refund,
    fetch_payment_details
)


def make_test_order(**kwargs):
    defaults = {
        "product_id": 1,
        "product_name": "Ivory Anarkali Silk Gown",
        "price": 4999.0,
        "customer_name": "Ananya Sharma",
        "phone": "+919876543210",
        "email": "ananya@example.com",
        "address": "404 Fashion Boulevard, Civil Lines",
        "city": "Jaipur",
        "pincode": "302001",
        "size": "M",
        "top_length": "42",
        "sleeves_length": "18",
        "status": "Payment Pending",
        "payment_status": "Pending",
        "payment_method": "Razorpay Online",
        "razorpay_order_id": "order_test_998877",
        "advance_paid": 0.0,
        "balance_due": 4999.0,
        "created_at": datetime.now()
    }
    defaults.update(kwargs)
    return Order(**defaults)


class RazorpayIntegrationTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site.app.config["TESTING"] = True
        site.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = site.app.test_client()

        with site.app.app_context():
            db.create_all()
            if not Product.query.first():
                p = Product(
                    id=1,
                    name="Ivory Anarkali Silk Gown",
                    category="anarkali",
                    price=4999.0,
                    original_price=5999.0,
                    stock=10,
                    image="anarkali.jpg"
                )
                db.session.add(p)
                db.session.commit()

    def setUp(self):
        with site.app.app_context():
            Order.query.delete()
            PaymentWebhookEvent.query.delete()
            db.session.commit()

    # -----------------------------------------------------------
    # TEST 1: Credentials Resolution & SDK Initialization
    # -----------------------------------------------------------
    def test_credentials_resolution(self):
        creds = get_razorpay_credentials()
        self.assertEqual(creds["key_id"], "rzp_test_TupSvNE2HfFWIC")
        self.assertEqual(creds["key_secret"], "rL72IfbmF7zGvl1zFOQL7GEz")
        self.assertEqual(creds["webhook_secret"], "tulsa_rzp_webhook_secret_2026")
        self.assertFalse(creds["is_live"])
        self.assertEqual(creds["mode"], "Test")

        client = get_razorpay_client()
        self.assertIsNotNone(client)

    # -----------------------------------------------------------
    # TEST 2: Exact INR to Integer Paise & Minimum Rule Validation
    # -----------------------------------------------------------
    def test_amount_conversion_and_minimum_validation(self):
        # Normal amount
        with patch("services.payment_service.get_razorpay_client") as mock_client:
            mock_inst = MagicMock()
            mock_inst.order.create.return_value = {"id": "order_mock_123"}
            mock_client.return_value = mock_inst

            res = create_razorpay_order(4999.0, receipt="test_rcpt_1")
            self.assertEqual(res["amount"], 499900)
            self.assertEqual(res["currency"], "INR")
            mock_inst.order.create.assert_called_once()
            call_payload = mock_inst.order.create.call_args[0][0]
            self.assertEqual(call_payload["amount"], 499900)
            self.assertEqual(call_payload["currency"], "INR")

        # Amount below 100 paise (< Rs 1.00) must raise ValueError
        with self.assertRaises(ValueError):
            create_razorpay_order(0.50)

        # Invalid amount types
        with self.assertRaises(ValueError):
            create_razorpay_order("not_a_number")

    # -----------------------------------------------------------
    # TEST 3: Cryptographic HMAC-SHA256 Signature Verification
    # -----------------------------------------------------------
    def test_signature_verification_valid_and_tampered(self):
        order_id = "order_rzp_test_1001"
        payment_id = "pay_rzp_test_5001"
        secret = "rL72IfbmF7zGvl1zFOQL7GEz"

        # Valid signature
        msg = f"{order_id}|{payment_id}"
        valid_sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

        is_valid, err = verify_razorpay_signature(order_id, payment_id, valid_sig)
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

        # Tampered signature
        tampered_sig = valid_sig[:-4] + "ffff"
        is_valid, err = verify_razorpay_signature(order_id, payment_id, tampered_sig)
        self.assertFalse(is_valid)
        self.assertIn("mismatch", err.lower())

        # Mismatched payment id
        is_valid, err = verify_razorpay_signature(order_id, "pay_different_999", valid_sig)
        self.assertFalse(is_valid)

        # Empty parameters
        is_valid, err = verify_razorpay_signature("", payment_id, valid_sig)
        self.assertFalse(is_valid)

    # -----------------------------------------------------------
    # TEST 4: Raw Webhook Payload Verification & Idempotency
    # -----------------------------------------------------------
    def test_webhook_raw_signature_verification(self):
        webhook_secret = "tulsa_rzp_webhook_secret_2026"
        sample_payload = json.dumps({"event": "payment.captured", "id": "evt_test_1"}).encode("utf-8")
        valid_sig = hmac.new(webhook_secret.encode("utf-8"), sample_payload, hashlib.sha256).hexdigest()

        is_valid, err = verify_webhook_signature(sample_payload, valid_sig, webhook_secret)
        self.assertTrue(is_valid)

        invalid_sig = "abcde12345wrongsignature"
        is_valid, err = verify_webhook_signature(sample_payload, invalid_sig, webhook_secret)
        self.assertFalse(is_valid)

    def test_webhook_idempotency_and_event_handling(self):
        with site.app.app_context():
            order = make_test_order(razorpay_order_id="order_webhook_sync_001")
            db.session.add(order)
            db.session.commit()
            order_id = order.id

            event_id = "evt_idempotent_test_999"
            payload_dict = {
                "id": event_id,
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_webhook_999",
                            "order_id": "order_webhook_sync_001",
                            "amount": 499900,
                            "currency": "INR",
                            "status": "captured",
                            "method": "upi"
                        }
                    }
                }
            }
            raw_bytes = json.dumps(payload_dict).encode("utf-8")
            valid_sig = hmac.new("tulsa_rzp_webhook_secret_2026".encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()

            # First invocation: processes successfully
            success, msg, code = process_webhook_payload(raw_bytes, valid_sig)
            self.assertTrue(success)
            self.assertEqual(code, 200)

            # Check order transitioned to captured
            refreshed = db.session.get(Order, order_id)
            self.assertEqual(refreshed.payment_status, "Captured")
            self.assertEqual(refreshed.status, "Confirmed")
            self.assertEqual(refreshed.razorpay_payment_id, "pay_webhook_999")

            # Check audit event recorded
            audit_events = PaymentWebhookEvent.query.filter_by(event_id=event_id).all()
            self.assertEqual(len(audit_events), 1)
            self.assertEqual(audit_events[0].status, "Processed")

            # Second invocation (Identical Payload): Must be recognized as duplicate (Idempotent)
            success2, msg2, code2 = process_webhook_payload(raw_bytes, valid_sig)
            self.assertTrue(success2)
            self.assertEqual(code2, 200)
            self.assertIn("idempotent", msg2.lower())

            # Ensure no duplicate audit record created
            audit_events_after = PaymentWebhookEvent.query.filter_by(event_id=event_id).all()
            self.assertEqual(len(audit_events_after), 1)

    # -----------------------------------------------------------
    # TEST 5: Payment Capture State Decoupling
    # -----------------------------------------------------------
    def test_payment_capture_state_decoupling(self):
        with site.app.app_context():
            order = make_test_order(status="Payment Pending", payment_status="Pending")
            db.session.add(order)
            db.session.commit()

            success, msg = capture_order_payment(
                order=order,
                razorpay_payment_id="pay_decouple_123",
                razorpay_order_id="order_decouple_123",
                razorpay_signature="sig_decouple_123",
                payment_details={"amount": 499900, "currency": "INR", "method": "card"}
            )
            self.assertTrue(success)
            self.assertTrue(order.is_paid())
            self.assertEqual(order.payment_status, "Captured")
            self.assertEqual(order.status, "Confirmed")
            self.assertEqual(order.payment_method, "card")
            self.assertIsNotNone(order.payment_captured_at)
            self.assertEqual(order.advance_paid, 4999.0)
            self.assertEqual(order.balance_due, 0.0)

    # -----------------------------------------------------------
    # TEST 6: Customer Notifications Triggered on Capture
    # -----------------------------------------------------------
    @patch("services.notification_service.trigger_order_notifications")
    def test_notifications_triggered_on_capture(self, mock_notify):
        with site.app.app_context():
            order = make_test_order()
            db.session.add(order)
            db.session.commit()

            capture_order_payment(
                order=order,
                razorpay_payment_id="pay_notify_123",
                razorpay_order_id="order_notify_123",
                payment_details={"amount": 499900, "currency": "INR", "method": "upi"}
            )
            mock_notify.assert_called_once_with(
                order_id=order.id,
                event_type="order_confirmation",
                trigger_source="razorpay_success"
            )

    # -----------------------------------------------------------
    # TEST 7: Cash on Delivery Workflow Remains Operational
    # -----------------------------------------------------------
    def test_cash_on_delivery_path(self):
        with site.app.app_context():
            order = make_test_order(
                payment_method="Cash on Delivery",
                payment_status="Pending",
                status="Confirmed",
                razorpay_payment_id=None,
                razorpay_order_id=None
            )
            db.session.add(order)
            db.session.commit()

            self.assertTrue(order.is_cod())
            self.assertFalse(order.is_paid())
            self.assertEqual(order.payment_method, "Cash on Delivery")
            self.assertEqual(order.status, "Confirmed")

    # -----------------------------------------------------------
    # TEST 8: Server-Side Refund Processing
    # -----------------------------------------------------------
    def test_admin_refund_processing(self):
        with site.app.app_context():
            order = make_test_order(
                payment_status="Captured",
                status="Confirmed",
                razorpay_payment_id="pay_refund_target_777"
            )
            db.session.add(order)
            db.session.commit()

            with patch("services.payment_service.get_razorpay_client") as mock_client:
                mock_inst = MagicMock()
                mock_inst.payment.refund.return_value = {"id": "rfnd_test_9988"}
                mock_client.return_value = mock_inst

                success, msg = process_order_refund(order, amount_inr=4999.0, reason="Customer cancellation")
                self.assertTrue(success)
                self.assertEqual(order.refund_id, "rfnd_test_9988")
                self.assertEqual(order.refund_amount, 4999.0)
                self.assertEqual(order.refund_status, "Processed")
                self.assertEqual(order.payment_status, "Refunded")
                self.assertEqual(order.status, "Cancelled")

    # -----------------------------------------------------------
    # TEST 9: HTTP Endpoint /api/create-order
    # -----------------------------------------------------------
    def test_endpoint_api_create_order(self):
        with site.app.app_context():
            order = make_test_order()
            db.session.add(order)
            db.session.commit()
            order_id = order.id

        with self.client.session_transaction() as sess:
            sess["authorized_order_ids"] = [order_id]

        with patch("services.payment_service.get_razorpay_client") as mock_client:
            mock_inst = MagicMock()
            mock_inst.order.create.return_value = {"id": "order_api_999"}
            mock_client.return_value = mock_inst

            resp = self.client.post("/api/create-order", json={"order_id": order_id})
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["razorpay_order_id"], "order_api_999")
            self.assertEqual(data["amount"], 499900)

    # -----------------------------------------------------------
    # TEST 10: HTTP Endpoint /api/verify-payment
    # -----------------------------------------------------------
    def test_endpoint_api_verify_payment(self):
        with site.app.app_context():
            order = make_test_order(razorpay_order_id="order_http_111")
            db.session.add(order)
            db.session.commit()
            order_id = order.id

        secret = "rL72IfbmF7zGvl1zFOQL7GEz"
        msg = "order_http_111|pay_http_222"
        valid_sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

        with patch("services.payment_service.fetch_payment_details") as mock_fetch:
            mock_fetch.return_value = {
                "id": "pay_http_222",
                "order_id": "order_http_111",
                "amount": 499900,
                "currency": "INR",
                "status": "captured",
                "method": "upi"
            }

            resp = self.client.post("/api/verify-payment", json={
                "order_id": order_id,
                "razorpay_order_id": "order_http_111",
                "razorpay_payment_id": "pay_http_222",
                "razorpay_signature": valid_sig
            })

            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertIn("order-success", data["redirect_url"])

            with site.app.app_context():
                chk = db.session.get(Order, order_id)
                self.assertEqual(chk.payment_status, "Captured")
                self.assertEqual(chk.status, "Confirmed")

    # -----------------------------------------------------------
    # TEST 11: HTTP Endpoint /api/webhooks/razorpay
    # -----------------------------------------------------------
    def test_endpoint_api_webhook(self):
        with site.app.app_context():
            order = make_test_order(razorpay_order_id="order_hook_333")
            db.session.add(order)
            db.session.commit()
            order_id = order.id

        webhook_secret = "tulsa_rzp_webhook_secret_2026"
        evt_id = f"evt_http_{uuid4().hex[:8]}"
        payload = {
            "id": evt_id,
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_hook_444",
                        "order_id": "order_hook_333",
                        "amount": 499900,
                        "currency": "INR",
                        "status": "captured",
                        "method": "card"
                    }
                }
            }
        }
        raw_bytes = json.dumps(payload).encode("utf-8")
        sig = hmac.new(webhook_secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()

        resp = self.client.post(
            "/api/webhooks/razorpay",
            data=raw_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": sig
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

        with site.app.app_context():
            chk = db.session.get(Order, order_id)
            self.assertEqual(chk.payment_status, "Captured")
            self.assertEqual(chk.razorpay_payment_id, "pay_hook_444")

    # -----------------------------------------------------------
    # TEST 12: Error Handling - Minimum Amount (< 100 paise) returns 400
    # -----------------------------------------------------------
    def test_create_order_below_minimum_returns_400(self):
        resp = self.client.post("/api/create-order", json={"amount": 50, "currency": "INR"})
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("100 paise", data["message"])

    # -----------------------------------------------------------
    # TEST 13: Error Handling - Verify Payment Missing Fields returns 400
    # -----------------------------------------------------------
    def test_verify_payment_missing_fields_returns_400(self):
        resp = self.client.post("/api/verify-payment", json={
            "razorpay_order_id": "order_test_123"
            # Missing payment_id and signature
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Missing", data["message"])

    # -----------------------------------------------------------
    # TEST 14: Error Handling - Verify Signature Mismatch returns 400
    # -----------------------------------------------------------
    def test_verify_payment_signature_mismatch_returns_400(self):
        resp = self.client.post("/api/verify-payment", json={
            "razorpay_order_id": "order_test_123",
            "razorpay_payment_id": "pay_test_456",
            "razorpay_signature": "invalid_tampered_signature_string"
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["success"])
        self.assertIn("signature", data["message"].lower())

    # -----------------------------------------------------------
    # TEST 15: Payment Failure Diagnostic Capture
    # -----------------------------------------------------------
    def test_payment_failed_records_diagnostics(self):
        with site.app.app_context():
            o = make_test_order(customer_name="Failure Test User")
            db.session.add(o)
            db.session.commit()
            order_id = o.id

        with self.client.session_transaction() as sess:
            sess["authorized_order_ids"] = [order_id]

        fail_payload = {
            "code": "BAD_REQUEST_ERROR",
            "description": "Payment was cancelled by the customer",
            "reason": "payment_cancelled",
            "source": "customer",
            "step": "payment_authentication",
            "device": "Mobile"
        }
        resp = self.client.post(f"/payment-failed/{order_id}", json=fail_payload)
        self.assertEqual(resp.status_code, 200)

        with site.app.app_context():
            chk = db.session.get(Order, order_id)
            self.assertEqual(chk.status, "Payment Failed")
            self.assertEqual(chk.payment_error_code, "BAD_REQUEST_ERROR")
            self.assertIn("cancelled", chk.payment_error_desc.lower())
            self.assertEqual(chk.payment_device, "Mobile")
            self.assertEqual(chk.payment_environment, "test")

    # -----------------------------------------------------------
    # TEST 16: Payment Step View Renders Official Razorpay Checkout & Test Guidance
    # -----------------------------------------------------------
    def test_payment_step_renders_razorpay_checkout(self):
        with site.app.app_context():
            o = make_test_order(customer_name="Checkout Render Test")
            db.session.add(o)
            db.session.commit()
            order_id = o.id

        with self.client.session_transaction() as sess:
            sess["authorized_order_ids"] = [order_id]

        resp = self.client.get(f"/payment-step/{order_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("checkout.razorpay.com/v1/checkout.js", body)
        self.assertIn("launchRazorpayModal", body)
        self.assertIn("Test Mode Active", body)
        self.assertIn("success@razorpay", body)

    # -----------------------------------------------------------
    # TEST 17: Order Safe Archiving & Permanent Deletion Rules
    # -----------------------------------------------------------
    def test_order_safe_archive_and_restore(self):
        with site.app.app_context():
            # Paid order cannot be permanently deleted
            paid_order = make_test_order(customer_name="Paid User", payment_status="Captured", status="Confirmed")
            self.assertFalse(paid_order.can_safely_delete_permanently())

            # Unpaid draft order CAN be permanently deleted
            draft_order = make_test_order(customer_name="Draft User", payment_status="Pending", status="Payment Pending", razorpay_payment_id=None)
            self.assertTrue(draft_order.can_safely_delete_permanently())

            # Test archive and restore
            paid_order.archive(admin_username="test_admin", reason="Annual audit archive")
            self.assertTrue(paid_order.is_archived)
            self.assertIsNotNone(paid_order.archived_at)
            self.assertEqual(paid_order.archived_by, "test_admin")

            paid_order.restore()
            self.assertFalse(paid_order.is_archived)
            self.assertIsNone(paid_order.archived_at)

    # -----------------------------------------------------------
    # TEST 18: Admin Delete Order Route Archives Paid Orders without 500 Error
    # -----------------------------------------------------------
    def test_admin_delete_order_safe_archive(self):
        with site.app.app_context():
            o = make_test_order(customer_name="Archive Target", payment_status="Captured", status="Confirmed")
            db.session.add(o)
            db.session.commit()
            order_id = o.id

            # Add child notification record that used to trigger foreign-key 500 error
            notif = OrderNotification(
                order_id=order_id,
                channel="email",
                event_type="order_confirmation",
                recipient="test@example.com",
                status="Sent",
                idempotency_key=f"test_fk_{order_id}"
            )
            db.session.add(notif)
            db.session.commit()

        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
            sess["admin_logged_in"] = True
            sess["admin_user"] = "admin"

        # Calling delete on confirmed/paid order must NOT return 500; it must safely archive
        resp = self.client.post(f"/admin/orders/delete/{order_id}", data={"action": "archive", "reason": "Test archive"})
        self.assertEqual(resp.status_code, 302)

        with site.app.app_context():
            chk = db.session.get(Order, order_id)
            self.assertIsNotNone(chk)
            self.assertTrue(chk.is_archived)
            # Notification child record is intact
            n_chk = OrderNotification.query.filter_by(order_id=order_id).first()
            self.assertIsNotNone(n_chk)

    # -----------------------------------------------------------
    # TEST 19: Owner SMS Alert Generation & Outbox Auditing
    # -----------------------------------------------------------
    def test_owner_new_order_sms_generation(self):
        with site.app.app_context():
            o = make_test_order(customer_name="Pooja Verma", price=3499.0, city="Ludhiana", pincode="141001")
            db.session.add(o)
            db.session.commit()

            from services.notification_service import format_owner_new_order_sms, send_owner_new_order_sms, build_order_items_list
            items, total_qty = build_order_items_list(o)
            sms_text = format_owner_new_order_sms(o, items, total_qty, "https://tulsa-wear.vercel.app")
            self.assertIn("NEW ORDER RECEIVED – TULSA WEAR", sms_text)
            self.assertIn(f"Order: #{o.id}", sms_text)
            self.assertIn("Pooja Verma", sms_text)
            self.assertIn("Rs.3,499", sms_text)
            self.assertIn("Ludhiana", sms_text)
            self.assertIn(f"/invoice/{o.id}", sms_text)

            # Test outbox dispatch record
            res = send_owner_new_order_sms(o)
            self.assertIn("status", res)
            outbox = OrderNotification.query.filter_by(order_id=o.id, channel="sms").first()
            self.assertIsNotNone(outbox)
            self.assertEqual(outbox.recipient, "919350439667")

    # -----------------------------------------------------------
    # TEST 20: Customer WhatsApp Lifecycle Follow-up Formatter
    # -----------------------------------------------------------
    def test_customer_whatsapp_lifecycle_messages(self):
        with site.app.app_context():
            o = make_test_order(customer_name="Meera Kapoor", tracking_id="TW-TRACK-555", dispatched_courier="BlueDart Express")
            from services.notification_service import format_whatsapp_followup_message

            # 1. Confirmed
            msg_conf = format_whatsapp_followup_message(o, "order_confirmation")
            self.assertIn("TULSA WEAR", msg_conf)
            self.assertIn("Meera Kapoor", msg_conf)
            self.assertIn("7–15 Business Days", msg_conf)

            # 2. Processing
            msg_proc = format_whatsapp_followup_message(o, "order_processing")
            self.assertIn("now being processed with care", msg_proc)

            # 3. Dispatched
            msg_disp = format_whatsapp_followup_message(o, "order_dispatched")
            self.assertIn("BlueDart Express", msg_disp)
            self.assertIn("TW-TRACK-555", msg_disp)

            # 4. Out for Delivery
            msg_out = format_whatsapp_followup_message(o, "out_for_delivery")
            self.assertIn("OUT FOR DELIVERY", msg_out)

            # 5. Delivered
            msg_del = format_whatsapp_followup_message(o, "order_delivered")
            self.assertIn("DELIVERED", msg_del)

            # 6. Post-Delivery Feedback
            msg_feed = format_whatsapp_followup_message(o, "post_delivery_feedback")
            self.assertIn("feedback", msg_feed.lower())

    # -----------------------------------------------------------
    # TEST 21: Secure Invoice Token Generation and Verification
    # -----------------------------------------------------------
    def test_secure_invoice_token(self):
        with site.app.app_context():
            o = make_test_order(customer_name="Invoice User")
            db.session.add(o)
            db.session.commit()
            order_id = o.id

            from services.notification_service import generate_secure_invoice_token, verify_invoice_token
            token = generate_secure_invoice_token(order_id)
            self.assertTrue(verify_invoice_token(order_id, token))
            self.assertFalse(verify_invoice_token(order_id, "invalid_tampered_token"))

            # Test invoice endpoint with valid token
            with self.client.session_transaction() as sess:
                sess.clear()
            resp = self.client.get(f"/invoice/{order_id}?token={token}")
            self.assertEqual(resp.status_code, 200)

            # Test invoice endpoint without token and without admin auth
            with self.client.session_transaction() as sess:
                sess.clear()
            bad_resp = self.client.get(f"/invoice/{order_id}?token=badtoken")
            self.assertEqual(bad_resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
