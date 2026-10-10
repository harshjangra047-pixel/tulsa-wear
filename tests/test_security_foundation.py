"""Local-only security and payment tests. Always override app storage with SQLite."""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

TEST_DB_DIR = Path(tempfile.gettempdir()) / "tulsa-handmade-tests"
TEST_DB_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DB_DIR / f"{uuid4().hex}.db")
os.environ["FLASK_SECRET_KEY"] = "unit-test-session-key"
os.environ["ADMIN_PASSWORD"] = "Unit-Test-Only-Password-7391"
os.environ["ADMIN_USERNAME"] = "unit-test-admin"
os.environ["FLASK_ENV"] = "testing"

import app as site
from models.customer_user import CustomerUser
from models.order import Order
from models.product import Product
from services.site_content import get_site_content, publish_site_content, save_site_content


class PaymentStub:
    def __init__(self, detail):
        self.detail = detail

    def fetch(self, payment_id):
        return self.detail


class RazorpayStub:
    def __init__(self, detail):
        self.payment = PaymentStub(detail)
        self.utility = self

    def verify_payment_signature(self, payload):
        return None


class SecurityFoundationTests(unittest.TestCase):
    def setUp(self):
        with site.app.app_context():
            site.db.session.remove()
            site.db.drop_all()
            site.db.create_all()
            site.razorpay_client = None
        self.client = site.app.test_client()

    def tearDown(self):
        with site.app.app_context():
            site.db.session.remove()

    def _csrf(self, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            token = session.get("csrf_token") or "csrf-test-token"
            session["csrf_token"] = token
        return token

    def _order(self, status="Payment Pending", customer_id=None, **values):
        order_values = dict(
            product_id=1, product_name="Test garment", price=1200.0,
            customer_name="Test buyer", phone="9876543210", email="buyer@example.invalid",
            address="Test address", city="Hansi", pincode="125033", status=status,
            customer_id=customer_id,
        )
        order_values.update(values)
        order = Order(**order_values)
        site.db.session.add(order)
        site.db.session.commit()
        return order

    def test_customer_login_requires_existing_password_and_registration_cannot_take_over_phone(self):
        with site.app.app_context():
            customer = CustomerUser(name="Test customer", phone="9876543210", email="test@example.invalid")
            customer.set_password("Correct-Local-Password-123")
            site.db.session.add(customer)
            site.db.session.commit()
        token = self._csrf()
        headers = {"X-CSRF-Token": token, "Content-Type": "application/json"}
        self.assertEqual(self.client.post("/customer/login", json={"phone": "9876543210"}, headers=headers).status_code, 400)
        self.assertEqual(self.client.post("/customer/login", json={"phone": "9876543210", "password": "wrong"}, headers=headers).status_code, 401)
        login = self.client.post("/customer/login", json={"phone": "9876543210", "password": "Correct-Local-Password-123"}, headers=headers)
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json["success"])
        self.assertEqual(login.json["csrf_token"], self._csrf())
        duplicate = self.client.post("/customer/register", json={
            "name": "Impostor", "phone": "9876543210", "password": "Different-Local-Password-123"
        }, headers={"X-CSRF-Token": login.json["csrf_token"], "Content-Type": "application/json"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.client.get("/customer/dashboard").status_code, 200)

    def test_dashboard_saves_only_owned_addresses_and_lists_customer_orders(self):
        with site.app.app_context():
            customer = CustomerUser(name="Dashboard customer", phone="9876543210", email="dash@example.invalid")
            customer.set_password("Correct-Local-Password-123")
            site.db.session.add(customer)
            site.db.session.commit()
            customer_id = customer.id
            own_order = self._order(customer_id=customer_id)
            own_order_id = own_order.id
            other = CustomerUser(name="Other customer", phone="9876543212", email="other@example.invalid")
            other.set_password("Another-Local-Password-123")
            site.db.session.add(other)
            site.db.session.commit()
            self._order(customer_id=other.id, product_name="Foreign confidential garment")
        csrf = self._csrf()
        self.client.post("/customer/login", json={"phone":"9876543210", "password":"Correct-Local-Password-123"},
                         headers={"X-CSRF-Token":csrf,"Content-Type":"application/json"})
        token = self._csrf()
        saved = self.client.post("/customer/dashboard", data={
            "csrf_token":token,"action":"address","label":"Home","recipient_name":"Dashboard customer",
            "phone":"9876543210","address":"12 Test Road","city":"Hansi","pincode":"125033",
        })
        self.assertEqual(saved.status_code, 302)
        with site.app.app_context():
            address = site.CustomerAddress.query.one()
            self.assertEqual(address.customer_id, customer_id)
            self.assertEqual(site.Order.query.filter_by(customer_id=customer_id).count(), 1)
        dashboard = self.client.get("/customer/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(f"Order #{own_order_id}".encode(), dashboard.data)
        self.assertNotIn(b"Foreign confidential garment", dashboard.data)

    def test_customer_cannot_open_another_customers_payment_or_confirmation_page(self):
        with site.app.app_context():
            owner = CustomerUser(name="Owner", phone="9876543211", email="owner@example.invalid")
            owner.set_password("Owner-Local-Password-123")
            site.db.session.add(owner)
            site.db.session.commit()
            order = self._order(customer_id=owner.id)
            order_id = order.id
        token = self._csrf()
        self.client.post("/customer/login", json={"phone": "9876543210", "password": "Correct-Local-Password-123"},
                         headers={"X-CSRF-Token": token, "Content-Type": "application/json"})
        self.assertEqual(self.client.get(f"/payment-step/{order_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/order-success/{order_id}").status_code, 404)

    def test_razorpay_payment_must_be_captured_for_exact_amount_and_currency(self):
        with site.app.app_context():
            order = self._order(razorpay_order_id="rzp_order_local")
            order_id = order.id
        with self.client.session_transaction() as session:
            session["authorized_order_ids"] = [order_id]
        site.razorpay_client = RazorpayStub({
            "method": "card", "order_id": "rzp_order_local", "amount": 120000,
            "currency": "INR", "status": "captured",
        })
        payload = {"razorpay_order_id": "rzp_order_local", "razorpay_payment_id": "pay_local_1", "razorpay_signature": "signed"}
        response = self.client.post(f"/payment/{order_id}", json=payload)
        self.assertEqual(response.status_code, 200)
        with site.app.app_context():
            paid = site.db.session.get(Order, order_id)
            self.assertEqual(paid.status, "Confirmed")
            self.assertEqual(paid.advance_paid, paid.price)
        self.assertTrue(self.client.post(f"/payment/{order_id}", json=payload).json["success"])

        with site.app.app_context():
            unpaid = self._order(razorpay_order_id="rzp_order_local_2")
            unpaid_id = unpaid.id
        with self.client.session_transaction() as session:
            session["authorized_order_ids"] = [unpaid_id]
        site.razorpay_client = RazorpayStub({
            "method": "card", "order_id": "rzp_order_local_2", "amount": 100,
            "currency": "INR", "status": "authorized",
        })
        invalid = self.client.post(f"/payment/{unpaid_id}", json={
            "razorpay_order_id": "rzp_order_local_2", "razorpay_payment_id": "pay_local_2", "razorpay_signature": "signed"
        })
        self.assertEqual(invalid.status_code, 400)
        with site.app.app_context():
            self.assertEqual(site.db.session.get(Order, unpaid_id).advance_paid, 0.0)

    def test_manual_upi_claim_stays_unpaid_and_cod_is_separate(self):
        with site.app.app_context():
            upi_order = self._order()
            cod_order = self._order()
            upi_id, cod_id = upi_order.id, cod_order.id
        with self.client.session_transaction() as session:
            session["authorized_order_ids"] = [upi_id, cod_id]
            csrf = session.setdefault("csrf_token", "csrf-test-token")
        image = io.BytesIO()
        from PIL import Image
        Image.new("RGB", (2, 2), color="white").save(image, format="PNG")
        image.seek(0)
        with patch.object(site, "upload_payment_proof", return_value=f"payment-proofs/{upi_id}/proof.png") as upload:
            upi_response = self.client.post(f"/submit-payment-proof/{upi_id}", data={
                "csrf_token": csrf, "payment_method": "UPI (GPay / PhonePe / QR)", "upi_utr": "ABCD12345678",
                "payment_screenshot": (image, "proof.png"),
            }, content_type="multipart/form-data")
        upload.assert_called_once()
        self.assertEqual(upi_response.status_code, 302)
        cod_response = self.client.post(f"/submit-payment-proof/{cod_id}", data={
            "csrf_token": csrf, "payment_method": "Cash on Delivery",
        })
        self.assertEqual(cod_response.status_code, 302)
        with site.app.app_context():
            upi = site.db.session.get(Order, upi_id)
            cod = site.db.session.get(Order, cod_id)
            self.assertEqual(upi.status, "Payment Verification Required")
            self.assertEqual(upi.advance_paid, 0.0)
            self.assertEqual(upi.balance_due, upi.price)
            self.assertEqual(cod.status, "COD Pending")
            self.assertEqual(cod.advance_paid, 0.0)
            self.assertEqual(cod.balance_due, cod.price)

    def test_blob_helpers_use_public_catalog_and_private_proof_access_modes(self):
        from services import media_storage
        with patch.dict(os.environ, {"PUBLIC_BLOB_READ_WRITE_TOKEN":"public-test-token", "PRIVATE_BLOB_READ_WRITE_TOKEN":"private-test-token"}, clear=False):
            with patch("services.media_storage.BlobClient") as client_type:
                client = client_type.return_value
                client.put.return_value = SimpleNamespace(url="https://store.public.blob.vercel-storage.com/products/abc.webp", pathname="products/abc.webp")
                public_url = media_storage.put_public_image("products", b"small-webp")
                self.assertIn(".public.blob.vercel-storage.com/", public_url)
                self.assertEqual(client.put.call_args.kwargs["access"], "public")
                client.put.return_value = SimpleNamespace(url="https://store.private.blob.vercel-storage.com/payment-proofs/1/abc.png", pathname="payment-proofs/1/abc.png")
                proof_path = media_storage.put_private_proof("payment-proofs/1/abc.png", b"proof", "image/png")
                self.assertEqual(proof_path, "payment-proofs/1/abc.png")
                self.assertEqual(client.put.call_args.kwargs["access"], "private")
                client.get.return_value = SimpleNamespace(status_code=200, content=b"proof", content_type="image/png")
                self.assertEqual(media_storage.get_private_object(proof_path), (b"proof", "image/png"))
                self.assertEqual(client.get.call_args.kwargs["access"], "private")

    def test_content_is_saved_as_draft_then_published_with_revision_history(self):
        draft = {"brand_name": "TULSA — BY ANJALI", "hero_title_line1": "Draft headline"}
        with site.app.app_context():
            self.assertTrue(save_site_content(draft, publish=False))
            self.assertNotEqual(get_site_content().get("hero_title_line1"), "Draft headline")
            self.assertEqual(get_site_content(preview_draft=True).get("hero_title_line1"), "Draft headline")
            self.assertTrue(publish_site_content())
            self.assertEqual(get_site_content().get("hero_title_line1"), "Draft headline")
            self.assertGreater(site.SiteContentRevision.query.count(), 1)

    def test_admin_process_writes_content_read_by_storefront(self):
        admin_root = Path("/Users/harsh/Documents/tulsa.wear.admin")
        writer = r"""
import os, sys
sys.path.insert(0, os.getcwd())
import app as admin_app
from models import Product, db
from services.site_content import save_site_content
with admin_app.app.app_context():
    assert save_site_content({'brand_name': 'TULSA — BY ANJALI', 'hero_title_line1': 'Shared from admin'}, publish=False)
    db.session.add(Product(name='Shared test product', price=1234.0, category='Test', stock=4))
    db.session.commit()
"""
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(filter(None, ["/tmp/tulsa-wears-test-deps", env.get("PYTHONPATH", "")]))
        result = subprocess.run([sys.executable, "-c", writer], cwd=admin_root, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        self.assertEqual(result.returncode, 0, "admin content writer should complete against the shared test database")
        with site.app.app_context():
            self.assertEqual(get_site_content(preview_draft=True).get("hero_title_line1"), "Shared from admin")
            self.assertEqual(Product.query.filter_by(name="Shared test product").one().price, 1234.0)

    def test_admin_status_change_cannot_mark_an_unpaid_order_confirmed(self):
        with site.app.app_context():
            order = self._order(status="Payment Verification Required", upi_utr="ABCD12345678")
            order_id = order.id
        with self.client.session_transaction() as session:
            session["admin_authenticated"] = True
        response = self.client.post(f"/admin/orders/update-status/{order_id}", data={"status":"Confirmed"})
        self.assertEqual(response.status_code, 302)
        with site.app.app_context():
            order = site.db.session.get(Order, order_id)
            self.assertEqual(order.status, "Payment Verification Required")
            self.assertEqual(order.advance_paid, 0.0)


if __name__ == "__main__":
    unittest.main()
