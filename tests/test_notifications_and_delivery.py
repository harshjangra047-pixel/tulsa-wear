"""Unit & Integration tests for Tulsa Wears Automated WhatsApp Confirmations,
Professional Email Receipts, and 7-15 Day Delivery Timeline System.
"""
import os
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

TEST_DB_DIR = Path(tempfile.gettempdir()) / "tulsa-notif-tests"
TEST_DB_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DB_DIR / f"{uuid4().hex}.db")
os.environ["FLASK_SECRET_KEY"] = "notif-test-session-secret"
os.environ["ADMIN_PASSWORD"] = "Admin-Test-Pass-7744"
os.environ["ADMIN_USERNAME"] = "test-notif-admin"
os.environ["FLASK_ENV"] = "testing"

import app as site
from models.database import db
from models.product import Product
from models.order import Order
from models.order_notification import OrderNotification
from models.admin_user import AdminUser
from services.notification_service import (
    calculate_delivery_window,
    trigger_order_notifications,
    send_whatsapp_order_confirmation,
    send_email_order_confirmation,
    DEFAULT_DELIVERY_MIN_DAYS,
    DEFAULT_DELIVERY_MAX_DAYS,
)


class NotificationAndDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site.app.config["TESTING"] = True
        site.app.config["WTF_CSRF_ENABLED"] = False

    def setUp(self):
        self.client = site.app.test_client()

        with site.app.app_context():
            site.ensure_schema_migrations()
            db.create_all()

            # Clean test data
            OrderNotification.query.delete()
            Order.query.delete()
            Product.query.delete()
            AdminUser.query.delete()
            db.session.commit()

            # Create test admin
            admin = AdminUser(username="test-notif-admin")
            admin.set_password("Admin-Test-Pass-7744")
            db.session.add(admin)

            # Create test products
            p1 = Product(
                name="Gulzar Chanderi Silk Anarkali Set",
                category="Palazzo Set",
                price=8500.0,
                stock=15,
            )
            p2 = Product(
                name="Noor Velvet Embroidered Kurti",
                category="Casual Wear",
                price=4200.0,
                stock=20,
            )
            db.session.add_all([p1, p2])
            db.session.commit()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
            sess["admin_user"] = "test-notif-admin"

    def test_01_calculate_delivery_window_7_to_15_days(self):
        """Verify delivery window calculates exactly 7 to 15 days in Asia/Kolkata format."""
        base = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
        win = calculate_delivery_window(base)
        self.assertIsInstance(win, dict)
        self.assertEqual(win["min_days"], 7)
        self.assertEqual(win["max_days"], 15)
        self.assertIn("2026", win["start_str"])
        self.assertIn("2026", win["end_str"])
        self.assertIn("–", win["display_window"])

    def test_02_order_creation_captures_delivery_window_and_items(self):
        """Creating an order should automatically compute 7-15 day delivery window and items snapshot."""
        with site.app.app_context():
            p = Product.query.first()
            win = calculate_delivery_window()
            order = Order(
                product_id=p.id,
                customer_name="Pooja Sharma",
                phone="9876543210",
                email="pooja.sharma@example.com",
                address="Flat 402, Lotus Towers, Bandra West",
                city="Mumbai",
                pincode="400050",
                product_name=p.name,
                size="M",
                price=8500.0,
                payment_method="Cash on Delivery",
                status="Pending",
                whatsapp_opt_in=True,
                whatsapp_opt_in_source="checkout_checkbox",
                delivery_window_start=win["start_str"],
                delivery_window_end=win["end_str"],
                order_items_data=json.dumps([{
                    "product_id": p.id,
                    "name": p.name,
                    "price": 8500.0,
                    "quantity": 1,
                    "size": "M"
                }]),
            )
            db.session.add(order)
            db.session.commit()

            saved_order = Order.query.get(order.id)
            self.assertEqual(saved_order.whatsapp_opt_in, True)
            self.assertEqual(saved_order.whatsapp_opt_in_source, "checkout_checkbox")
            self.assertEqual(saved_order.delivery_window_start, win["start_str"])
            self.assertEqual(saved_order.delivery_window_end, win["end_str"])

            items = saved_order.get_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], p.name)
            self.assertEqual(items[0]["size"], "M")

    def test_03_notification_trigger_and_idempotency(self):
        """Triggering order notifications creates outbox record and prevents duplicate sends."""
        with site.app.app_context():
            p = Product.query.first()
            order = Order(
                product_id=p.id,
                customer_name="Ananya Verma",
                phone="+919811223344",
                email="ananya.verma@example.com",
                address="12 Park Street",
                city="Kolkata",
                pincode="700016",
                product_name=p.name,
                size="L",
                price=4200.0,
                payment_method="Online - Razorpay",
                status="Confirmed",
                whatsapp_opt_in=True,
            )
            db.session.add(order)
            db.session.commit()

            # First trigger
            res1 = trigger_order_notifications(order.id, event_type="order_confirmation", trigger_source="test_run")
            self.assertIn("whatsapp", res1)
            self.assertIn("email", res1)

            # Notifications recorded in outbox
            notifications = OrderNotification.query.filter_by(order_id=order.id).all()
            self.assertGreaterEqual(len(notifications), 1)

            initial_count = len(notifications)

            # Second trigger with force_resend=False should be idempotent
            res2 = trigger_order_notifications(order.id, event_type="order_confirmation", force_resend=False)
            new_count = OrderNotification.query.filter_by(order_id=order.id).count()
            self.assertEqual(initial_count, new_count)

    def test_04_whatsapp_opt_in_versus_opt_out(self):
        """WhatsApp message should NOT be sent if customer did not opt in."""
        with site.app.app_context():
            p = Product.query.first()
            order_no_opt = Order(
                product_id=p.id,
                customer_name="Ritu Mehra",
                phone="9988776655",
                email="ritu.mehra@example.com",
                address="55 Civil Lines",
                city="Jaipur",
                pincode="302006",
                product_name=p.name,
                size="S",
                price=4200.0,
                payment_method="Cash on Delivery",
                status="Pending",
                whatsapp_opt_in=False,
            )
            db.session.add(order_no_opt)
            db.session.commit()

            res = send_whatsapp_order_confirmation(order_no_opt, event_type="order_confirmation", force_resend=False)
            self.assertFalse(res.get("success"))
            self.assertIn("opt in", res.get("message", "").lower())
            self.assertEqual(order_no_opt.whatsapp_notification_status, "Not opted in")

    def test_05_whatsapp_customer_opt_out_endpoint(self):
        """Customer can opt out of WhatsApp notifications via /whatsapp-opt-out."""
        with site.app.app_context():
            p = Product.query.first()
            order = Order(
                product_id=p.id,
                customer_name="Meera Sen",
                phone="9876543219",
                email="meera.sen@example.com",
                address="7 Lake Gardens",
                city="Kolkata",
                pincode="700045",
                product_name=p.name,
                price=8500.0,
                payment_method="Cash on Delivery",
                status="Pending",
                whatsapp_opt_in=True,
            )
            db.session.add(order)
            db.session.commit()
            order_id = order.id

        # GET request renders opt out form
        get_res = self.client.get(f"/whatsapp-opt-out?order_id={order_id}&phone=9876543219")
        self.assertEqual(get_res.status_code, 200)
        self.assertIn(b"WhatsApp Notification Preferences", get_res.data)

        # POST request executes opt out
        post_res = self.client.post("/whatsapp-opt-out", data={
            "order_id": str(order_id),
            "phone": "9876543219"
        })
        self.assertEqual(post_res.status_code, 200)
        self.assertIn(b"opted out", post_res.data.lower())

        with site.app.app_context():
            updated = Order.query.get(order_id)
            self.assertFalse(updated.whatsapp_opt_in)
            self.assertEqual(updated.whatsapp_notification_status, "Opted out")

    def test_06_admin_notification_audit_api(self):
        """Admin can retrieve JSON notification audit history for an order."""
        self._login_admin()

        with site.app.app_context():
            p = Product.query.first()
            order = Order(
                product_id=p.id,
                customer_name="Kavita Rao",
                phone="9876543211",
                email="kavita.rao@example.com",
                address="14 Jubilee Hills",
                city="Hyderabad",
                pincode="500033",
                product_name=p.name,
                price=8500.0,
                payment_method="Cash on Delivery",
                status="Pending",
                whatsapp_opt_in=True,
            )
            db.session.add(order)
            db.session.commit()

            # Record a mock notification
            notif = OrderNotification(
                order_id=order.id,
                channel="email",
                event_type="order_confirmation",
                recipient=order.email,
                status="Sent",
                provider_message_id="msg_test_888",
                idempotency_key=f"order_{order.id}_email_order_confirmation_v1",
            )
            db.session.add(notif)
            db.session.commit()
            order_id = order.id

        res = self.client.get(f"/admin/orders/{order_id}/notifications")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(len(data.get("notifications")), 1)
        self.assertEqual(data["notifications"][0]["channel"], "email")
        self.assertEqual(data["notifications"][0]["status"], "Sent")

    def test_07_admin_resend_notification_route(self):
        """Admin can trigger manual resend for WhatsApp and Email."""
        self._login_admin()

        with site.app.app_context():
            p = Product.query.first()
            order = Order(
                product_id=p.id,
                customer_name="Simran Kaur",
                phone="9876543212",
                email="simran.kaur@example.com",
                address="8 Sector 17",
                city="Chandigarh",
                pincode="160017",
                product_name=p.name,
                price=8500.0,
                payment_method="Cash on Delivery",
                status="Pending",
                whatsapp_opt_in=True,
            )
            db.session.add(order)
            db.session.commit()
            order_id = order.id

        # Resend Email
        res = self.client.post(f"/admin/orders/{order_id}/resend-notification/email", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with site.app.app_context():
            notifs = OrderNotification.query.filter_by(order_id=order_id, channel="email").all()
            self.assertGreaterEqual(len(notifs), 1)


if __name__ == "__main__":
    unittest.main()
