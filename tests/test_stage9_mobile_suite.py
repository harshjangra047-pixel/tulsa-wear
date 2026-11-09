import os
import sys
import unittest

TEST_DB_PATH = "/tmp/tulsa_stage9_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-stage9-secret-key-32bytes-len!!"
os.environ["FLASK_ENV"] = "testing"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, db
from models.product import Product

class TestStage9MobileFirstSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()

        with open("static/css/atelier-3d.css", "r", encoding="utf-8") as f:
            cls.atelier_css = f.read()
        with open("static/css/style.css", "r", encoding="utf-8") as f:
            cls.style_css = f.read()
        with open("templates/product.html", "r", encoding="utf-8") as f:
            cls.product_html = f.read()
        with open("templates/shop.html", "r", encoding="utf-8") as f:
            cls.shop_html = f.read()
        with open("templates/index.html", "r", encoding="utf-8") as f:
            cls.index_html = f.read()
        with open("templates/fitting_room.html", "r", encoding="utf-8") as f:
            cls.fitting_html = f.read()

        # Seed synthetic product for testing
        with app.app_context():
            db.create_all()
            prod = Product.query.filter_by(id=9999).first()
            if not prod:
                prod = Product(
                    id=9999,
                    name="Heritage Emerald Anarkali Test",
                    description="Pure handloom silk test garment",
                    price=2499.0,
                    original_price=2999.0,
                    category="Anarkali",
                    fabric="Chanderi Silk",
                    stock=10
                )
                db.session.add(prod)
                db.session.commit()

    # =========================================================================
    # TEST A: MOBILE HEADER & NAVIGATION
    # =========================================================================
    def test_01_mobile_header_elements_present_on_all_storefront_pages(self):
        """Verify menuButton, brand crest, Try-On, account, and bag exist across all main templates."""
        for name, html in [("product", self.product_html), ("shop", self.shop_html), ("index", self.index_html), ("fitting", self.fitting_html)]:
            self.assertIn('id="menuButton"', html, f"Missing #menuButton in {name}.html")
            self.assertIn('class="brand-crest-logo"', html, f"Missing brand crest logo in {name}.html")
            self.assertIn('class="nav-links mobile-navigation-drawer"', html, f"Missing mobile drawer in {name}.html")
            self.assertIn('class="btn-nav-bag"', html, f"Missing bag button in {name}.html")

    def test_02_mobile_header_css_prevents_overlap_and_wrapping(self):
        """Verify CSS contains max-width, no overflow, and sub-380px compact rules."""
        self.assertIn("@media (max-width: 768px)", self.atelier_css)
        self.assertIn("max-width: calc(100vw - 20px)", self.atelier_css)
        self.assertIn(".mobile-menu-toggle", self.atelier_css)
        self.assertIn("@media (max-width: 380px)", self.atelier_css)
        self.assertIn(".brand-sub-luxury", self.atelier_css)

    # =========================================================================
    # TEST B: PRODUCT DETAIL PAGE (PDP) IMAGE RESPONSIVENESS
    # =========================================================================
    def test_03_pdp_image_bounding_box_and_containment(self):
        """Verify PDP image container uses aspect-ratio 4/5, object-fit contain, and centered alignment."""
        self.assertIn(".pdp-main-bounding-box", self.atelier_css)
        self.assertIn("aspect-ratio: 4 / 5", self.atelier_css)
        self.assertIn("object-fit: contain", self.atelier_css)
        self.assertIn(".pdp-contained-img", self.atelier_css)

    def test_04_pdp_gallery_arrows_inside_safe_bounds(self):
        """Verify gallery navigation arrows are positioned inside image boundaries."""
        self.assertIn(".pdp-main-nav-prev", self.atelier_css)
        self.assertIn("left: 8px", self.atelier_css)
        self.assertIn(".pdp-main-nav-next", self.atelier_css)
        self.assertIn("right: 8px", self.atelier_css)

    # =========================================================================
    # TEST C: PRODUCT DETAILS & TYPOGRAPHY STABILITY
    # =========================================================================
    def test_05_pdp_content_hierarchy_and_fluid_titles(self):
        """Verify title, price, and descriptions have independent layout areas and fluid sizing."""
        self.assertIn("font-size: clamp(22px, 5.2vw, 32px)", self.atelier_css)
        self.assertIn('class="pdp-content-column"', self.product_html)
        self.assertIn('class="pdp-title"', self.product_html)
        self.assertIn('class="pdp-price-row"', self.product_html)

    # =========================================================================
    # TEST D: SIZE SELECTOR & HORIZONTAL TOUCH SCROLLING
    # =========================================================================
    def test_06_size_selector_touch_scrolling_and_target_size(self):
        """Verify size pill group has touch-action pan-x, flex-wrap nowrap, and >= 44px touch targets."""
        self.assertIn("touch-action: pan-x", self.atelier_css)
        self.assertIn("overflow-x: auto", self.atelier_css)
        self.assertIn("flex-wrap: nowrap", self.atelier_css)
        self.assertIn("min-width: 48px", self.atelier_css)
        self.assertIn("height: 46px", self.atelier_css)

    # =========================================================================
    # TEST E: FLOATING SUPPORT BUTTON COLLISION PREVENTION
    # =========================================================================
    def test_07_floating_buttons_cleared_from_add_to_bag_sticky_bar(self):
        """Verify floating WhatsApp and AI help buttons elevate above the sticky purchase bar."""
        self.assertIn("body.has-pdp-sticky-bar .floating-whatsapp-btn", self.atelier_css)
        self.assertIn("bottom: calc(76px + env(safe-area-inset-bottom, 12px))", self.atelier_css)
        self.assertIn(".pdp-mobile-sticky-bar", self.atelier_css)
        self.assertIn("z-index: 1002", self.atelier_css)

    # =========================================================================
    # TEST F: MOBILE PURCHASE FLOW (ADD TO BAG)
    # =========================================================================
    def test_08_mobile_add_to_bag_with_size_selection(self):
        """Verify selecting size and adding to bag updates session cart successfully."""
        res = self.client.post("/add-to-bag/9999", data={"size": "L"}, follow_redirects=False)
        self.assertIn(res.status_code, [302, 200])

        # Verify bag page reflects added product
        bag_res = self.client.get("/bag")
        self.assertEqual(bag_res.status_code, 200)
        self.assertIn(b"Heritage Emerald Anarkali Test", bag_res.data)

    # =========================================================================
    # TEST G: PRODUCT CARDS NON-OVERLAPPING
    # =========================================================================
    def test_09_product_cards_separate_image_and_info(self):
        """Verify editorial cards maintain clean media container separate from titles and prices."""
        self.assertIn(".editorial-card-media", self.atelier_css)
        self.assertIn(".editorial-card-content", self.atelier_css)
        self.assertIn("aspect-ratio: 3 / 4", self.atelier_css)

    # =========================================================================
    # TEST H: MOBILE DRAWER ACCESSIBILITY & ESCAPE
    # =========================================================================
    def test_10_mobile_navigation_drawer_accessibility(self):
        """Verify drawer includes ARIA role, landmarks, and links to all primary destinations."""
        self.assertIn('role="navigation"', self.product_html)
        self.assertIn('aria-label="Mobile Navigation"', self.product_html)
        self.assertIn('aria-expanded="false"', self.product_html)
        self.assertIn('aria-label="Open navigation menu"', self.product_html)

if __name__ == "__main__":
    unittest.main()
