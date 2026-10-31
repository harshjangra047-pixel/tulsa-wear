"""Comprehensive test suite for Tulsa Wears Admin and Storefront Gallery Integration."""

import os
import io
import sys
import json
import subprocess
from PIL import Image

# Ensure environment
os.environ["FLASK_ENV"] = "testing"
from dotenv import load_dotenv
load_dotenv("/Users/harsh/Documents/tulsa-wear.handmade/.env")

db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url and db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
os.environ["DATABASE_URL"] = db_url

# Clean up any leftover test product from earlier
from sqlalchemy import create_engine, text
engine = create_engine(db_url)
with engine.connect() as conn:
    conn.execute(text("DELETE FROM products WHERE name LIKE 'TEST Garment%';"))
    conn.commit()


def create_test_image(color, label):
    """Generate distinct image bytes in memory."""
    img = Image.new("RGB", (300, 400), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    buf.name = f"{label}.jpg"
    return buf


def run_admin_flow():
    """Run all Admin actions using Admin app context."""
    sys.path.insert(0, "/Users/harsh/Projects/tulsa-admin-gallery-clean")
    import app as admin_module

    admin_app = admin_module.app
    admin_app.config["TESTING"] = True
    admin_app.config["SECRET_KEY"] = "test_secret_admin_key"
    client = admin_app.test_client()

    with client.session_transaction() as sess:
        sess["admin_authenticated"] = True
        sess["admin_user"] = "admin"
        sess["csrf_token"] = "test_csrf_token_123"

        with admin_app.app_context():
            admin = admin_module.AdminUser.query.filter_by(username="admin").first()
            if not admin:
                admin = admin_module.AdminUser(username="admin", email="admin@tulsawears.com")
                admin.set_password("atelier-password")
                admin_module.db.session.add(admin)
                admin_module.db.session.commit()
            sess["admin_auth_version"] = admin_module.admin_password_fingerprint(admin)

    # 1. Test A: Create Product A (1 photo)
    print("\n--- Running Test A in Admin: 1-photo workflow ---")
    res_a = client.post(
        "/products/add",
        data={
            "name": "TEST Garment Single Photo",
            "price": "4500",
            "category": "Salwar Kameez",
            "fabric": "Chanderi Silk",
            "color": "Royal Crimson",
            "stock": "8",
            "description": "Master test item single photo",
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
    )
    assert res_a.status_code == 200, f"Create A failed: {res_a.data}"
    prod_a_id = res_a.get_json()["product_id"]

    img_a = create_test_image((180, 40, 40), "garment_a_1")
    up_a = client.post(
        f"/products/{prod_a_id}/gallery-upload",
        data={"image": (img_a, "photo_1.jpg")},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "X-CSRF-Token": "test_csrf_token_123",
            "X-Original-Size": str(len(img_a.getvalue()))
        },
        content_type="multipart/form-data"
    )
    assert up_a.status_code == 200, f"Upload A failed: {up_a.data}"
    photo_a_url = up_a.get_json()["url"]
    print(f"Product A ({prod_a_id}) photo uploaded: {photo_a_url}")

    # 2. Test B: Create Product B (5 distinct photos)
    print("\n--- Running Test B in Admin: 5-photo workflow ---")
    res_b = client.post(
        "/products/add",
        data={
            "name": "TEST Garment Five Photos Edit",
            "price": "6800",
            "category": "Plazo / Kurta",
            "fabric": "Mulmul Cotton",
            "color": "Ochre & Gold",
            "stock": "15",
            "description": "Master test item with full 5-photo gallery",
        },
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
    )
    assert res_b.status_code == 200, f"Create B failed: {res_b.data}"
    prod_b_id = res_b.get_json()["product_id"]

    test_colors = [
        ((220, 50, 50), "photo_1"),
        ((50, 180, 50), "photo_2"),
        ((50, 50, 220), "photo_3"),
        ((220, 180, 50), "photo_4"),
        ((180, 50, 220), "photo_5")
    ]
    uploaded_urls_b = []
    for idx, (color, label) in enumerate(test_colors):
        buf = create_test_image(color, label)
        up_b = client.post(
            f"/products/{prod_b_id}/gallery-upload",
            data={"image": (buf, f"{label}.jpg")},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                "X-CSRF-Token": "test_csrf_token_123",
                "X-Original-Size": str(len(buf.getvalue()))
            },
            content_type="multipart/form-data"
        )
        assert up_b.status_code == 200, f"Photo {idx+1} failed: {up_b.data}"
        json_b = up_b.get_json()
        assert json_b["sort_order"] == idx
        uploaded_urls_b.append(json_b["url"])
        print(f"Product B ({prod_b_id}) photo {idx+1} uploaded: {json_b['url']} (sort_order={idx})")

    # 3. Test C: Validation & Constraints
    print("\n--- Running Test C in Admin: Validation & Constraints ---")
    # Unsupported file extension
    fake_txt = io.BytesIO(b"Not an image")
    fake_txt.name = "malicious.txt"
    bad_ext = client.post(
        f"/products/{prod_b_id}/gallery-upload",
        data={"image": (fake_txt, "malicious.txt")},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json", "X-CSRF-Token": "test_csrf_token_123"},
        content_type="multipart/form-data"
    )
    assert bad_ext.status_code == 400
    print("Rejected invalid extension cleanly.")

    # Exceeding 5 photos
    extra_img = create_test_image((10, 10, 10), "photo_6")
    exceed = client.post(
        f"/products/{prod_b_id}/gallery-upload",
        data={"image": (extra_img, "photo_6.jpg")},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json", "X-CSRF-Token": "test_csrf_token_123"},
        content_type="multipart/form-data"
    )
    assert exceed.status_code == 400
    print("Rejected 6th photo (maximum 5 enforced).")

    # Unauthenticated / expired AJAX returns 401
    unauth_client = admin_app.test_client()
    unauth_resp = unauth_client.post(
        f"/products/{prod_b_id}/gallery-upload",
        data={"image": (create_test_image((20, 20, 20), "unauth_photo"), "photo.jpg")},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        content_type="multipart/form-data"
    )
    assert unauth_resp.status_code == 401
    print("Unauthenticated AJAX returned 401 JSON.")

    return prod_a_id, photo_a_url, prod_b_id, uploaded_urls_b


def verify_storefront(prod_a_id, photo_a_url, prod_b_id, uploaded_urls_b):
    """Run storefront verifications in an isolated subprocess."""
    script = f"""
import os, sys
os.environ["FLASK_ENV"] = "testing"
from dotenv import load_dotenv
load_dotenv("/Users/harsh/Documents/tulsa-wear.handmade/.env")

db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url and db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
os.environ["DATABASE_URL"] = db_url

sys.path.insert(0, "/Users/harsh/Projects/tulsa-wear-recovery")
import app as sf_module

app = sf_module.app
app.config["TESTING"] = True
client = app.test_client()

# Check Product A Detail
res_a = client.get("/product/{prod_a_id}")
assert res_a.status_code == 200, f"Storefront detail A failed: {{res_a.status_code}}"
html_a = res_a.get_data(as_text=True)
assert "{photo_a_url}" in html_a, "Photo A missing from product detail"
print("Storefront verified Product A detail page!")

# Check Product B Detail (all 5 photos)
res_b = client.get("/product/{prod_b_id}")
assert res_b.status_code == 200, f"Storefront detail B failed: {{res_b.status_code}}"
html_b = res_b.get_data(as_text=True)
for u in {json.dumps(uploaded_urls_b)}:
    assert u in html_b, f"Photo URL {{u}} missing from Product B gallery"
print("Storefront verified Product B detail page with all 5 photos!")

# Check Shop catalog has primary photo of Product B
res_shop = client.get("/shop")
assert res_shop.status_code == 200, f"Storefront shop failed: {{res_shop.status_code}}"
html_shop = res_shop.get_data(as_text=True)
assert "{uploaded_urls_b[0]}" in html_shop, "Primary cover photo of Product B missing from shop catalog"
print("Storefront verified Shop catalog display!")
"""
    cmd = [
        "/Users/harsh/.gemini/antigravity-ide/brain/46ed46cb-b711-45ef-a39c-ef54a2d0afe3/scratch/venv/bin/python3",
        "-c",
        script
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Storefront verification FAILED:")
        print(res.stdout)
        print(res.stderr)
        assert False, "Storefront verification failed"
    else:
        print(res.stdout)


if __name__ == "__main__":
    prod_a_id, photo_a_url, prod_b_id, uploaded_urls_b = run_admin_flow()
    print("\n--- Running Storefront Verifications ---")
    verify_storefront(prod_a_id, photo_a_url, prod_b_id, uploaded_urls_b)

    # Clean up test products
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM products WHERE name LIKE 'TEST Garment%';"))
        conn.commit()
    print("Cleaned up test products from database.")
    print("\n*** ALL INTEGRATION TESTS PASSED 100% ***\n")
