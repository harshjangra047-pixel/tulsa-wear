import os
import sys
import unittest
import hashlib
from datetime import datetime, timedelta

TEST_DB_PATH = "/tmp/tulsa_stage10_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-stage10-secret-key-32bytes-len!!"
os.environ["FLASK_ENV"] = "testing"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, db
from models.product import Product
from models.admin_user import AdminUser
from models.editor_preview_token import EditorPreviewToken

class TestStage10MobileAndCmsSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()

        with open("static/css/atelier-3d.css", "r", encoding="utf-8") as f:
            cls.atelier_css = f.read()
        with open("templates/product.html", "r", encoding="utf-8") as f:
            cls.product_html = f.read()
        with open("templates/index.html", "r", encoding="utf-8") as f:
            cls.index_html = f.read()
        with open("templates/fitting_room.html", "r", encoding="utf-8") as f:
            cls.fitting_html = f.read()
        with open("templates/admin-customizer.html", "r", encoding="utf-8") as f:
            cls.customizer_html = f.read()

        with app.app_context():
            db.create_all()
            if not AdminUser.query.filter_by(username="admin").first():
                admin = AdminUser(username="admin", default_delivery_days=10)
                admin.set_password("atelier-admin-2026")
                db.session.add(admin)
                db.session.commit()

            if not Product.query.first():
                prod = Product(
                    id=101,
                    name="Zari Handloom Emerald Suit",
                    description="Authentic Chanderi silk with antique gold threads",
                    price=2499.0,
                    original_price=3200.0,
                    category="Suits",
                    fabric="Chanderi Silk",
                    stock=8,
                    best_seller=True
                )
                db.session.add(prod)
                db.session.commit()

    def test_01_admin_customizer_safe_origin_and_preview_token(self):
        """Verify templates/admin-customizer.html uses window.location.origin instead of new URL('') and embeds preview token."""
        self.assertIn("const previewOrigin = window.location.origin;", self.customizer_html)
        self.assertNotIn("new URL('{{ website_url }}').origin", self.customizer_html)
        self.assertIn("editor_preview={{ preview_token }}", self.customizer_html)

    def test_02_editor_preview_token_generation_and_headers(self):
        """Verify that an EditorPreviewToken allows embedding without X-Frame-Options and sets CSP frame-ancestors."""
        raw_token = "stage10-test-token-safe-random-12345"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with app.app_context():
            token_rec = EditorPreviewToken(
                token_hash=token_hash,
                expires_at=datetime.utcnow() + timedelta(hours=2)
            )
            db.session.add(token_rec)
            db.session.commit()

        # Regular storefront GET (not in preview mode) has X-Frame-Options: SAMEORIGIN
        resp_regular = self.client.get("/")
        self.assertEqual(resp_regular.status_code, 200)
        self.assertEqual(resp_regular.headers.get("X-Frame-Options"), "SAMEORIGIN")

        # Preview mode with editor token
        resp_preview = self.client.get(f"/?preview=1&editor_preview={raw_token}")
        self.assertEqual(resp_preview.status_code, 200)
        self.assertIsNone(resp_preview.headers.get("X-Frame-Options"))
        self.assertIn("frame-ancestors 'self' *", resp_preview.headers.get("Content-Security-Policy", ""))
        self.assertIn("no-store", resp_preview.headers.get("Cache-Control", ""))

    def test_03_heritage_curtain_suppressed_in_preview(self):
        """Verify heritageOpeningCurtain is conditioned on {% if not editor_preview %}."""
        self.assertIn("{% if not editor_preview %}", self.index_html)
        raw_token = "curtain-bypass-test-token-67890"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with app.app_context():
            token_rec = EditorPreviewToken(
                token_hash=token_hash,
                expires_at=datetime.utcnow() + timedelta(hours=2)
            )
            db.session.add(token_rec)
            db.session.commit()

        resp_preview = self.client.get(f"/?preview=1&editor_preview={raw_token}")
        self.assertNotIn('id="heritageOpeningCurtain"', resp_preview.get_data(as_text=True))

    def test_04_promo_showcase_genuine_catalogue_data(self):
        """Verify virtual-try-on-promo has no hardcoded 404 images or fake ₹28,500 prices."""
        self.assertNotIn("garment-01-anarkali.jpg", self.index_html)
        self.assertNotIn("₹28,500", self.index_html)
        resp = self.client.get("/")
        content = resp.get_data(as_text=True)
        self.assertIn("Zari Handloom Emerald Suit", content)
        self.assertIn("₹2,499", content)

    def test_05_fitting_room_and_look_builder_robust_fallback(self):
        """Verify fitting stage images include onerror fallbacks in templates and JS."""
        self.assertIn('id="fittingStageImg"', self.index_html)
        self.assertIn("onerror=", self.index_html)
        self.assertIn('id="fittingStageImg"', self.fitting_html)
        self.assertIn("onerror=", self.fitting_html)

    def test_06_weaving_studio_mobile_responsive_css(self):
        """Verify weaving studio floating bar and strand tabs wrap cleanly on mobile viewports."""
        self.assertIn(".weaving-floating-bar {", self.atelier_css)
        self.assertIn(".weave-strand-tabs {", self.atelier_css)
        self.assertIn("grid-template-columns: repeat(3, 1fr)", self.atelier_css)
        self.assertIn(".weave-color-swatches {", self.atelier_css)

    def test_07_pdp_sticky_bar_intersection_observer(self):
        """Verify PDP mobile sticky bar has transition, is-hidden class and IntersectionObserver logic."""
        self.assertIn(".pdp-mobile-sticky-bar.is-hidden", self.atelier_css)
        self.assertIn('id="pdpMainAddBagBtn"', self.product_html)
        self.assertIn("IntersectionObserver", self.product_html)

if __name__ == "__main__":
    unittest.main()
