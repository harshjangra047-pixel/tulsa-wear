import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

class TestMobileResponsiveness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("static/css/atelier-3d.css", "r", encoding="utf-8") as f:
            cls.atelier_css = f.read()
        with open("static/css/style.css", "r", encoding="utf-8") as f:
            cls.style_css = f.read()
        with open("templates/index.html", "r", encoding="utf-8") as f:
            cls.index_html = f.read()

    def test_mobile_viewports_coverage(self):
        """Verify CSS contains breakpoints covering 360px, 375px, 390px, 430px."""
        self.assertIn("@media (max-width: 768px)", self.atelier_css)
        self.assertIn("@media (max-width: 480px)", self.style_css)

    def test_no_text_overlay_on_mobile_product_cards(self):
        """
        Verify that on mobile screens (< 768px), arched-info has position: static or relative,
        ensuring title, category, price, and actions are placed strictly below the photo box.
        """
        # Find mobile media query block in atelier-3d.css
        pos = self.atelier_css.find("@media (max-width: 768px)")
        self.assertNotEqual(pos, -1)
        mobile_block = self.atelier_css[pos:pos+4000]

        # Check .arched-card uses column flex layout
        self.assertIn(".arched-card", mobile_block)
        self.assertIn("flex-direction: column", mobile_block)

        # Check .arched-info uses static positioning below image
        self.assertIn(".arched-info", mobile_block)
        self.assertIn("position: static", mobile_block)

        # Check arched-media has distinct aspect-ratio container
        self.assertIn(".arched-media", mobile_block)
        self.assertIn("aspect-ratio:", mobile_block)

    def test_horizontal_scroll_prevention(self):
        """Verify overflow-x: hidden is enforced on body and html to avoid mobile side-scrolling."""
        self.assertIn("overflow-x: hidden", self.style_css)
        self.assertIn("max-width: 100vw", self.style_css)

    def test_product_card_markup_structure(self):
        """Verify index.html arched-card markup nests media and info in separate semantic elements."""
        self.assertIn('class="arched-card', self.index_html)
        self.assertIn('class="arched-media"', self.index_html)
        self.assertIn('class="arched-info"', self.index_html)

if __name__ == "__main__":
    unittest.main()
