import os
import sys

# Ensure isolated test database
os.environ['DATABASE_URL'] = 'sqlite:////tmp/tulsa_stage8_test.db'
os.environ['TESTING'] = '1'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app
from models.database import db
from models.admin_user import AdminUser
from models.customer_user import CustomerUser
from models.customer_address import CustomerAddress
from models.product import Product
from models.order import Order
from models.site_content import SiteContent

with app.app.app_context():
    db.create_all()

    # Seed Admin
    if not AdminUser.query.filter_by(username="admin").first():
        admin = AdminUser(username="admin")
        admin.set_password("admin123")
        admin.studio_phone = "+91 93504 39667"
        admin.studio_whatsapp = "919350439667"
        admin.studio_email = "contact@tulsawear.com"
        db.session.add(admin)

    # Seed Customer
    customer = CustomerUser.query.filter_by(phone="+919876543210").first()
    if not customer:
        customer = CustomerUser(
            name="Aarav Sharma",
            phone="+919876543210",
            email="aarav@example.com",
            address="42 Gulmohar Lane, Sector 14",
            city="Gurugram",
            pincode="122001"
        )
        customer.set_password("Customer@123")
        db.session.add(customer)
        db.session.flush()

        # Seed Address
        addr = CustomerAddress(
            customer_id=customer.id,
            label="Home",
            recipient_name="Aarav Sharma",
            phone="+919876543210",
            address="42 Gulmohar Lane, Sector 14",
            city="Gurugram",
            pincode="122001"
        )
        db.session.add(addr)

    # Seed Products if empty
    if Product.query.count() == 0:
        names = [
            ("Noor Anarkali", 18500, "Palazzo Set", "garment-01.jpg", True),
            ("Zehra Sharara", 22000, "Salwar Kameez", "garment-02.jpg", True),
            ("Mehrunissa Kurta", 14500, "Casual Wear", "garment-03.jpg", False),
            ("Sitara Lehenga", 34000, "Party / Wedding Regalia", "garment-04.jpg", True),
            ("Gulzar Velvet Set", 26000, "Party / Wedding Regalia", "garment-05.jpg", True),
            ("Chanderi Dawn Suit", 16500, "Salwar Kameez", "garment-06.jpg", False),
        ]
        for name, price, cat, img, best in names:
            p = Product(
                name=name,
                price=price,
                category=cat,
                image=img,
                best_seller=best,
                description=f"Handcrafted {name} created with artisanal silk and zari embroidery.",
                fabric="Pure Mulberry Silk",
                color="Emerald Green",
                stock=15
            )
            db.session.add(p)
        db.session.flush()

    # Seed Order
    if Order.query.count() == 0:
        p = Product.query.first()
        ord1 = Order(
            product_id=p.id if p else 1,
            product_name=p.name if p else "Noor Anarkali",
            price=p.price if p else 18500,
            customer_name="Aarav Sharma",
            phone="+919876543210",
            email="aarav@example.com",
            address="42 Gulmohar Lane, Sector 14",
            city="Gurugram",
            pincode="122001",
            status="Confirmed",
            payment_status="Paid",
            size="M",
            customer_id=customer.id
        )
        db.session.add(ord1)

    db.session.commit()
    print("Test database seeded with synthetic records.")
