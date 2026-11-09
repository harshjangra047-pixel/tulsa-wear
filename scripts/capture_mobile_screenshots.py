import os
import sys
import time
import subprocess
import urllib.request
import signal

ARTIFACT_DIR = "/Users/harsh/.gemini/antigravity/brain/6f45e6e5-340e-4015-a793-ed1cfb35780f/mobile_screenshots"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

PORT = 5005
BASE_URL = f"http://127.0.0.1:{PORT}"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

env = os.environ.copy()
env["DATABASE_URL"] = "sqlite:////tmp/tulsa_stage9_test.db"
env["FLASK_ENV"] = "testing"
env["PORT"] = str(PORT)

# Start test server process
server = subprocess.Popen(
    [sys.executable, "-c", f"""
import os, sys
os.environ['DATABASE_URL'] = 'sqlite:////tmp/tulsa_stage9_test.db'
os.environ['FLASK_ENV'] = 'testing'
from app import app, db
from models.product import Product
with app.app_context():
    db.create_all()
    p = Product.query.get(9999)
    if not p:
        p = Product(id=9999, name="Heritage Emerald Silk Anarkali", description="Pure handloom Chanderi silk with antique zardozi embroidery and flowing silhouette.", price=2499.0, original_price=2999.0, category="Anarkali", fabric="Chanderi Silk", color="Emerald Green", image="garment-01.jpg", additional_images="garment-09.jpg,garment-11.jpg", stock=15, best_seller=True)
        db.session.add(p)
    else:
        p.image = "garment-01.jpg"
        p.additional_images = "garment-09.jpg,garment-11.jpg"
        p.stock = 15
    db.session.commit()
app.run(host='127.0.0.1', port={PORT}, debug=False)
"""],
    env=env
)

print(f"Waiting for test server on {BASE_URL}...")
for _ in range(30):
    try:
        with urllib.request.urlopen(f"{BASE_URL}/", timeout=1) as resp:
            if resp.status == 200:
                print("Server is ready!")
                break
    except Exception:
        time.sleep(0.3)
else:
    print("Server failed to respond in time.")
    server.terminate()
    sys.exit(1)

tasks = [
    ("mobile_android_360x800_home.png", f"{BASE_URL}/", 360, 800),
    ("mobile_android_360x800_shop.png", f"{BASE_URL}/shop", 360, 800),
    ("mobile_android_360x800_pdp.png", f"{BASE_URL}/product/9999", 360, 800),
    ("mobile_iphone_375x812_pdp.png", f"{BASE_URL}/product/9999", 375, 812),
    ("mobile_iphone_390x844_pdp.png", f"{BASE_URL}/product/9999", 390, 844),
    ("mobile_iphone_430x932_pdp.png", f"{BASE_URL}/product/9999", 430, 932),
    ("desktop_1280x800_home.png", f"{BASE_URL}/", 1280, 800),
    ("desktop_1280x800_pdp.png", f"{BASE_URL}/product/9999", 1280, 800),
]

try:
    for filename, url, width, height in tasks:
        output_path = os.path.join(ARTIFACT_DIR, filename)
        cmd = [
            CHROME_BIN,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--window-size={width},{height}",
            f"--screenshot={output_path}",
            url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"Captured: {filename} ({width}x{height}, {os.path.getsize(output_path):,} bytes)")
        else:
            print(f"Failed to capture {filename}: {res.stderr}")
finally:
    server.terminate()
    try:
        server.wait(timeout=2)
    except Exception:
        server.kill()
    print("Test server stopped.")
