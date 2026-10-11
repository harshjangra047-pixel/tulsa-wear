"""Comprehensive Unit Tests for Tulsa Wears Commerce Upgrades.

Covers:
1. Integer paise arithmetic (to_paise, to_rupees)
2. Subtotal calculation before coupon discounts
3. Coupon eligibility, percent/flat discount calculation, caps, and min_order thresholds
4. Package dimension & volumetric weight calculation
5. Shipping logistics zone classification and rate quotation
6. Checkout calculator end-to-end integration
7. Live checkout shipping quote API (/api/shipping/quote)
8. Live checkout coupon apply API (/api/coupon/apply)
"""
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

TEST_DB_DIR = Path(tempfile.gettempdir()) / "tulsa-commerce-tests"
TEST_DB_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DB_DIR / f"{uuid4().hex}.db")
os.environ["FLASK_SECRET_KEY"] = "unit-test-session-key"
os.environ["ADMIN_PASSWORD"] = "Unit-Test-Password-8822"
os.environ["ADMIN_USERNAME"] = "unit-test-admin"
os.environ["FLASK_ENV"] = "testing"

import app as site
from models.order import Order
from models.product import Product
from models.coupon import Coupon
from models.admin_user import AdminUser
from services.checkout_calculator import (
    to_paise,
    to_rupees,
    calculate_bag_and_checkout,
    calculate_coupon_discount,
)
from services.shipping_service import (
    calculate_volumetric_weight,
    calculate_volumetric_weight_kg,
    get_order_package_specs,
    get_indian_postal_zone,
    get_shipping_quote,
)


class CommerceUpgradesTests(unittest.TestCase):
    def setUp(self):
        with site.app.app_context():
            site.db.session.remove()
            site.db.drop_all()
            site.db.create_all()

            # Ensure admin exists
            admin = AdminUser.query.first()
            if not admin:
                admin = AdminUser(username="unit-test-admin")
                admin.set_password("Unit-Test-Password-8822")
                admin.warehouse_pincode = "125033"
                admin.warehouse_city = "Hansi"
                admin.warehouse_state = "Haryana"
                admin.shipping_fallback_enabled = True
                admin.shipping_flat_fallback = 120.0
                site.db.session.add(admin)

            # Create test coupon
            c1 = Coupon(
                code="TULSA10",
                discount_type="percentage",
                discount_value=10.0,
                min_order_amount=2000.0,
                max_discount=1000.0,
                is_active=True
            )
            site.db.session.add(c1)

            # Create test products
            self.p1 = Product(
                name="Gulzar Chanderi Kurta",
                category="Kurta",
                price=4800.0,
                stock=10,
                weight_kg=0.6,
                length_cm=35.0,
                width_cm=28.0,
                height_cm=4.0,
            )
            self.p2 = Product(
                name="Sitara Organza Dupatta",
                category="Dupatta",
                price=3200.0,
                stock=8,
                weight_kg=0.3,
                length_cm=25.0,
                width_cm=20.0,
                height_cm=3.0,
            )
            site.db.session.add_all([self.p1, self.p2])
            site.db.session.commit()
            self.p1_id = self.p1.id
            self.p2_id = self.p2.id

        self.client = site.app.test_client()

    def tearDown(self):
        with site.app.app_context():
            site.db.session.remove()

    def _csrf(self, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            token = session.get("_csrf_token")
            if not token:
                token = "test-csrf-token"
                session["_csrf_token"] = token
            return token

    # ---------------------------------------------------------
    # 1. PAISE ARITHMETIC UNIT TESTS
    # ---------------------------------------------------------
    def test_paise_arithmetic_precision(self):
        """Verify float conversion to paise avoids floating point drift."""
        self.assertEqual(to_paise(199.99), 19999)
        self.assertEqual(to_paise(0.1 + 0.2), 30)  # Standard float 0.30000000000000004
        self.assertEqual(to_rupees(19999), 199.99)
        self.assertEqual(to_rupees(0), 0.0)
        self.assertEqual(to_paise(None), 0)
        self.assertEqual(to_rupees(None), 0.0)

    # ---------------------------------------------------------
    # 2. COUPON CALCULATION UNIT TESTS
    # ---------------------------------------------------------
    def test_coupon_percentage_calculation(self):
        """10% coupon on 4800 subtotal should give 480 discount."""
        res = calculate_coupon_discount(
            subtotal_paise=480000,
            coupon={"code": "TULSA10", "type": "percentage", "value": 10, "min_order": 2000, "max_discount": 1000}
        )
        self.assertTrue(res["valid"])
        self.assertEqual(res["discount_paise"], 48000)
        self.assertEqual(res["discount_rupees"], 480.0)

    def test_coupon_percentage_capped_by_max_discount(self):
        """10% coupon on 15,000 subtotal with max_discount 1000 should give 1000, not 1500."""
        res = calculate_coupon_discount(
            subtotal_paise=1500000,
            coupon={"code": "TULSA10", "type": "percentage", "value": 10, "min_order": 2000, "max_discount": 1000}
        )
        self.assertTrue(res["valid"])
        self.assertEqual(res["discount_paise"], 100000)
        self.assertEqual(res["discount_rupees"], 1000.0)

    def test_coupon_min_order_threshold_rejection(self):
        """Coupon requiring min_order 5000 should be rejected on 4800 subtotal."""
        res = calculate_coupon_discount(
            subtotal_paise=480000,
            coupon={"code": "LUXURY500", "type": "flat", "value": 500, "min_order": 5000}
        )
        self.assertFalse(res["valid"])
        self.assertEqual(res["discount_paise"], 0)
        self.assertIn("minimum order", res["message"].lower())

    def test_coupon_flat_discount_capped_to_subtotal(self):
        """Flat coupon of 2000 on a 1500 order cannot exceed subtotal."""
        res = calculate_coupon_discount(
            subtotal_paise=150000,
            coupon={"code": "FLAT2000", "type": "flat", "value": 2000, "min_order": 1000}
        )
        self.assertTrue(res["valid"])
        self.assertEqual(res["discount_paise"], 150000)
        self.assertEqual(res["discount_rupees"], 1500.0)

    # ---------------------------------------------------------
    # 3. WEIGHT & DIMENSION SPECIFICATIONS
    # ---------------------------------------------------------
    def test_volumetric_weight_calculation(self):
        """Standard courier formula (L x W x H) / 5000."""
        # 50cm x 40cm x 25cm = 50,000 / 5000 = 10.0 kg
        vol_wt = calculate_volumetric_weight(50.0, 40.0, 25.0)
        self.assertAlmostEqual(vol_wt, 10.0, places=2)
        vol_wt_alias = calculate_volumetric_weight_kg(50.0, 40.0, 25.0)
        self.assertAlmostEqual(vol_wt_alias, 10.0, places=2)

    def test_multi_item_order_package_specs(self):
        """Multiple items accumulate physical weight and stacked height."""
        with site.app.app_context():
            p1 = Product.query.get(self.p1_id)
            p2 = Product.query.get(self.p2_id)
            items = [
                {"product": p1, "quantity": 2}, # 2 x 0.6kg = 1.2kg
                {"product": p2, "quantity": 1}, # 1 x 0.3kg = 0.3kg
            ]
            specs = get_order_package_specs(items)
            self.assertAlmostEqual(specs["physical_weight_kg"], 1.5, places=2)
            self.assertEqual(specs["length_cm"], 35.0)
            self.assertEqual(specs["width_cm"], 28.0)
            self.assertEqual(specs["height_cm"], 11.0)
            self.assertGreaterEqual(specs["billable_weight_kg"], 1.5)

    # ---------------------------------------------------------
    # 4. SHIPPING ZONE & LOGISTICS QUOTES
    # ---------------------------------------------------------
    def test_postal_zone_classification(self):
        """Check Indian PIN code zone mapping from Hansi, Haryana (125033)."""
        # Haryana (125xxx) -> Zone A (Local)
        self.assertEqual(get_indian_postal_zone("125033"), "Zone A (Local / Haryana)")
        self.assertEqual(get_indian_postal_zone("125001"), "Zone A (Local / Haryana)")

        # Delhi / North (110xxx) -> Zone B (Regional North)
        self.assertEqual(get_indian_postal_zone("110001"), "Zone B (Regional North)")

        # Mumbai / West Metro (400xxx) -> Zone C (Metro)
        self.assertEqual(get_indian_postal_zone("400001"), "Zone C (Metro)")

        # Bangalore / South (560xxx) -> Zone D (Rest of India)
        self.assertEqual(get_indian_postal_zone("560001"), "Zone D (Rest of India)")

        # Srinagar J&K (190xxx) -> Zone E (Special / Remote)
        self.assertEqual(get_indian_postal_zone("190001"), "Zone E (Special / Remote)")

    def test_invalid_pincode_returns_error(self):
        """Invalid PIN codes (non-numeric, wrong length, invalid start digit) fail cleanly."""
        quote_short = get_shipping_quote(dest_pincode="123")
        self.assertFalse(quote_short["success"])
        self.assertIn("6-digit", quote_short["message"])

        quote_alpha = get_shipping_quote(dest_pincode="ABCDEF")
        self.assertFalse(quote_alpha["success"])

        quote_zero = get_shipping_quote(dest_pincode="012345")
        self.assertFalse(quote_zero["success"])

    def test_shipping_quote_calculation(self):
        """Shipping quote for Delhi (110001) should quote Zone B rates."""
        quote = get_shipping_quote(dest_pincode="110001", physical_weight_kg=0.8)
        self.assertTrue(quote["success"])
        self.assertGreater(quote["rate_rupees"], 0)
        self.assertIn("Regional North", quote.get("zone", "") + quote.get("courier", ""))
        self.assertIn("estimated_days", quote)

    # ---------------------------------------------------------
    # 5. INTEGRATED CHECKOUT ARITHMETIC
    # ---------------------------------------------------------
    def test_checkout_calculator_subtotal_before_coupon(self):
        """Subtotal must be strictly sum(price * qty) before coupon and shipping."""
        with site.app.app_context():
            p1 = Product.query.get(self.p1_id) # Price 4800
            p2 = Product.query.get(self.p2_id) # Price 3200

            items = [
                {"product": p1, "quantity": 1},
                {"product": p2, "quantity": 2}, # 2 x 3200 = 6400
            ]
            # Total subtotal should be 4800 + 6400 = 11200
            summary = calculate_bag_and_checkout(
                items=items,
                dest_pincode="110001",
                coupon_code="TULSA10",
                payment_method="UPI_FULL"
            )

            self.assertEqual(summary["subtotal"], 11200.0)
            # 10% coupon capped at 1000
            self.assertEqual(summary["discount_amount"], 1000.0)
            self.assertEqual(summary["discounted_subtotal"], 10200.0)
            # Final total must equal discounted_subtotal + shipping_fee
            expected_total = summary["discounted_subtotal"] + summary["shipping_fee"]
            self.assertEqual(summary["final_total"], expected_total)
            # Since UPI_FULL, advance_paid must equal final_total
            self.assertEqual(summary["advance_paid"], summary["final_total"])
            self.assertEqual(summary["balance_due"], 0.0)

    def test_partial_advance_calculation(self):
        """When 25% Advance payment is chosen, calculate exact deposit and COD balance."""
        with site.app.app_context():
            p1 = Product.query.get(self.p1_id)
            items = [{"product": p1, "quantity": 1}]

            summary = calculate_bag_and_checkout(
                items=items,
                dest_pincode="125033",
                payment_method="ADVANCE_25"
            )

            final_total = summary["final_total"]
            advance_paid = summary["advance_paid"]
            balance_due = summary["balance_due"]

            self.assertEqual(to_paise(advance_paid) + to_paise(balance_due), to_paise(final_total))
            self.assertAlmostEqual(advance_paid, round(final_total * 0.25, 2), delta=1.0)

    # ---------------------------------------------------------
    # 6. LIVE AJAX API ENDPOINTS
    # ---------------------------------------------------------
    def test_api_shipping_quote_valid_pincode(self):
        """API endpoint /api/shipping/quote returns rate JSON."""
        res = self.client.post("/api/shipping/quote", json={"pincode": "110001"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertGreater(data.get("rate_rupees", 0), 0)
        self.assertIn("courier", data)

    def test_api_shipping_quote_invalid_pincode(self):
        """API endpoint /api/shipping/quote returns 400 on invalid pin code."""
        res = self.client.post("/api/shipping/quote", json={"pincode": "999"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("success"))

    def test_api_coupon_apply_endpoint(self):
        """API endpoint /api/coupon/apply returns calculated discount."""
        with site.app.app_context():
            res = self.client.post(
                "/api/coupon/apply",
                json={
                    "code": "TULSA10",
                    "product_id": self.p1_id,
                    "quantity": 1,
                    "pincode": "110001",
                }
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("discount_amount"), 480.0) # 10% of 4800
            self.assertEqual(data.get("subtotal"), 4800.0)
            self.assertEqual(data.get("final_total"), 4800.0 - 480.0)

    def test_upi_qr_code_endpoints(self):
        """API endpoints /api/order/<id>/upi-qr.png and /api/order/<id>/payment-qr-details work correctly."""
        with site.app.app_context():
            order = Order(
                customer_name="Sita Sharma",
                phone="9876543210",
                email="sita@example.com",
                address="12 Janpath",
                city="New Delhi",
                pincode="110001",
                product_id=self.p1_id,
                product_name="Royal Chanderi Silk Kurta",
                price=4920.0,
                shipping_fee=120.0,
                status="Pending"
            )
            site.db.session.add(order)
            site.db.session.commit()
            order_id = order.id

        with self.client.session_transaction() as sess:
            sess["authorized_order_ids"] = [order_id]

        # 1. Test PNG QR code generation
        res_png = self.client.get(f"/api/order/{order_id}/upi-qr.png")
        self.assertEqual(res_png.status_code, 200)
        self.assertEqual(res_png.mimetype, "image/png")
        self.assertTrue(res_png.data.startswith(b"\x89PNG\r\n\x1a\n"), "Must be a valid PNG image binary")

        # 2. Test JSON details endpoint
        res_json = self.client.get(f"/api/order/{order_id}/payment-qr-details")
        self.assertEqual(res_json.status_code, 200)
        data = res_json.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("upi://pay?", data.get("upi_uri"))
        self.assertEqual(data.get("amount"), 4920.0)
        self.assertEqual(data.get("order_id"), order_id)

    def test_product_parcel_attributes(self):
        """Product parcel specifications (weight, dimensions) persist accurately."""
        with site.app.app_context():
            prod = Product(
                name="Heirloom Organza Dupatta",
                price=2400.0,
                category="Accessories",
                weight_kg=0.35,
                length_cm=25.0,
                width_cm=20.0,
                height_cm=4.0
            )
            site.db.session.add(prod)
            site.db.session.commit()
            prod_id = prod.id

            fetched = site.db.session.get(Product, prod_id)
            self.assertEqual(fetched.weight_kg, 0.35)
            self.assertEqual(fetched.length_cm, 25.0)
            self.assertEqual(fetched.width_cm, 20.0)
            self.assertEqual(fetched.height_cm, 4.0)


if __name__ == "__main__":
    unittest.main()
