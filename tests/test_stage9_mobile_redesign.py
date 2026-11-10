import os
import sys
import unittest

TEST_DB_PATH = "/tmp/tulsa_stage10_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-stage9-secret-key-32bytes-len!!"
os.environ["FLASK_ENV"] = "testing"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app, db


class TestStage9MobileRedesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.client = app.test_client()

    def test_mobile_bottom_navigation_present_on_home(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('class="mobile-bottom-nav"', html)
        self.assertIn('class="mobile-nav-tab', html)
        self.assertIn('Home', html)
        self.assertIn('Shop', html)
        self.assertIn('Collections', html)
        self.assertIn('Wishlist', html)
        self.assertIn('Account', html)

    def test_mobile_header_elements_present(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        # Circular Try-on badge
        self.assertIn('nav-tryon-mobile-circle', html)
        self.assertIn('TRY-<br>ON', html)
        # Bag icon and counter
        self.assertIn('btn-nav-bag-icon', html)
        # Account outline icon
        self.assertIn('nav-link-account-icon', html)

    def test_mobile_hero_content_present(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('mobile-mockup-hero-card', html)
        self.assertIn('YOUR STYLE.', html)
        self.assertIn('YOUR FIT.', html)
        self.assertIn('YOUR EXPERIENCE.', html)
        self.assertIn('EXPLORE COLLECTIONS →', html)
        self.assertIn('mobile-hero-dots', html)

    def test_our_collections_arched_cards_present(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('OUR COLLECTIONS', html)
        self.assertIn('Festive', html)
        self.assertIn('Bridal', html)
        self.assertIn('Silk', html)
        self.assertIn('Lookbook', html)

    def test_mobile_vton_banner_card_present(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('mobile-vton-card-wrap', html)
        self.assertIn('mobile-vton-banner-card', html)
        self.assertIn('silhouette-gold-svg', html)
        self.assertIn('VIRTUAL FITTING ROOM', html)
        self.assertIn('Try. Experience. Own.', html)
        self.assertIn('TRY NOW →', html)
        self.assertIn('/fitting-room', html)

    def test_pdp_renders_and_suppresses_bottom_nav_in_css(self):
        # Read CSS file to verify PDP bottom nav suppression
        with open('static/css/atelier-3d.css', 'r', encoding='utf-8') as f:
            css = f.read()
        self.assertIn('body.is-pdp-page .mobile-bottom-nav', css)
        self.assertIn('display: none !important', css)

    def test_ai_support_bubble_in_html(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('ai-help-bubble-icon', html)


if __name__ == '__main__':
    unittest.main()
