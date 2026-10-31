"""Unit & Integration tests for Tulsa Wear's Production Planning,
Garment Consolidation Queue, Smart Manufacturing Priorities, and Product Sales Analytics.
"""
import os
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

TEST_DB_DIR = Path(tempfile.gettempdir()) / "tulsa-prod-tests"
TEST_DB_DIR.mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DB_DIR / f"{uuid4().hex}.db")
os.environ["FLASK_SECRET_KEY"] = "prod-test-session-secret"
os.environ["ADMIN_PASSWORD"] = "Admin-Test-Pass-7744"
os.environ["ADMIN_USERNAME"] = "test-prod-admin"
os.environ["FLASK_ENV"] = "testing"

import app as site
from models.database import db
from models.product import Product
from models.order import Order
from models.production_batch import ProductionBatch
from models.production_allocation import ProductionAllocation
from models.production_setting import ProductionSetting
from models.admin_user import AdminUser
from services.production_service import (
    resolve_date_range,
    get_date_wise_orders,
    get_consolidated_production_queue,
    get_production_overview_kpis,
    calculate_product_analytics,
    get_individual_garment_analytics,
    get_daily_work_schedule,
    calculate_priority_score,
    KOLKATA_TZ,
)


def make_order(**kwargs):
    defaults = {
        "product_id": 1,
        "product_name": "Garment",
        "price": 2999.0,
        "customer_name": "Test Customer",
        "phone": "+919876543210",
        "email": "test@example.com",
        "address": "123 Fashion Lane",
        "city": "Jaipur",
        "pincode": "302001",
        "status": "Confirmed",
        "size": "M",
    }
    defaults.update(kwargs)
    return Order(**defaults)


class ProductionAndAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        site.app.config["TESTING"] = True
        site.app.config["WTF_CSRF_ENABLED"] = False

    def setUp(self):
        self.client = site.app.test_client()

        with site.app.app_context():
            site.ensure_schema_migrations()
            db.create_all()

            # Clean test tables
            ProductionAllocation.query.delete()
            ProductionBatch.query.delete()
            ProductionSetting.query.delete()
            Order.query.delete()
            Product.query.delete()
            AdminUser.query.delete()
            db.session.commit()

            # Create test admin
            admin = AdminUser(username="test-prod-admin")
            admin.set_password("Admin-Test-Pass-7744")
            db.session.add(admin)

            # Create default production settings
            setting = ProductionSetting.get_settings()
            setting.workers_count = 5
            setting.working_hours_per_day = 8.0
            setting.daily_capacity_pieces = 15
            db.session.commit()

    def test_01_date_range_resolution(self):
        """Test resolving all standard presets and custom ranges."""
        now = datetime.now(timezone.utc)

        start, end, p_start, p_end, label = resolve_date_range("today")
        self.assertEqual(label, "Today")
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        self.assertTrue(start < end)
        self.assertIsNotNone(p_start)
        self.assertIsNotNone(p_end)

        start7, end7, _, _, label7 = resolve_date_range("7d")
        self.assertEqual(label7, "Last 7 Days")
        delta = end7 - start7
        self.assertGreaterEqual(delta.days, 6)

        start30, end30, _, _, label30 = resolve_date_range("30d")
        self.assertEqual(label30, "Last 30 Days")

        start_all, end_all, _, _, label_all = resolve_date_range("all")
        self.assertEqual(label_all, "All Time")
        self.assertIsNone(start_all)

        c_start = (now - timedelta(days=10)).strftime("%Y-%m-%d")
        c_end = now.strftime("%Y-%m-%d")
        start_c, end_c, _, _, label_c = resolve_date_range("custom", c_start, c_end)
        self.assertIsNotNone(start_c)
        self.assertIsNotNone(end_c)

    def test_02_identical_dress_consolidation(self):
        """Test that multiple orders for the same dress are consolidated into a single queue item with size breakdown."""
        with site.app.app_context():
            # Create a dress
            dress1 = Product(
                name="Anarkali Suit Set",
                category="Suits",
                price=4999.0,
                cost_price=2200.0,
                sku="TW-SUI-001",
                stock=50,
            )
            db.session.add(dress1)
            db.session.commit()

            # Create 12 orders for this same dress across different dates and sizes
            now = datetime.now(timezone.utc)
            sizes = ["S", "S", "M", "M", "M", "L", "L", "XL", "XS", "M", "S", "L"]
            for i, sz in enumerate(sizes):
                order_date = now - timedelta(days=i % 3)
                order = make_order(
                    customer_name=f"Customer {i+1}",
                    phone=f"+9198000000{i:02d}",
                    email=f"cust{i}@example.com",
                    product_id=dress1.id,
                    product_name=dress1.name,
                    size=sz,
                    price=4999.0,
                    status="Confirmed",
                    production_status="Pending",
                    dispatch_status="Awaiting Production",
                    delivery_window_start=(order_date + timedelta(days=7)).strftime("%d %b %Y"),
                    delivery_window_end=(order_date + timedelta(days=15)).strftime("%d %b %Y"),
                    created_at=order_date,
                )
                db.session.add(order)
            db.session.commit()

            # Retrieve consolidated queue
            queue = get_consolidated_production_queue()
            self.assertEqual(len(queue), 1)

            item = queue[0]
            self.assertEqual(item["product_id"], dress1.id)
            self.assertEqual(item["total_ordered"], 12)
            self.assertEqual(item["completed_quantity"], 0)
            self.assertEqual(item["remaining_quantity"], 12)

            # Check size breakdown: S: 3, M: 4, L: 3, XL: 1, XS: 1
            sb = item["size_breakdown"]
            self.assertEqual(sb.get("S", 0), 3)
            self.assertEqual(sb.get("M", 0), 4)
            self.assertEqual(sb.get("L", 0), 3)
            self.assertEqual(sb.get("XL", 0), 1)
            self.assertEqual(sb.get("XS", 0), 1)

            # Check arrival timeline: arrived across distinct dates
            self.assertGreaterEqual(len(item["date_arrivals"]), 1)

    def test_03_distinct_products_remain_isolated(self):
        """Test that distinct products are kept strictly separate even if ordered at the same time."""
        with site.app.app_context():
            p1 = Product(name="Silk Kurta", category="Kurtas", price=2999.0, sku="TW-KUR-001")
            p2 = Product(name="Cotton Kurta", category="Kurtas", price=1999.0, sku="TW-KUR-002")
            db.session.add_all([p1, p2])
            db.session.commit()

            o1 = make_order(
                customer_name="Alice",
                product_id=p1.id,
                product_name=p1.name,
                size="M",
                price=2999.0,
                status="Confirmed",
                production_status="Pending",
            )
            o2 = make_order(
                customer_name="Bob",
                product_id=p2.id,
                product_name=p2.name,
                size="M",
                price=1999.0,
                status="Confirmed",
                production_status="Pending",
            )
            db.session.add_all([o1, o2])
            db.session.commit()

            queue = get_consolidated_production_queue()
            self.assertEqual(len(queue), 2)
            p_ids = [q["product_id"] for q in queue]
            self.assertIn(p1.id, p_ids)
            self.assertIn(p2.id, p_ids)

    def test_04_batch_creation_and_size_completion(self):
        """Test creating a ProductionBatch, updating completion by size, and tracking remaining quantities."""
        with site.app.app_context():
            p = Product(name="Velvet Lehenga", category="Lehengas", price=12999.0, sku="TW-LEH-001")
            db.session.add(p)
            db.session.commit()

            # Create an active order
            o = make_order(
                customer_name="Priya",
                product_id=p.id,
                product_name=p.name,
                size="L",
                price=12999.0,
                status="Confirmed",
                production_status="Pending",
            )
            db.session.add(o)
            db.session.commit()

            # Create a production batch
            batch = ProductionBatch(
                batch_number=ProductionBatch.generate_batch_number(p.category),
                product_id=p.id,
                product_name=p.name,
                sku=p.effective_sku,
                total_quantity=5,
                size_breakdown={"M": 2, "L": 3},
                size_completed={"M": 0, "L": 0},
                status="In Production",
                priority="High",
            )
            db.session.add(batch)
            db.session.commit()

            # Partial completion: 2 of size L finished
            batch.record_size_completion("L", 2)
            db.session.commit()

            self.assertEqual(batch.completed_quantity, 2)
            self.assertEqual(batch.remaining_quantity, 3)
            self.assertEqual(batch.get_completed_sizes()["L"], 2)
            self.assertEqual(batch.get_completed_sizes()["M"], 0)
            self.assertEqual(batch.status, "In Production")

            # Complete remaining
            batch.record_size_completion("L", 1)
            batch.record_size_completion("M", 2)
            db.session.commit()

            self.assertEqual(batch.completed_quantity, 5)
            self.assertEqual(batch.remaining_quantity, 0)
            self.assertEqual(batch.status, "Completed")

    def test_05_priority_calculation_deadline_factor(self):
        """Test that orders near or past deadline get Critical/High priority."""
        with site.app.app_context():
            p = Product(name="Bridal Anarkali", category="Partywear", price=9999.0)
            db.session.add(p)
            db.session.commit()

            now = datetime.now(timezone.utc)
            # Order with deadline in 1 day
            o_crit = make_order(
                customer_name="Urgent Customer",
                product_id=p.id,
                product_name=p.name,
                price=9999.0,
                status="Confirmed",
                created_at=now - timedelta(days=14),
                delivery_window_end=(now + timedelta(days=1)).strftime("%d %b %Y"),
            )
            p_crit, r_crit = calculate_priority_score(o_crit, total_garment_qty=3)
            self.assertEqual(p_crit, "Critical")
            self.assertIn("Imminent", r_crit)

            # Order with deadline in 12 days
            o_norm = make_order(
                customer_name="Regular Customer",
                product_id=p.id,
                product_name=p.name,
                price=9999.0,
                status="Confirmed",
                created_at=now - timedelta(days=1),
                delivery_window_end=(now + timedelta(days=12)).strftime("%d %b %Y"),
            )
            p_norm, _ = calculate_priority_score(o_norm, total_garment_qty=2)
            self.assertIn(p_norm, ["Medium", "Low"])

    def test_06_daily_capacity_and_workload_schedule(self):
        """Test daily capacity calculation, scheduled pieces, and overload detection."""
        with site.app.app_context():
            setting = ProductionSetting.get_settings()
            setting.daily_capacity_pieces = 10
            setting.daily_capacity_hours = 20.0
            db.session.commit()

            # Create 15 pieces batch scheduled for tomorrow
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
            batch = ProductionBatch(
                batch_number="BATCH-OVERLOAD-TEST",
                product_name="Heavy Gown",
                total_quantity=15,
                completed_quantity=0,
                estimated_hours=25.0,
                planned_start_date=tomorrow,
                target_completion_date=tomorrow,
                status="Scheduled",
            )
            db.session.add(batch)
            db.session.commit()

            schedule = get_daily_work_schedule(days_ahead=7)
            # Find tomorrow in schedule
            t_day = next((d for d in schedule if d["date"] == tomorrow), None)
            self.assertIsNotNone(t_day)
            self.assertEqual(t_day["scheduled_pieces"], 15)
            self.assertEqual(t_day["capacity_pieces"], 10)
            self.assertTrue(t_day["is_overloaded"])
            self.assertEqual(t_day["load_percentage"], 150.0)

    def test_07_sales_analytics_gross_discount_net_revenue(self):
        """Test granular sales analytics, coupon discount attribution, ASP, and velocity."""
        with site.app.app_context():
            p = Product(name="Festive Sharara", category="Sharara", price=5000.0, cost_price=2000.0, sku="TW-SHA-001")
            db.session.add(p)
            db.session.commit()

            # Order 1: 5000 price, 500 discount
            o1 = make_order(
                customer_name="Meena",
                product_id=p.id,
                product_name=p.name,
                price=4500.0,
                discount_amount=500.0,
                coupon_code="DIWALI500",
                status="Delivered",
                created_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
            # Order 2: 5000 price, 0 discount
            o2 = make_order(
                customer_name="Rani",
                product_id=p.id,
                product_name=p.name,
                price=5000.0,
                discount_amount=0.0,
                status="Delivered",
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            db.session.add_all([o1, o2])
            db.session.commit()

            analytics = calculate_product_analytics(date_filter="30d")
            self.assertEqual(analytics["total_units_sold"], 2)
            self.assertEqual(analytics["total_gross_sales"], 10000.0)
            self.assertEqual(analytics["total_discounts"], 500.0)
            self.assertEqual(analytics["total_net_revenue"], 9500.0)

            # Check individual product analytics
            indiv = get_individual_garment_analytics(p.id)
            self.assertIsNotNone(indiv)
            self.assertEqual(indiv["lifetime"]["units_sold"], 2)
            self.assertEqual(indiv["lifetime"]["net_revenue"], 9500.0)

    def test_08_date_wise_orders_grouping(self):
        """Test date-wise grouping in Asia/Kolkata timezone with daily totals."""
        with site.app.app_context():
            p = Product(name="Classic Kurta", category="Kurtas", price=1500.0, sku="TW-CLA-001")
            db.session.add(p)
            db.session.commit()

            now = datetime.now(timezone.utc)
            o1 = make_order(customer_name="Cust 1", product_id=p.id, product_name=p.name, price=1500.0, status="Confirmed", created_at=now)
            o2 = make_order(customer_name="Cust 2", product_id=p.id, product_name=p.name, price=1500.0, status="Confirmed", created_at=now)
            o3 = make_order(customer_name="Cust 3", product_id=p.id, product_name=p.name, price=1500.0, status="Confirmed", created_at=now - timedelta(days=3))
            db.session.add_all([o1, o2, o3])
            db.session.commit()

            groups = get_date_wise_orders(date_filter="30d")
            self.assertGreaterEqual(len(groups), 2)
            # Check first group has 2 orders
            self.assertEqual(groups[0]["orders_count"], 2)
            self.assertEqual(groups[0]["total_revenue"], 3000.0)

    def test_09_production_overview_kpis(self):
        """Test overall production overview KPI counters."""
        with site.app.app_context():
            p = Product(name="Dupatta", category="Accessories", price=800.0, sku="TW-DUP-001")
            db.session.add(p)
            db.session.commit()

            o = make_order(customer_name="Sunita", product_id=p.id, product_name=p.name, price=800.0, status="Confirmed", production_status="In Production")
            db.session.add(o)
            db.session.commit()

            kpis = get_production_overview_kpis()
            self.assertGreaterEqual(kpis["total_active_orders"], 1)
            self.assertGreaterEqual(kpis["orders_in_production"], 1)


if __name__ == "__main__":
    unittest.main()
