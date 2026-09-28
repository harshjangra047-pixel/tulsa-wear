from app import app
from models.database import db
from models.product import Product
from models.feedback import Feedback
from models.custom_order import CustomOrder

product_catalog = [
    {
        "name": "Handcrafted Cotton Stole",
        "price": 950.0,
        "category": "Plazo / Kurta",
        "fabric": "Organic Cotton",
        "color": "Off-White",
        "description": "Delicate handmade cotton stole with hand-spun threads and hand-hemmed borders.",
        "image": "product-1.jpg",
        "stock": 15,
        "best_seller": True
    },
    {
        "name": "Everyday Artisan Kurti",
        "price": 1650.0,
        "category": "Plazo / Kurta",
        "fabric": "Pure Cotton",
        "color": "Indigo",
        "description": "Minimal everyday hand-stitched kurti designed for airy comfort and effortless luxury.",
        "image": "product-2.jpg",
        "stock": 12,
        "best_seller": False
    },
    {
        "name": "Hand Embroidered Kurta",
        "price": 2800.0,
        "category": "Plazo / Kurta",
        "fabric": "Mulmul Cotton",
        "color": "Beige",
        "description": "A signature handcrafted kurta featuring delicate tonal embroidery along the neckline.",
        "image": "product-1.jpg",
        "stock": 10,
        "best_seller": True
    },
    {
        "name": "Artisan Plazo Set",
        "price": 3600.0,
        "category": "Plazo / Kurta",
        "fabric": "Linen Blend",
        "color": "Ivory",
        "description": "A relaxed-silhouette handmade plazo set with fine hand-tuck detailing.",
        "image": "product-2.jpg",
        "stock": 8,
        "best_seller": True
    },
    {
        "name": "Heritage Salwar Kameez",
        "price": 3900.0,
        "category": "Salwar Kameez",
        "fabric": "Chanderi Cotton",
        "color": "Dusty Rose",
        "description": "A classic three-piece salwar kameez finished with handcrafted artisanal borders.",
        "image": "product-3.jpg",
        "stock": 6,
        "best_seller": True
    },
    {
        "name": "Festive Embroidered Suit",
        "price": 4200.0,
        "category": "Salwar Kameez",
        "fabric": "Chanderi Silk",
        "color": "Sage Green",
        "description": "Soft chanderi suit adorned with subtle handmade motifs and fine zardozi touches.",
        "image": "product-1.jpg",
        "stock": 7,
        "best_seller": False
    },
    {
        "name": "Embroidered Party Dress",
        "price": 4800.0,
        "category": "Party Wear",
        "fabric": "Silk Blend",
        "color": "Noir Black",
        "description": "An evening statement piece crafted with hand-placed tonal beads and delicate stitching.",
        "image": "product-3.jpg",
        "stock": 5,
        "best_seller": False
    },
    {
        "name": "Royal Wedding Handwork Set",
        "price": 7200.0,
        "category": "Wedding Wear",
        "fabric": "Pure Raw Silk",
        "color": "Antique Gold",
        "description": "An opulent wedding ensemble adorned with traditional needlework, designed for grand celebrations.",
        "image": "product-2.jpg",
        "stock": 4,
        "best_seller": False
    }
]

def seed_database():
    with app.app_context():
        added_count = 0
        updated_count = 0

        for item in product_catalog:
            existing = Product.query.filter_by(name=item["name"]).first()
            if not existing:
                new_product = Product(
                    name=item["name"],
                    price=item["price"],
                    category=item["category"],
                    fabric=item["fabric"],
                    color=item["color"],
                    description=item["description"],
                    image=item["image"],
                    stock=item["stock"],
                    best_seller=item["best_seller"]
                )
                db.session.add(new_product)
                added_count += 1
            else:
                existing.price = item["price"]
                existing.category = item["category"]
                existing.fabric = item["fabric"]
                existing.color = item["color"]
                existing.description = item["description"]
                existing.image = item["image"]
                existing.stock = item["stock"]
                existing.best_seller = item["best_seller"]
                updated_count += 1

        # Seed sample approved reviews if none exist
        if Feedback.query.count() == 0:
            sample_reviews = [
                Feedback(
                    customer_name="Ananya Sharma",
                    email="ananya.sharma@example.com",
                    rating=5,
                    message="The attention to detail and hand-finished hems are truly remarkable. The organic cotton drape feels extraordinary in summer.",
                    is_approved=True
                ),
                Feedback(
                    customer_name="Meera Kapoor",
                    email="meera.k@example.com",
                    rating=5,
                    message="The experience felt personal from beginning to end. It is rare to find such authentic hand-needle embroidery and gentle tailoring.",
                    is_approved=True
                ),
                Feedback(
                    customer_name="Radhika Verma",
                    email="radhika.v@example.com",
                    rating=5,
                    message="Beautiful craftsmanship and timeless silhouettes. An heirloom investment piece that will last for years.",
                    is_approved=True
                ),
            ]
            db.session.add_all(sample_reviews)
            print("Seeded 3 approved atelier testimonials.")

        # Seed sample custom order inquiry if none exist
        if CustomOrder.query.count() == 0:
            sample_inquiry = CustomOrder(
                customer_name="Pooja Mehta",
                phone="+91 98765 43210",
                email="pooja.mehta@example.com",
                outfit_type="Wedding Ensemble",
                fabric_preference="Chanderi Silk with Raw Silk Dupatta",
                color_preference="Sage Green & Antique Gold",
                occasion="Sister's Wedding",
                measurements="Bust: 36, Waist: 30, Hip: 40, Kurta Length: 46",
                notes="Delicate zardozi threadwork along the neckline and cuffs. Minimal glitter, matte gold needlework preferred.",
                status="Inquiry Received"
            )
            db.session.add(sample_inquiry)
            print("Seeded 1 sample bespoke inquiry for admin preview.")

        db.session.commit()
        print(f"Database seed complete! Added {added_count} new product(s), updated {updated_count} product(s).")

if __name__ == "__main__":
    seed_database()
