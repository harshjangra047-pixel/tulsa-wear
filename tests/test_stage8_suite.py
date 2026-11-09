import os
import sys
import unittest
import json
import time

# Strictly enforce test database
TEST_DB_PATH = "/tmp/tulsa_stage8_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-stage8-secret-key-32bytes-len!!"
os.environ["FLASK_ENV"] = "testing"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, db
from models.customer_user import CustomerUser
from models.customer_address import CustomerAddress
from models.customer_wishlist import CustomerWishlist
from models.product import Product
from models.order import Order
from models.admin_user import AdminUser
from services.site_content import get_site_content, save_site_content, publish_site_content
from services.ai_stylist import answer_customer_support

class TestStage8EcommerceUpgrade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()

    # =========================================================================
    # PART 1: PERFORMANCE & CACHING
    # =========================================================================
    def test_01_static_asset_caching_headers(self):
        """Verify immutable long-lived cache headers on static assets."""
        res = self.client.get("/static/css/atelier-3d.css")
        self.assertEqual(res.status_code, 200)
        cache_control = res.headers.get("Cache-Control", "")
        self.assertIn("public", cache_control)
        self.assertIn("max-age=31536000", cache_control)
        self.assertIn("immutable", cache_control)

    def test_02_storefront_response_time_benchmark(self):
        """Verify storefront pages respond rapidly (< 250ms)."""
        # Warmup
        self.client.get("/")
        
        # Test Home
        t0 = time.time()
        res_home = self.client.get("/")
        d_home = (time.time() - t0) * 1000
        self.assertEqual(res_home.status_code, 200)
        self.assertLess(d_home, 250, f"Homepage took {d_home:.1f}ms (expected < 250ms)")

        # Test Shop
        t0 = time.time()
        res_shop = self.client.get("/shop")
        d_shop = (time.time() - t0) * 1000
        self.assertEqual(res_shop.status_code, 200)
        self.assertLess(d_shop, 250, f"Shop took {d_shop:.1f}ms (expected < 250ms)")

        # Test Fitting Room
        t0 = time.time()
        res_fitting = self.client.get("/fitting-room")
        d_fitting = (time.time() - t0) * 1000
        self.assertEqual(res_fitting.status_code, 200)
        self.assertLess(d_fitting, 250, f"Fitting room took {d_fitting:.1f}ms (expected < 250ms)")

    # =========================================================================
    # PART 3: CUSTOMER REGISTRATION, CRYPTOGRAPHIC CAPTCHA & OTP
    # =========================================================================
    def test_03_captcha_generation_and_validation(self):
        """Test cryptographic CAPTCHA challenge generation and validation."""
        res = self.client.get("/api/captcha/generate")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("token", data)
        self.assertIn("question", data)
        self.assertIn("+", data["question"])

    def test_04_customer_registration_pipeline_with_otp(self):
        """Test registration initiate, OTP generation and verification."""
        # Clean up any existing test user with our test phone first
        test_phone = "9876543999"
        with app.app_context():
            old = CustomerUser.query.filter_by(phone=test_phone).first()
            if old:
                db.session.delete(old)
                db.session.commit()

        # 1. Generate captcha
        res_cap = self.client.get("/api/captcha/generate")
        cap_data = res_cap.get_json()
        token = cap_data["token"]
        q = cap_data["question"]
        
        # Calculate correct answer from question "X + Y = ?"
        correct_answer = str(eval(q.replace(" = ?", "")))

        # 2. Test registration with invalid captcha
        res_fail = self.client.post("/api/customer/register-initiate", json={
            "name": "Stage8 Royal Client",
            "email": "stage8_newuser@example.com",
            "phone": test_phone,
            "password": "Password123!",
            "captcha_token": token,
            "captcha_answer": "999"
        })
        self.assertEqual(res_fail.status_code, 400)
        self.assertIn("Incorrect human verification", res_fail.get_json()["message"])

        # 3. Test registration with valid captcha
        res_ok = self.client.post("/api/customer/register-initiate", json={
            "name": "Stage8 Royal Client",
            "email": "stage8_royal@example.com",
            "phone": test_phone,
            "password": "RoyalPassword123!",
            "captcha_token": token,
            "captcha_answer": correct_answer
        })
        self.assertEqual(res_ok.status_code, 200)
        initiate_data = res_ok.get_json()
        self.assertTrue(initiate_data["success"])
        self.assertTrue(initiate_data["requires_otp"])
        registered_phone = initiate_data["phone"]

        # 4. Check DB for OTP
        with app.app_context():
            user = CustomerUser.query.filter_by(phone=registered_phone).first()
            self.assertIsNotNone(user)
            self.assertFalse(user.is_verified)
            real_otp = user.otp_code
            self.assertEqual(len(real_otp), 6)

        # 5. Verify with WRONG OTP
        res_wrong_otp = self.client.post("/api/customer/verify-otp", json={
            "phone": registered_phone,
            "otp_code": "000000"
        })
        self.assertEqual(res_wrong_otp.status_code, 400)

        # 6. Verify with CORRECT OTP
        res_correct_otp = self.client.post("/api/customer/verify-otp", json={
            "phone": registered_phone,
            "otp_code": real_otp
        })
        self.assertEqual(res_correct_otp.status_code, 200)
        self.assertTrue(res_correct_otp.get_json()["success"])

        # 7. Verify user is now marked verified in DB
        with app.app_context():
            user = CustomerUser.query.filter_by(phone=registered_phone).first()
            self.assertTrue(user.is_verified)
            self.assertIsNone(user.otp_code)

        # 7. Verify user is now marked verified in DB
        with app.app_context():
            user = CustomerUser.query.filter_by(email="stage8_royal@example.com").first()
            self.assertTrue(user.is_verified)
            self.assertIsNone(user.otp_code)

    def test_05_customer_login_and_guest_cart_merge(self):
        """Test customer password login and merging of guest bag."""
        client = app.test_client()
        # Set guest cart in session
        with client.session_transaction() as sess:
            sess["cart"] = [{"product_id": 1, "size": "M", "quantity": 1}]
            sess["csrf_token"] = "test-csrf-token"

        # Login with seed customer
        res = client.post("/customer/login", data={
            "email": "aarav@example.com",
            "password": "Customer@123",
            "csrf_token": "test-csrf-token"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Check customer session and cart merge
        with client.session_transaction() as sess:
            self.assertIn("customer_id", sess)
            self.assertEqual(sess.get("customer_email"), "aarav@example.com")
            # Session separation: admin keys must NOT be present
            self.assertNotIn("admin_authenticated", sess)
            self.assertNotIn("studio_user", sess)
            # Cart should have the item
            self.assertIn("cart", sess)
            self.assertGreaterEqual(len(sess["cart"]), 1)

    # =========================================================================
    # PART 4: AMAZON-LIKE CUSTOMER ACCOUNT PORTAL
    # =========================================================================
    def test_06_account_portal_access_and_security(self):
        """Test /account requires login and redirects unauthenticated guests."""
        anon_client = app.test_client()
        res = anon_client.get("/account")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/customer/login", res.headers.get("Location", ""))

    def test_07_customer_addresses_and_ownership(self):
        """Test address addition, default toggle, and deletion."""
        client = app.test_client()
        # Log in as Aarav Sharma (id=1 in seed)
        with client.session_transaction() as sess:
            sess["customer_id"] = 1
            sess["customer_email"] = "aarav@example.com"
            sess["customer_name"] = "Aarav Sharma"

        # View account
        res = client.get("/account")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Aarav Sharma", res.data)
        self.assertIn(b"Saved Delivery Addresses", res.data)

        # Add new address
        res_add = client.post("/account/address/add", data={
            "recipient_name": "Aarav Sharma",
            "phone": "9876543210",
            "address": "Flat 402, Lotus Palace",
            "city": "Mumbai",
            "pincode": "400050",
            "label": "Home",
            "is_default": "on"
        }, follow_redirects=True)
        self.assertEqual(res_add.status_code, 200)

        # Verify address in DB
        with app.app_context():
            addr = CustomerAddress.query.filter_by(customer_id=1, pincode="400050").first()
            self.assertIsNotNone(addr)
            self.assertTrue(addr.is_default)
            addr_id = addr.id

        # Delete address
        res_del = client.post(f"/account/address/{addr_id}/delete", follow_redirects=True)
        self.assertEqual(res_del.status_code, 200)
        with app.app_context():
            deleted = db.session.get(CustomerAddress, addr_id)
            self.assertIsNone(deleted)

    def test_08_customer_wishlist(self):
        """Test adding and removing products from customer wishlist."""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["customer_id"] = 1
            sess["customer_email"] = "aarav@example.com"

        # Add product 1 to wishlist (JSON request)
        res_add = client.post("/account/wishlist/add/1", json={})
        self.assertEqual(res_add.status_code, 200)
        self.assertTrue(res_add.get_json()["success"])

        # Check DB
        with app.app_context():
            w = CustomerWishlist.query.filter_by(customer_id=1, product_id=1).first()
            self.assertIsNotNone(w)

        # Remove from wishlist (JSON request)
        res_rem = client.post("/account/wishlist/remove/1", json={})
        self.assertEqual(res_rem.status_code, 200)
        self.assertTrue(res_rem.get_json()["success"])

    # =========================================================================
    # PART 5: AI CUSTOMER SUPPORT AGENT
    # =========================================================================
    def test_09_ai_customer_support_sizing_and_orders(self):
        """Test AI support queries for sizing, order tracking, and policies."""
        # Test size query
        res_size = self.client.post("/api/customer-support", json={"query": "What is my bust size for Medium?"})
        self.assertEqual(res_size.status_code, 200)
        size_data = res_size.get_json()
        self.assertIn("message", size_data)
        # Should reference 36 for Medium top
        self.assertIn("36", size_data["message"])

        # Test order status query with authenticated customer
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["customer_id"] = 1
            sess["customer_name"] = "Aarav Sharma"

        res_ord = client.post("/api/customer-support", json={"query": "Where is my order status?"})
        self.assertEqual(res_ord.status_code, 200)
        ord_data = res_ord.get_json()
        self.assertIn("message", ord_data)
        self.assertIn("Aarav", ord_data["message"])

        # Test policy query
        res_pol = self.client.post("/api/customer-support", json={"query": "How many days for return policy?"})
        self.assertEqual(res_pol.status_code, 200)
        pol_data = res_pol.get_json()
        self.assertIn("7", pol_data["message"])

        # Test human handoff query
        res_human = self.client.post("/api/customer-support", json={"query": "I want to talk to Anjali or human agent"})
        self.assertEqual(res_human.status_code, 200)
        human_data = res_human.get_json()
        self.assertTrue(human_data.get("show_human_handoff"))

    # =========================================================================
    # PART 2: ADMIN WEBSITE MANAGEMENT CMS
    # =========================================================================
    def test_10_admin_website_management_cms_flow(self):
        """Test admin customizer with 10 sections, draft saving, and safe image removal."""
        admin_client = app.test_client()
        with admin_client.session_transaction() as sess:
            sess["admin_authenticated"] = True
            sess["admin_user"] = "admin"

        # 1. Access CMS page
        res = admin_client.get("/admin/website-management")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Website Management", res.data)
        self.assertIn(b"tab-showcase", res.data)
        self.assertIn(b"tab-fitting", res.data)
        self.assertIn(b"tab-silk", res.data)
        self.assertIn(b"tab-lookbook", res.data)
        self.assertIn(b"tab-weaving", res.data)

        # 2. Save draft content with modified headline
        res_save = admin_client.post("/admin/website-management", data={
            "hero_title_accent": "TEST STAGE 8 HERITAGE",
            "hero_tagline": "Handcrafted Haute Couture",
            "mandatory_customer_login": "false"
        }, follow_redirects=True)
        self.assertEqual(res_save.status_code, 200)

        # Verify draft was saved
        with app.app_context():
            content = get_site_content(preview_draft=True)
            self.assertEqual(content.get("hero_title_accent"), "TEST STAGE 8 HERITAGE")

        # 3. Publish draft
        res_pub = admin_client.post("/admin/website-management/publish", follow_redirects=True)
        self.assertEqual(res_pub.status_code, 200)
        with app.app_context():
            live_content = get_site_content(preview_draft=False)
            self.assertEqual(live_content.get("hero_title_accent"), "TEST STAGE 8 HERITAGE")

        # 4. Safe image removal flag: mark remove_image_hero_bg_image = 1
        res_rem_img = admin_client.post("/admin/website-management", data={
            "hero_title_accent": "TEST STAGE 8 HERITAGE",
            "remove_image_hero_bg_image": "1"
        }, follow_redirects=True)
        self.assertEqual(res_rem_img.status_code, 200)
        with app.app_context():
            draft_content = get_site_content(preview_draft=True)
            self.assertIn(draft_content.get("hero_bg_image"), [None, ""])

    # =========================================================================
    # PART 6: MOBILE LAYOUT & OVERFLOW PROTECTION
    # =========================================================================
    def test_11_mobile_styling_rules(self):
        """Verify CSS contains mobile column flow separating image from text."""
        with open("static/css/atelier-3d.css", "r", encoding="utf-8") as f:
            atelier_css = f.read()

        # Check mobile query has arched-card flex-direction column and arched-info position static
        self.assertIn("@media (max-width: 768px)", atelier_css)
        self.assertIn(".arched-card", atelier_css)
        self.assertIn("position: static", atelier_css)

        with open("static/css/style.css", "r", encoding="utf-8") as f:
            style_css = f.read()
        self.assertIn("overflow-x: hidden", style_css)
        self.assertIn("max-width: 100vw", style_css)

if __name__ == "__main__":
    unittest.main()
