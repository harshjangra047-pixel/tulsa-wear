"""Unit & Integration tests for Tulsa Wears Storefront Category Navigation,

Multi-Category Assignments, and Admin Product Editing.
"""
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

TEST_DB_DIR = Path(tempfile.gettempdir()) / "tulsa-cat-tests"
TEST_DB_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DB_DIR / f"{uuid4().hex}.db")
os.environ["FLASK_SECRET_KEY"] = "cat-test-session-secret"
os.environ["ADMIN_PASSWORD"] = "Admin-Test-Pass-9933"
os.environ["ADMIN_USERNAME"] = "test-admin"
os.environ["FLASK_ENV"] = "testing"

import app as site
from models.database import db
from models.product import Product
from models.product_category import ProductCategory
from models.product_image import ProductImage
from models.admin_user import AdminUser
from services.category_service import (
    resolve_canonical_category,
    get_equivalent_categories,
    is_category_active,
    filter_products_by_category,
    CANONICAL_PALAZZO,
    CANONICAL_SALWAR,
    CANONICAL_CASUAL,
    CANONICAL_PARTY_WEDDING,
    CANONICAL_BEST_SELLERS,
)


class CategoryAndAdminEditTests(unittest.TestCase):
    def setUp(self):
        site.app.config["TESTING"] = True
        site.app.config["WTF_CSRF_ENABLED"] = False
        self.client = site.app.test_client()

        with site.app.app_context():
            site.ensure_schema_migrations()
            db.session.remove()
            db.drop_all()
            db.create_all()

            # Ensure admin exists
            admin = AdminUser(username="test-admin")
            admin.set_password("Admin-Test-Pass-9933")
            db.session.add(admin)

            # Create test products with both legacy and canonical categories
            p1 = Product(
                name="Casual Kurti Daily Piece",
                price=1800.0,
                original_price=2200.0,
                discount_percent=18,
                category="Casual / Kurti",  # Legacy production category
                stock=15,
            )
            p2 = Product(
                name="Palazzo Heritage Set",
                price=3200.0,
                category="Plazo / Kurta",  # Legacy production category
                stock=10,
            )
            p3 = Product(
                name="Royal Silk Salwar Suit",
                price=2900.0,
                category="Salwar Kameez",
                stock=8,
            )
            p4 = Product(
                name="Regalia Embroidered Ensemble",
                price=5500.0,
                category="Festival / Wedding Regalia",  # Legacy production category
                stock=5,
            )
            # Multi-category product
            p5 = Product(
                name="Multi-Collection Yellow Dress",
                price=2400.0,
                original_price=3000.0,
                category="Casual Wear",
                category_2="Best Sellers",
                category_3="Party / Wedding Regalia",
                stock=12,
                best_seller=True,
            )

            db.session.add_all([p1, p2, p3, p4, p5])
            db.session.commit()

            # Add product category entries
            db.session.add(ProductCategory(product_id=p1.id, category=p1.category, is_primary=True))
            db.session.add(ProductCategory(product_id=p2.id, category=p2.category, is_primary=True))
            db.session.add(ProductCategory(product_id=p3.id, category=p3.category, is_primary=True))
            db.session.add(ProductCategory(product_id=p4.id, category=p4.category, is_primary=True))
            db.session.add(ProductCategory(product_id=p5.id, category=p5.category, is_primary=True))
            db.session.add(ProductCategory(product_id=p5.id, category="Best Sellers", is_primary=False))
            db.session.add(ProductCategory(product_id=p5.id, category="Party / Wedding Regalia", is_primary=False))
            db.session.commit()

            self.p1_id = p1.id
            self.p2_id = p2.id
            self.p3_id = p3.id
            self.p4_id = p4.id
            self.p5_id = p5.id

    def test_canonical_category_resolution(self):
        """Test canonical mapping for all variants and slug styles."""
        self.assertEqual(resolve_canonical_category("Casual Wear"), CANONICAL_CASUAL)
        self.assertEqual(resolve_canonical_category("Casual / Kurti"), CANONICAL_CASUAL)
        self.assertEqual(resolve_canonical_category("casual-kurti"), CANONICAL_CASUAL)
        self.assertEqual(resolve_canonical_category("Palazzo Set"), CANONICAL_PALAZZO)
        self.assertEqual(resolve_canonical_category("Plazo / Kurta"), CANONICAL_PALAZZO)
        self.assertEqual(resolve_canonical_category("Salwar Kameez"), CANONICAL_SALWAR)
        self.assertEqual(resolve_canonical_category("Party / Wedding Regalia"), CANONICAL_PARTY_WEDDING)
        self.assertEqual(resolve_canonical_category("Festival / Wedding Regalia"), CANONICAL_PARTY_WEDDING)
        self.assertEqual(resolve_canonical_category("Wedding Wear"), CANONICAL_PARTY_WEDDING)
        self.assertEqual(resolve_canonical_category("Party Wear"), CANONICAL_PARTY_WEDDING)

    def test_is_category_active(self):
        """Test active filter pill detection across aliases."""
        self.assertTrue(is_category_active("Casual Wear", "Casual / Kurti"))
        self.assertTrue(is_category_active("Casual Wear", "casual-wear"))
        self.assertTrue(is_category_active("Palazzo Set", "Plazo / Kurta"))
        self.assertTrue(is_category_active("Party / Wedding Regalia", "Festival / Wedding Regalia"))
        self.assertFalse(is_category_active("Palazzo Set", "Casual Wear"))

    def test_storefront_casual_wear_query(self):
        """Clicking Casual Wear immediately finds garments with Casual / Kurti and Casual Wear."""
        resp = self.client.get("/shop?category=Casual+Wear")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        # Should NOT show empty state
        self.assertNotIn("No Garments Found", html)
        self.assertIn("Casual Kurti Daily Piece", html)
        self.assertIn("Multi-Collection Yellow Dress", html)
        # Should not show unrelated garments
        self.assertNotIn("Palazzo Heritage Set", html)

    def test_storefront_palazzo_set_query(self):
        """Clicking Palazzo Set immediately finds garments with Plazo / Kurta."""
        resp = self.client.get("/shop?category=Palazzo+Set")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertNotIn("No Garments Found", html)
        self.assertIn("Palazzo Heritage Set", html)
        self.assertNotIn("Casual Kurti Daily Piece", html)

    def test_storefront_salwar_kameez_query(self):
        """Clicking Salwar Kameez finds Salwar garments."""
        resp = self.client.get("/shop?category=Salwar+Kameez")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertNotIn("No Garments Found", html)
        self.assertIn("Royal Silk Salwar Suit", html)

    def test_storefront_party_wedding_regalia_query(self):
        """Clicking Party / Wedding Regalia finds Festival/Wedding/Party garments."""
        resp = self.client.get("/shop?category=Party+/+Wedding+Regalia")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertNotIn("No Garments Found", html)
        self.assertIn("Regalia Embroidered Ensemble", html)
        self.assertIn("Multi-Collection Yellow Dress", html)

    def test_multi_category_garment_in_multiple_collections(self):
        """A garment assigned to multiple categories appears in all assigned collections."""
        # Check Casual Wear
        r1 = self.client.get("/shop?category=Casual+Wear")
        self.assertIn("Multi-Collection Yellow Dress", r1.data.decode("utf-8"))

        # Check Best Sellers
        r2 = self.client.get("/shop?category=Best+Sellers")
        self.assertIn("Multi-Collection Yellow Dress", r2.data.decode("utf-8"))

        # Check Party / Wedding Regalia
        r3 = self.client.get("/shop?category=Party+/+Wedding+Regalia")
        self.assertIn("Multi-Collection Yellow Dress", r3.data.decode("utf-8"))

    def test_no_duplicate_garment_in_single_collection(self):
        """Ensure no duplicate cards when a garment matches on primary and alt categories."""
        with site.app.app_context():
            query = Product.query
            query = filter_products_by_category(query, "Casual Wear")
            results = query.all()
            ids = [p.id for p in results]
            self.assertEqual(len(ids), len(set(ids)), "Product IDs must be unique in query results")

    def test_admin_edit_page_get(self):
        """Test GET /admin/products/edit/<id> loads complete existing product data."""
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
            sess["admin_user"] = "test-admin"

        resp = self.client.get(f"/admin/products/edit/{self.p5_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Must not be an empty or blurred page
        self.assertIn("Edit Garment: Multi-Collection Yellow Dress", html)
        self.assertIn('value="Multi-Collection Yellow Dress"', html)
        self.assertIn('value="2400"', html)
        self.assertIn('value="3000"', html)
        # Category dropdowns populated
        self.assertIn("★ Primary Category", html)
        self.assertIn("Additional Collection Assignments", html)

    def test_admin_edit_page_post_save(self):
        """Test POST /admin/products/edit/<id> updates details and multi-category assignments."""
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
            sess["admin_user"] = "test-admin"

        data = {
            "name": "Updated Silk Anarkali Suit",
            "price": "3499",
            "original_price": "4999",
            "discount_percent": "30",
            "category": "Salwar Kameez",
            "category_2": "Best Sellers",
            "category_3": "Party / Wedding Regalia",
            "category_4": "",
            "fabric": "Chanderi Silk",
            "color": "Emerald Green",
            "stock": "25",
            "description": "Exquisite hand-finished festive couture.",
            "weight_kg": "0.75",
            "length_cm": "35",
            "width_cm": "28",
            "height_cm": "6",
        }
        resp = self.client.post(f"/admin/products/edit/{self.p1_id}", data=data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify database persisted values
        with site.app.app_context():
            p = db.session.get(Product, self.p1_id)
            self.assertEqual(p.name, "Updated Silk Anarkali Suit")
            self.assertEqual(p.price, 3499.0)
            self.assertEqual(p.original_price, 4999.0)
            self.assertEqual(p.category, "Salwar Kameez")
            self.assertEqual(p.category_2, "Best Sellers")
            self.assertEqual(p.category_3, "Party / Wedding Regalia")
            self.assertIsNone(p.category_4)
            self.assertEqual(p.fabric, "Chanderi Silk")
            self.assertEqual(p.color, "Emerald Green")
            self.assertEqual(p.stock, 25)
            self.assertEqual(p.effective_discount_percent, 30)

            # Verify ProductCategory records
            assigned_cats = {c.category for c in p.product_category_records}
            self.assertEqual(assigned_cats, {"Salwar Kameez", "Best Sellers", "Party / Wedding Regalia"})

    def test_admin_add_product_multi_category(self):
        """Test adding new garment with primary + alt categories."""
        with self.client.session_transaction() as sess:
            sess["admin_authenticated"] = True
            sess["admin_user"] = "test-admin"

        data = {
            "name": "New Handcrafted Velvet Ensemble",
            "price": "4200",
            "original_price": "5600",
            "category": "Party / Wedding Regalia",
            "category_2": "Best Sellers",
            "category_3": "New Arrivals",
            "category_4": "",
            "fabric": "Royal Velvet",
            "color": "Midnight Blue",
            "stock": "7",
            "description": "Slow fashion couture piece.",
            "weight_kg": "0.9",
            "length_cm": "32",
            "width_cm": "26",
            "height_cm": "8",
        }
        resp = self.client.post("/admin/products/add", data=data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        with site.app.app_context():
            new_p = Product.query.filter_by(name="New Handcrafted Velvet Ensemble").first()
            self.assertIsNotNone(new_p)
            self.assertEqual(new_p.category, "Party / Wedding Regalia")
            self.assertEqual(new_p.category_2, "Best Sellers")
            self.assertEqual(new_p.category_3, "New Arrivals")

            # Must appear in Party / Wedding Regalia query
            q1 = filter_products_by_category(Product.query, "Party / Wedding Regalia")
            self.assertIn(new_p.id, [p.id for p in q1.all()])

            # Must appear in Best Sellers query
            q2 = filter_products_by_category(Product.query, "Best Sellers")
            self.assertIn(new_p.id, [p.id for p in q2.all()])


if __name__ == "__main__":
    unittest.main()
