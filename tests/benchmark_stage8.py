import os
import sys
import time

os.environ['DATABASE_URL'] = 'sqlite:////tmp/tulsa_stage8_test.db'
os.environ['TESTING'] = '1'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app

client = app.app.test_client()

routes = [
    ('/', 'Homepage'),
    ('/shop', 'Shop'),
    ('/fitting-room', 'Fitting Room'),
    ('/bag', 'Shopping Bag'),
    ('/admin/login', 'Admin Login'),
]

print("=== BASELINE PERFORMANCE MEASUREMENTS ===")
for path, label in routes:
    start = time.perf_counter()
    resp = client.get(path)
    elapsed = (time.perf_counter() - start) * 1000.0
    size_kb = len(resp.data) / 1024.0
    print(f"{label:20} ({path:15}): Status {resp.status_code} | Time: {elapsed:6.2f} ms | Size: {size_kb:6.2f} KB")

# Test static assets size
static_assets = [
    '/static/css/atelier-3d.css',
    '/static/css/style.css',
    '/static/js/main.js',
    '/static/js/stage4-atelier.js',
    '/static/js/look-builder.js',
    '/static/js/curved-carousel.js',
]
print("\n=== STATIC BUNDLE SIZES ===")
total_static = 0
for asset in static_assets:
    resp = client.get(asset)
    size_kb = len(resp.data) / 1024.0
    total_static += size_kb
    print(f"{asset:35}: Status {resp.status_code} | Size: {size_kb:6.2f} KB")
print(f"Total Static JS/CSS: {total_static:.2f} KB")

