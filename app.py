import os
import functools
import uuid
import time
import secrets
import re
import io
import csv
import json
import hmac
import hashlib

import razorpay

from dotenv import load_dotenv

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    url_for,
    session,
    redirect,
    flash,
    Response,
    send_file,
    g
)

from datetime import datetime, timedelta
from sqlalchemy import inspect, text

from models.database import db
from models.product import Product
from models.product_image import ProductImage
from models.order import Order
from models.feedback import Feedback
from models.custom_order import CustomOrder
from models.admin_user import AdminUser
from models.trend_upload import TrendUpload
from models.contact_inquiry import ContactInquiry
from models.coupon import Coupon
from models.customer_user import CustomerUser
from models.site_content import SiteContent, SiteContentRevision
from models.customer_address import CustomerAddress
from models.editor_preview_token import EditorPreviewToken
from models.traffic_log import TrafficLog
from services.ai_stylist import ask_ai_stylist, ask_ai_about_product
from services.site_content import (
    get_site_content,
    save_site_content,
    reset_site_content,
    process_image_upload,
    publish_site_content,
    validate_editor_layout,
    validate_editor_theme
)
from services.private_storage import read_payment_proof, upload_payment_proof
from services.checkout_calculator import calculate_bag_and_checkout, to_paise, to_rupees
from services.shipping_service import get_shipping_quote, get_order_package_specs, DEFAULT_WAREHOUSE
from services.payment_service import (
    get_razorpay_credentials,
    get_razorpay_client,
    create_razorpay_order,
    verify_razorpay_signature,
    verify_webhook_signature,
    capture_order_payment,
    process_webhook_payload,
    process_order_refund,
    fetch_payment_details
)
import urllib.parse
import random
try:
    import qrcode
except ImportError:
    qrcode = None


# =========================================
# LOAD ENVIRONMENT VARIABLES
# =========================================

load_dotenv()
PRODUCTION_RUNTIME = os.getenv("FLASK_ENV") == "production" or os.getenv("VERCEL") == "1"


# =========================================
# FLASK APP & SECURITY CONFIGURATION
# =========================================

app = Flask(__name__)


@app.template_global()
def product_image_url(image, fallback="editorial-hero.jpg"):
    """
    Supports:
    - existing local image filenames
    - absolute Vercel Blob URLs uploaded by the Admin Portal
    """
    if image:
        image = str(image).strip()
        if image.startswith(("http://", "https://")):
            return image
        return url_for("static", filename=f"images/{image}")

    return url_for("static", filename=f"images/{fallback}")


@app.template_global()
def is_category_active(cat_pill, selected_cat):
    """Template helper to check if a category pill is active."""
    from services.category_service import is_category_active as ica
    return ica(cat_pill, selected_cat)


# Persistent High-Entropy Cryptographic Session Key
SECRET_KEY_FILE = os.path.join(app.root_path, ".session_secret")
if os.getenv("FLASK_SECRET_KEY"):
    app.secret_key = os.getenv("FLASK_SECRET_KEY")
elif PRODUCTION_RUNTIME:
    raise RuntimeError("FLASK_SECRET_KEY must be configured in production")
elif os.path.exists(SECRET_KEY_FILE):
    try:
        with open(SECRET_KEY_FILE, "r") as f:
            app.secret_key = f.read().strip()
    except Exception:
        app.secret_key = secrets.token_hex(32)
else:
    new_key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, "w") as f:
            f.write(new_key)
    except Exception:
        pass
    app.secret_key = new_key

# High security session cookie attributes:
# 1. Blocks client-side scripts from reading session cookies (XSS mitigation)
app.config["SESSION_COOKIE_HTTPONLY"] = True

# 2. Helps protect against Cross-Site Request Forgery (CSRF)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# 3. Secure cookies when running under HTTPS in production
app.config["SESSION_COOKIE_SECURE"] = PRODUCTION_RUNTIME
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Media upload configuration
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "avif"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def is_valid_image_file(file_storage):
    """
    Validates uploaded file binary headers using PIL to ensure genuine, non-malicious image content.
    Resets stream pointer afterwards.
    """
    if not file_storage or not file_storage.filename:
        return False
    try:
        pos = file_storage.stream.tell()
        img = Image.open(file_storage.stream)
        img.verify()
        file_storage.stream.seek(pos)
        return True
    except Exception:
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
        return False

def validate_indian_phone(phone_str):
    """
    Validates genuine Indian 10-digit mobile number format (6-9 followed by 9 digits).
    Cleans out country codes (+91, 91), spaces, dashes, parentheses, and leading 0s.
    Returns (is_valid: bool, cleaned_10_digits: str)
    """
    if not phone_str:
        return False, ""
    cleaned = re.sub(r"\D", "", str(phone_str))
    if len(cleaned) == 11 and cleaned.startswith("0"):
        cleaned = cleaned[1:]
    elif len(cleaned) == 12 and cleaned.startswith("91"):
        cleaned = cleaned[2:]
    elif len(cleaned) == 13 and cleaned.startswith("091"):
        cleaned = cleaned[3:]

    if re.match(r"^[6-9]\d{9}$", cleaned):
        return True, cleaned
    return False, cleaned

def validate_utr(utr_str):
    """
    Validates UPI UTR / Transaction Reference ID:
    - Min 8, max 30 alphanumeric characters
    - Must not be dummy placeholders
    """
    if not utr_str:
        return False
    cleaned = re.sub(r"\s+", "", str(utr_str)).upper()
    if len(cleaned) < 8 or len(cleaned) > 30:
        return False
    if not re.match(r"^[A-Z0-9]+$", cleaned):
        return False
    dummy_patterns = ["TEST", "DUMMY", "FAKE", "12345678", "00000000", "SAMPLE", "NULL", "NONE"]
    if any(cleaned == p or cleaned.startswith("TEST") for p in dummy_patterns):
        return False
    return True


def get_merchant_upi_config():
    """Retrieve trusted merchant UPI ID and payee name from admin settings or environment variables."""
    admin_cfg = AdminUser.query.first()
    upi_id = ""
    if admin_cfg and admin_cfg.upi_id:
        upi_id = admin_cfg.upi_id.strip()
    if not upi_id:
        upi_id = os.getenv("MERCHANT_UPI_ID", "9350439667@okbizaxis").strip()

    payee_name = ""
    if admin_cfg and admin_cfg.upi_payee_name:
        payee_name = admin_cfg.upi_payee_name.strip()
    if not payee_name:
        payee_name = os.getenv("MERCHANT_NAME", "Tulsa Wears").strip()

    return upi_id, payee_name


# Admin Anti-Brute-Force Rate Limiting Store
FAILED_ADMIN_LOGINS = {}  # ip -> {"count": int, "lockout_until": float}
_STUDIO_CACHE = {"data": None, "ts": 0.0}
ASSET_VERSION = os.environ.get("ASSET_VERSION", "2026.8.1")

# Production HTTP Security & Caching Headers
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif getattr(g, "editor_preview", False):
        response.headers.pop("X-Frame-Options", None)
        response.headers["Cache-Control"] = "no-store"
    elif request.method == "GET" and not session.get("customer_id") and not session.get("admin_authenticated"):
        if request.path in ["/", "/shop", "/fitting-room", "/robots.txt", "/sitemap.xml"]:
            response.headers["Cache-Control"] = "public, max-age=120, s-maxage=600, stale-while-revalidate=120"
    return response

@app.context_processor
def inject_global_vars():
    preview_token = request.args.get("editor_preview", "")
    preview_record = None
    if preview_token:
        preview_record = EditorPreviewToken.query.filter_by(
            token_hash=hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
        ).first()
    token_preview = bool(preview_record and preview_record.expires_at > datetime.utcnow())
    is_admin_draft_preview = (request.path == "/" and request.args.get("preview") == "1" and session.get("admin_authenticated")) or token_preview
    g.editor_preview = bool(is_admin_draft_preview)
    cms = get_site_content(preview_draft=bool(is_admin_draft_preview))
    theme = cms.get("editor_theme", {})
    cms["editor_theme"] = validate_editor_theme(
        theme.get("accent"), theme.get("background"), theme.get("heading_font"), theme.get("section_spacing")
    )
    layout = validate_editor_layout(json.dumps(cms.get("editor_sections", [])), json.dumps(cms.get("custom_sections", [])))
    if layout:
        cms["editor_sections"], cms["custom_sections"] = layout

    now_ts = time.time()
    if not is_admin_draft_preview and _STUDIO_CACHE["data"] and (now_ts - _STUDIO_CACHE["ts"] < 30.0):
        delivery_days, phone, whatsapp, email, address, hours = _STUDIO_CACHE["data"]
    else:
        try:
            admin_user = AdminUser.query.first()
            delivery_days = admin_user.default_delivery_days if admin_user else 10
            phone = (admin_user.studio_phone if admin_user and getattr(admin_user, 'studio_phone', None) else cms.get("studio_phone", "+91 93504 39667"))
            whatsapp = (admin_user.studio_whatsapp if admin_user and getattr(admin_user, 'studio_whatsapp', None) else cms.get("studio_whatsapp", "919350439667"))
            email = (admin_user.studio_email if admin_user and getattr(admin_user, 'studio_email', None) else cms.get("studio_email", "contact@tulsawear.com"))
            address = (admin_user.studio_address if admin_user and getattr(admin_user, 'studio_address', None) else cms.get("studio_address", "Tulsa Wears Atelier, Hansi, Haryana, India - 125033"))
            hours = (admin_user.studio_hours if admin_user and getattr(admin_user, 'studio_hours', None) else cms.get("studio_hours", "Mon – Sat: 10:00 AM – 7:00 PM IST"))
        except Exception:
            delivery_days = 10
            phone = cms.get("studio_phone", "+91 93504 39667")
            whatsapp = cms.get("studio_whatsapp", "919350439667")
            email = cms.get("studio_email", "contact@tulsawear.com")
            address = cms.get("studio_address", "Tulsa Wears Atelier, Hansi, Haryana, India - 125033")
            hours = cms.get("studio_hours", "Mon – Sat: 10:00 AM – 7:00 PM IST")
        if not is_admin_draft_preview:
            _STUDIO_CACHE["data"] = (delivery_days, phone, whatsapp, email, address, hours)
            _STUDIO_CACHE["ts"] = now_ts

    current_customer = None
    customer_id = session.get("customer_id")
    if customer_id:
        try:
            current_customer = CustomerUser.query.get(customer_id)
        except Exception:
            current_customer = None

    return dict(
        cache_id=ASSET_VERSION,
        cms=cms,
        brand_name=cms.get("brand_name", "Tulsa by Anjali"),
        brand_tagline=cms.get("brand_tagline", "Handcrafted Slow Fashion • By Anjali"),
        brand_logo=cms.get("brand_logo", "tulsa-brand-logo.png"),
        instagram_handle_1=cms.get("instagram_handle_1", "__aannuuu.06"),
        instagram_handle_2=cms.get("instagram_handle_2", "tulsawear"),
        default_delivery_days=delivery_days,
        studio_phone=phone,
        studio_whatsapp=whatsapp,
        studio_email=email,
        studio_address=address,
        studio_hours=hours,
        current_customer=current_customer,
        editor_preview=bool(is_admin_draft_preview),
        csrf_token=session.setdefault("csrf_token", secrets.token_urlsafe(32))
    )


# =========================================
# DATABASE SETUP
# =========================================

BASE_DIR = os.path.abspath(
    os.path.dirname(__file__)
)

# Use hosted PostgreSQL on Vercel; keep SQLite as the local fallback.
DATABASE_URL = os.getenv("DATABASE_URL")
if PRODUCTION_RUNTIME and not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must point to the shared persistent database in production")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    DATABASE_PATH = os.path.join(
        BASE_DIR,
        "database",
        "fashion.db"
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DATABASE_PATH

app.config[
    "SQLALCHEMY_TRACK_MODIFICATIONS"
] = False

db.init_app(app)


# =========================================
# RAZORPAY SETUP
# =========================================

RAZORPAY_KEY_ID = os.getenv(
    "RAZORPAY_KEY_ID"
)

RAZORPAY_KEY_SECRET = os.getenv(
    "RAZORPAY_KEY_SECRET"
)


razorpay_client = get_razorpay_client()


# =========================================
# DATABASE MIGRATION
# =========================================

def ensure_schema_migrations():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if "orders" in tables:
        existing_order_cols = {
            column["name"]
            for column in inspector.get_columns("orders")
        }

        new_order_cols = {
            "razorpay_order_id": "VARCHAR(100)",
            "razorpay_payment_id": "VARCHAR(100)",
            "payment_method": "VARCHAR(50)",
            "tracking_id": "VARCHAR(100)",
            "size": "VARCHAR(20)",
            "top_length": "VARCHAR(50)",
            "sleeves_length": "VARCHAR(50)",
            "bust": "VARCHAR(50)",
            "waist": "VARCHAR(50)",
            "hip": "VARCHAR(50)",
            "shoulder": "VARCHAR(50)",
            "advance_paid": "FLOAT DEFAULT 0.0",
            "balance_due": "FLOAT DEFAULT 0.0",
            "estimated_delivery_days": "INTEGER DEFAULT 10",
            "estimated_delivery_date": "VARCHAR(100)",
            "upi_utr": "VARCHAR(100)",
            "payment_screenshot": "VARCHAR(255)",
            "customer_id": "INTEGER",
            "coupon_code": "VARCHAR(50)",
            "discount_amount": "FLOAT DEFAULT 0.0",
            "shipping_fee": "FLOAT DEFAULT 0.0",
            "shipping_provider": "VARCHAR(100)",
            "shipping_service": "VARCHAR(100)",
            "manual_payment_verified_by": "VARCHAR(80)",
            "manual_payment_verified_at": "TIMESTAMP",
            "whatsapp_opt_in": "BOOLEAN DEFAULT FALSE",
            "whatsapp_opt_in_at": "TIMESTAMP",
            "whatsapp_opt_in_source": "VARCHAR(50)",
            "whatsapp_notification_status": "VARCHAR(50) DEFAULT 'Not opted in'",
            "email_notification_status": "VARCHAR(50) DEFAULT 'Pending'",
            "order_items_data": "TEXT",
            "delivery_window_start": "VARCHAR(100)",
            "delivery_window_end": "VARCHAR(100)",
            "production_status": "VARCHAR(50) DEFAULT 'Pending'",
            "dispatch_status": "VARCHAR(50) DEFAULT 'Awaiting Production'",
            "dispatch_date": "TIMESTAMP",
            "dispatched_courier": "VARCHAR(100)",
            "cost_price": "FLOAT DEFAULT 0.0",
            "payment_status": "VARCHAR(50) DEFAULT 'Pending'",
            "razorpay_signature": "VARCHAR(255)",
            "payment_currency": "VARCHAR(10) DEFAULT 'INR'",
            "payment_captured_at": "TIMESTAMP",
            "refund_id": "VARCHAR(100)",
            "refund_status": "VARCHAR(50)",
            "refund_amount": "FLOAT DEFAULT 0.0",
            "webhook_event_id": "VARCHAR(100)",
            "payment_error_code": "VARCHAR(100)",
            "payment_error_desc": "TEXT",
            "payment_device": "VARCHAR(50)",
            "payment_environment": "VARCHAR(20)",
            "is_archived": "BOOLEAN DEFAULT FALSE",
            "archived_at": "TIMESTAMP",
            "archived_by": "VARCHAR(100)",
            "archived_reason": "VARCHAR(255)"
        }

        with db.engine.begin() as connection:
            for column_name, column_type in new_order_cols.items():
                if column_name not in existing_order_cols:
                    connection.execute(
                        text(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")
                    )

    if "products" in tables:
        existing_prod_cols = {
            column["name"]
            for column in inspector.get_columns("products")
        }
        new_prod_cols = {
            "weight_kg": "FLOAT DEFAULT 0.5",
            "length_cm": "FLOAT DEFAULT 30.0",
            "width_cm": "FLOAT DEFAULT 25.0",
            "height_cm": "FLOAT DEFAULT 5.0",
            "original_price": "FLOAT",
            "discount_percent": "INTEGER",
            "category_2": "VARCHAR(100)",
            "category_3": "VARCHAR(100)",
            "category_4": "VARCHAR(100)",
            "sku": "VARCHAR(50)",
            "cost_price": "FLOAT DEFAULT 0.0"
        }
        with db.engine.begin() as connection:
            for col_name, col_type in new_prod_cols.items():
                if col_name not in existing_prod_cols:
                    connection.execute(
                        text(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
                    )

    if "custom_orders" in tables:
        existing_co_cols = {
            column["name"]
            for column in inspector.get_columns("custom_orders")
        }
        if "reference_image" not in existing_co_cols:
            with db.engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE custom_orders ADD COLUMN reference_image VARCHAR(255)")
                )

    # Initialize AdminUser and add missing columns
    if "admin_users" in tables:
        existing_admin_cols = {
            column["name"]
            for column in inspector.get_columns("admin_users")
        }
        admin_cols = {
            "upi_id": "VARCHAR(100) DEFAULT ''",
            "upi_payee_name": "VARCHAR(100) DEFAULT 'Tulsa Wears'",
            "razorpay_key_id": "VARCHAR(100) DEFAULT ''",
            "razorpay_key_secret": "VARCHAR(100) DEFAULT ''",
            "studio_phone": "VARCHAR(50) DEFAULT '+91 93504 39667'",
            "studio_whatsapp": "VARCHAR(50) DEFAULT '919350439667'",
            "permanent_phone": "VARCHAR(50) DEFAULT '9350439667'",
            "additional_emails": "TEXT DEFAULT ''",
            "reset_otp": "VARCHAR(10)",
            "reset_otp_expiry": "DATETIME",
            "studio_email": "VARCHAR(100) DEFAULT 'contact@tulsawear.com'",
            "studio_address": "VARCHAR(255) DEFAULT 'Tulsa Wears Atelier, Hansi, Haryana, India - 125033'",
            "studio_hours": "VARCHAR(100) DEFAULT 'Mon – Sat: 10:00 AM – 7:00 PM IST'",
            "warehouse_pincode": "VARCHAR(20) DEFAULT '125033'",
            "warehouse_city": "VARCHAR(100) DEFAULT 'Hansi'",
            "warehouse_state": "VARCHAR(100) DEFAULT 'Haryana'",
            "warehouse_address": "VARCHAR(255) DEFAULT 'Tulsa Wears Atelier, Hansi'",
            "shiprocket_email": "VARCHAR(150) DEFAULT ''",
            "shiprocket_password": "VARCHAR(255) DEFAULT ''",
            "shiprocket_token": "TEXT DEFAULT ''",
            "shiprocket_token_expiry": "DATETIME",
            "shipping_fallback_enabled": "BOOLEAN DEFAULT 1",
            "shipping_flat_fallback": "FLOAT DEFAULT 0.0"
        }
        with db.engine.begin() as connection:
            for col_name, col_type in admin_cols.items():
                if col_name not in existing_admin_cols:
                    connection.execute(
                        text(f"ALTER TABLE admin_users ADD COLUMN {col_name} {col_type}")
                    )

    if "customer_users" in tables:
        existing_cust_cols = {
            column["name"]
            for column in inspector.get_columns("customer_users")
        }
        cust_cols = {
            "is_verified": "BOOLEAN DEFAULT 0",
            "otp_code": "VARCHAR(10)",
            "otp_expiry": "DATETIME",
            "otp_attempts": "INTEGER DEFAULT 0",
            "otp_last_sent": "DATETIME",
            "saved_cart_json": "TEXT"
        }
        with db.engine.begin() as connection:
            for col_name, col_type in cust_cols.items():
                if col_name not in existing_cust_cols:
                    connection.execute(
                        text(f"ALTER TABLE customer_users ADD COLUMN {col_name} {col_type}")
                    )

    if "customer_addresses" in tables:
        existing_addr_cols = {
            column["name"]
            for column in inspector.get_columns("customer_addresses")
        }
        if "is_default" not in existing_addr_cols:
            with db.engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE customer_addresses ADD COLUMN is_default BOOLEAN DEFAULT 0")
                )

    # Ensure tables exist
    # Additive shared-content tables; existing catalog/order tables are untouched.
    SiteContent.__table__.create(bind=db.engine, checkfirst=True)
    SiteContentRevision.__table__.create(bind=db.engine, checkfirst=True)
    CustomerAddress.__table__.create(bind=db.engine, checkfirst=True)
    EditorPreviewToken.__table__.create(bind=db.engine, checkfirst=True)
    try:
        from models.customer_wishlist import CustomerWishlist
        CustomerWishlist.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    try:
        from models.order_notification import OrderNotification
        OrderNotification.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    try:
        from models.product_category import ProductCategory
        ProductCategory.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    try:
        from models.production_batch import ProductionBatch
        ProductionBatch.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    try:
        from models.production_allocation import ProductionAllocation
        ProductionAllocation.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    try:
        from models.production_setting import ProductionSetting
        ProductionSetting.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    try:
        from models.payment_webhook import PaymentWebhookEvent
        PaymentWebhookEvent.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass

    try:
        db.create_all()
    except Exception:
        pass

    try:
        from models.product_category import ProductCategory
        existing_assigned = {row[0] for row in db.session.query(ProductCategory.product_id).all()}
        for p in Product.query.all():
            if p.id not in existing_assigned and p.category:
                db.session.add(ProductCategory(product_id=p.id, category=p.category, is_primary=True))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        if AdminUser.query.count() == 0:
            default_admin = AdminUser(
                username=os.getenv("ADMIN_USERNAME", "admin"),
                default_delivery_days=10
            )
            initial_admin_password = os.getenv("ADMIN_PASSWORD")
            if not initial_admin_password:
                raise RuntimeError("Set ADMIN_PASSWORD before initializing the first admin account")
            default_admin.set_password(initial_admin_password)
            db.session.add(default_admin)
            db.session.commit()

        # Seed initial launch coupons if none exist
        if Coupon.query.count() == 0:
            c1 = Coupon(
                code="TULSA10",
                discount_type="percentage",
                discount_value=10.0,
                min_order_amount=0.0,
                max_discount=1500.0,
                is_active=True
            )
            c2 = Coupon(
                code="WELCOME500",
                discount_type="flat",
                discount_value=500.0,
                min_order_amount=2499.0,
                is_active=True
            )
            db.session.add_all([c1, c2])
            db.session.commit()
    except Exception as e:
        db.session.rollback()

    # The storefront is the sole migration owner. The admin portal checks this
    # version before serving requests and never applies a second copy of DDL.
    required_tables = {
        "products", "orders", "site_content", "site_content_revisions",
        "customer_addresses", "editor_preview_tokens", "order_notifications",
        "production_batches", "production_allocations", "production_settings"
    }
    present_tables = set(inspect(db.engine).get_table_names())
    missing_tables = required_tables - present_tables
    if missing_tables:
        raise RuntimeError("Storefront schema migration incomplete; required tables are missing")
    with db.engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS tulsa_schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "INSERT INTO tulsa_schema_migrations (version) VALUES (1) ON CONFLICT DO NOTHING"
        ))


# =========================================
# SITE TRAFFIC & ANALYTICS TRACKING
# =========================================

@app.before_request
def track_site_traffic():
    # Ignore static files, favicon, etc.
    if request.path.startswith("/static") or request.path.startswith("/favicon.ico"):
        return
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()

        event = "visit"
        if request.path == "/checkout":
            event = "checkout_visit"
        elif request.path.startswith("/payment"):
            event = "payment_visit"

        visit = TrafficLog(
            event_type=event,
            ip_address=(ip or "127.0.0.1")[:95],
            page_url=request.path[:250],
            referrer=(request.referrer or "")[:250],
            user_agent=(request.user_agent.string if request.user_agent else "")[:250],
            customer_id=session.get("customer_id")
        )
        db.session.add(visit)
        db.session.commit()
    except Exception:
        db.session.rollback()


@app.before_request
def protect_account_and_checkout_posts():
    protected_endpoints = {
        "customer_register", "customer_login", "customer_dashboard",
        "checkout", "buy_now", "submit_payment_proof"
    }
    if request.method == "POST" and request.endpoint in protected_endpoints:
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            return jsonify({"success": False, "message": "Session expired. Refresh the page and try again."}), 400


@app.before_request
def enforce_mandatory_customer_login():
    if request.path.startswith("/static") or request.path.startswith("/favicon.ico") or request.path.startswith("/admin"):
        return
    if request.path.startswith("/customer/") or request.path.startswith("/api/"):
        return

    try:
        from services.site_content import get_site_content
        content = get_site_content()
        if content.get("mandatory_customer_login") == "true":
            if not session.get("customer_id"):
                return redirect(url_for("customer_login", next=request.full_path if request.query_string else request.path))
    except Exception:
        pass


# =========================================
# PRODUCTION ERROR HANDLERS
# =========================================

@app.errorhandler(404)
def handle_not_found_error(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def handle_internal_error(e):
    db.session.rollback()
    app.logger.error(f"Internal server error: {e}")
    return render_template("500.html"), 500


# =========================================
# SEO: ROBOTS.TXT & SITEMAP.XML
# =========================================

@app.route("/robots.txt")
def robots_txt():
    rules = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /checkout",
        "Disallow: /payment/",
        "Disallow: /payment-step/",
        "Disallow: /customer/",
        "Disallow: /api/",
        "",
        f"Sitemap: {request.url_root.rstrip('/')}/sitemap.xml"
    ]
    return Response("\n".join(rules), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    base_url = request.url_root.rstrip("/")
    pages = [
        {"loc": f"{base_url}/", "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{base_url}/fitting-room", "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base_url}/shop", "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base_url}/#pick-your-silk", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base_url}/#the-rack", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base_url}/#cinematic-lookbook", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base_url}/#weaving-studio", "changefreq": "weekly", "priority": "0.8"},
    ]
    try:
        products = Product.query.filter(Product.stock > 0).all()
        for p in products:
            pages.append({
                "loc": f"{base_url}/product/{p.id}",
                "changefreq": "weekly",
                "priority": "0.8"
            })
    except Exception:
        pass

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for page in pages:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{page['loc']}</loc>")
        xml_lines.append(f"    <changefreq>{page['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{page['priority']}</priority>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    return Response("\n".join(xml_lines), mimetype="application/xml")


# =========================================
# HOME PAGE
# =========================================

@app.route("/")
def home():

    products = Product.query.order_by(
        Product.created_at.desc()
    ).all()

    best_sellers = [p for p in products if p.best_seller]

    approved_feedback = Feedback.query.filter_by(
        is_approved=True
    ).order_by(
        Feedback.created_at.desc()
    ).limit(6).all()

    return render_template(
        "index.html",
        products=products,
        best_sellers=best_sellers,
        approved_feedback=approved_feedback
    )


# =========================================
# VIRTUAL FITTING ROOM (Stage 3 Enhanced)
# =========================================

@app.route("/fitting-room")
def fitting_room():
    products = Product.query.order_by(
        Product.created_at.desc()
    ).all()

    best_sellers = Product.query.filter_by(
        best_seller=True
    ).all()

    return render_template(
        "fitting_room.html",
        products=products,
        best_sellers=best_sellers
    )


# =========================================
# SHOP PAGE
# =========================================

@app.route("/shop")
def shop():

    query = Product.query

    category = request.args.get("category", "").strip()
    fabric = request.args.get("fabric", "").strip()
    color = request.args.get("color", "").strip()
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    sort = request.args.get("sort", "newest").strip()

    # CATEGORY FILTER (Multi-Category & Canonical Alias Matching)
    if category:
        from services.category_service import filter_products_by_category
        query = filter_products_by_category(query, category)

    # FABRIC FILTER
    if fabric:
        query = query.filter(Product.fabric == fabric)

    # COLOR FILTER
    if color:
        query = query.filter(Product.color == color)

    # MINIMUM PRICE FILTER
    if min_price is not None:
        query = query.filter(Product.price >= min_price)

    # MAXIMUM PRICE FILTER
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # SORTING
    if sort == "price_asc":
        query = query.order_by(Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc())
    elif sort == "best_seller":
        query = query.order_by(Product.best_seller.desc(), Product.created_at.desc())
    else:
        sort = "newest"
        query = query.order_by(Product.created_at.desc())

    products = query.all()

    all_categories = [
        "Palazzo Set",
        "Salwar Kameez",
        "Casual Wear",
        "Party / Wedding Regalia",
        "Best Sellers",
    ]

    from services.category_service import resolve_canonical_category
    display_category = resolve_canonical_category(category) if category else ""

    return render_template(
        "shop.html",
        products=products,
        categories=all_categories,
        selected_category=category,
        display_category=display_category,
        selected_fabric=fabric,
        selected_color=color,
        selected_sort=sort,
        min_price=min_price,
        max_price=max_price,
        product_count=len(products)
    )


# =========================================
# SHOPPING BAG
# =========================================

@app.route("/bag")
def bag():
    cart = session.get("cart", [])
    raw_items = []

    for item in cart:
        product = Product.query.get(item["product_id"])
        if product:
            raw_items.append({
                "product": product,
                "quantity": max(1, int(item.get("quantity", 1))),
                "size": item.get("size", "M"),
                "top_length": item.get("top_length", "30"),
                "sleeves_length": item.get("sleeves_length", "18"),
                "bust": item.get("bust", ""),
                "waist": item.get("waist", ""),
                "hip": item.get("hip", ""),
                "shoulder": item.get("shoulder", "")
            })

    # Retrieve applied coupon if present
    applied_coupon = session.get("applied_coupon")
    coupon_obj = None
    if applied_coupon and applied_coupon.get("code"):
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()

    calc = calculate_bag_and_checkout(raw_items, coupon_obj=coupon_obj, shipping_paise=0)

    if coupon_obj and calc["coupon_valid"]:
        applied_coupon["discount_amount"] = calc["discount_amount"]
        session["applied_coupon"] = applied_coupon
    elif applied_coupon:
        session.pop("applied_coupon", None)
        applied_coupon = None

    return render_template(
        "bag.html",
        cart_items=calc["items"],
        total=calc["total"],
        subtotal=calc["subtotal"],
        discount_amount=calc["discount_amount"],
        applied_coupon=applied_coupon
    )


# =========================================
# ADD PRODUCT TO BAG
# =========================================

@app.route(
    "/add-to-bag/<int:product_id>",
    methods=["POST"]
)
def add_to_bag(product_id):

    product = Product.query.get_or_404(
        product_id
    )


    # CHECK STOCK

    if product.stock <= 0:

        return redirect(
            url_for(
                "product_detail",
                product_id=product.id
            )
        )


    cart = session.get(
        "cart",
        []
    )


    size = request.form.get("size", "M").strip()
    top_length = request.form.get("top_length", "30").strip()
    sleeves_length = request.form.get("sleeves_length", "18").strip()
    bust = request.form.get("bust", "").strip()
    waist = request.form.get("waist", "").strip()
    hip = request.form.get("hip", "").strip()
    shoulder = request.form.get("shoulder", "").strip()

    found = False

    for item in cart:
        if item["product_id"] == product.id and item.get("size") == size:
            if item["quantity"] < product.stock:
                item["quantity"] += 1
            found = True
            break

    if not found:
        cart.append(
            {
                "product_id": product.id,
                "quantity": 1,
                "size": size,
                "top_length": top_length,
                "sleeves_length": sleeves_length,
                "bust": bust,
                "waist": waist,
                "hip": hip,
                "shoulder": shoulder
            }
        )

    session["cart"] = cart
    session.modified = True

    return redirect(
        url_for("bag")
    )


# =========================================
# REMOVE PRODUCT FROM BAG
# =========================================

@app.route(
    "/remove-from-bag/<int:product_id>",
    methods=["POST"]
)
def remove_from_bag(product_id):

    cart = session.get(
        "cart",
        []
    )


    cart = [
        item
        for item in cart
        if item["product_id"] != product_id
    ]


    session["cart"] = cart

    session.modified = True


    return redirect(
        url_for("bag")
    )


# =========================================
# UPDATE BAG QUANTITY (+ / -)
# =========================================

@app.route(
    "/update-bag-quantity/<int:product_id>/<string:action>"
)
def update_bag_quantity(product_id, action):

    cart = session.get("cart", [])
    product = Product.query.get_or_404(product_id)

    updated_cart = []

    for item in cart:
        if item["product_id"] == product_id:
            if action == "increase":
                if item["quantity"] < product.stock:
                    item["quantity"] += 1
                updated_cart.append(item)
            elif action == "decrease":
                if item["quantity"] > 1:
                    item["quantity"] -= 1
                    updated_cart.append(item)
                # if quantity is 1 and decreased, it is removed
        else:
            updated_cart.append(item)

    session["cart"] = updated_cart
    session.modified = True

    return redirect(url_for("bag"))


# =========================================
# BAG CHECKOUT
# =========================================

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart = session.get("cart", [])
    if not cart:
        return redirect(url_for("shop"))

    raw_items = []
    for item in cart:
        product = Product.query.get(item["product_id"])
        if product:
            raw_items.append({
                "product": product,
                "quantity": max(1, int(item.get("quantity", 1))),
                "size": item.get("size", "M"),
                "top_length": item.get("top_length", "30"),
                "sleeves_length": item.get("sleeves_length", "18"),
                "bust": item.get("bust", ""),
                "waist": item.get("waist", ""),
                "hip": item.get("hip", ""),
                "shoulder": item.get("shoulder", "")
            })

    if not raw_items:
        session["cart"] = []
        return redirect(url_for("shop"))

    applied_coupon = session.get("applied_coupon")
    coupon_obj = None
    if applied_coupon and applied_coupon.get("code"):
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()

    admin_user = AdminUser.query.first()
    warehouse_info = {
        "pincode": admin_user.warehouse_pincode if (admin_user and admin_user.warehouse_pincode) else DEFAULT_WAREHOUSE["pincode"],
        "city": admin_user.warehouse_city if (admin_user and admin_user.warehouse_city) else DEFAULT_WAREHOUSE["city"],
        "state": admin_user.warehouse_state if (admin_user and admin_user.warehouse_state) else DEFAULT_WAREHOUSE["state"]
    }
    shiprocket_creds = {
        "token": admin_user.shiprocket_token if admin_user else None
    }
    fallback_enabled = bool(admin_user.shipping_fallback_enabled) if admin_user else True
    fallback_amount = float(admin_user.shipping_flat_fallback or 0.0) if admin_user else 0.0

    # Determine destination pincode if available
    customer_id = session.get("customer_id")
    current_customer = CustomerUser.query.get(customer_id) if customer_id else None
    default_pincode = current_customer.pincode if current_customer and current_customer.pincode else ""

    shipping_quote = None
    shipping_paise = 0
    if default_pincode:
        shipping_quote = get_shipping_quote(
            destination_pincode=default_pincode,
            destination_country="India",
            products_with_qty=raw_items,
            warehouse_info=warehouse_info,
            shiprocket_creds=shiprocket_creds,
            fallback_enabled=fallback_enabled,
            fallback_amount=fallback_amount
        )
        if shipping_quote.get("serviceable"):
            shipping_paise = to_paise(shipping_quote.get("shipping_fee", 0.0))

    calc = calculate_bag_and_checkout(raw_items, coupon_obj=coupon_obj, shipping_paise=shipping_paise)

    if coupon_obj and calc["coupon_valid"]:
        applied_coupon["discount_amount"] = calc["discount_amount"]
        session["applied_coupon"] = applied_coupon
    elif applied_coupon:
        session.pop("applied_coupon", None)
        applied_coupon = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        pincode = request.form.get("pincode", "").strip()

        if not name or not phone or not address or not city or not pincode:
            flash("⚠️ All delivery details (Name, Mobile Phone, Address, City, PIN code) are mandatory.", "danger")
            return redirect(url_for("checkout"))

        is_valid_phone, clean_phone = validate_indian_phone(phone)
        if not is_valid_phone:
            flash("⚠️ Please enter a genuine 10-digit Indian mobile number (e.g. 9876543210).", "danger")
            return redirect(url_for("checkout"))

        clean_pincode = re.sub(r"\D", "", pincode)
        if len(clean_pincode) != 6:
            flash("⚠️ Please enter a valid 6-digit Indian PIN code.", "danger")
            return redirect(url_for("checkout"))

        # Recalculate shipping quote for customer's submitted address
        order_shipping_quote = get_shipping_quote(
            destination_pincode=clean_pincode,
            destination_country="India",
            products_with_qty=raw_items,
            warehouse_info=warehouse_info,
            shiprocket_creds=shiprocket_creds,
            fallback_enabled=fallback_enabled,
            fallback_amount=fallback_amount
        )

        if not order_shipping_quote.get("serviceable"):
            flash(f"⚠️ Delivery Serviceability Notice: {order_shipping_quote.get('error')}", "danger")
            return redirect(url_for("checkout"))

        order_shipping_fee = float(order_shipping_quote.get("shipping_fee", 0.0))
        final_calc = calculate_bag_and_checkout(
            raw_items,
            coupon_obj=coupon_obj,
            shipping_paise=to_paise(order_shipping_fee)
        )

        phone = clean_phone
        pincode = clean_pincode

        # Sizing and Measurements from form or first cart item
        size = request.form.get("size", "").strip() or raw_items[0].get("size", "M")
        top_length = request.form.get("top_length", "").strip() or raw_items[0].get("top_length", "30")
        sleeves_length = request.form.get("sleeves_length", "").strip() or raw_items[0].get("sleeves_length", "18")
        bust = request.form.get("bust", "").strip() or raw_items[0].get("bust", "")
        waist = request.form.get("waist", "").strip() or raw_items[0].get("waist", "")
        hip = request.form.get("hip", "").strip() or raw_items[0].get("hip", "")
        shoulder = request.form.get("shoulder", "").strip() or raw_items[0].get("shoulder", "")

        tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"
        est_days = order_shipping_quote.get("estimated_days") or (admin_user.default_delivery_days if admin_user else 10)
        est_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")

        items_summary = ", ".join([f"{item['product'].name} (x{item['quantity']})" for item in raw_items])

        # WhatsApp opt-in consent (unchecked by default)
        whatsapp_opt_in = (request.form.get("whatsapp_opt_in") == "1")
        whatsapp_opt_in_at = datetime.utcnow() if whatsapp_opt_in else None
        whatsapp_opt_in_source = "checkout" if whatsapp_opt_in else None

        # 7–15 Day Delivery Timeline Calculation
        from services.notification_service import calculate_delivery_window
        delivery_window = calculate_delivery_window()
        delivery_window_start = delivery_window["start_str"]
        delivery_window_end = delivery_window["end_str"]

        # Itemized snapshot for persistent receipt & notification accuracy
        order_items_payload = []
        for it in raw_items:
            order_items_payload.append({
                "product_id": it["product"].id,
                "name": it["product"].name,
                "quantity": it["quantity"],
                "price": float(it["product"].price or 0.0),
                "size": it.get("size", "M"),
                "top_length": it.get("top_length", "30"),
                "bust": it.get("bust", ""),
                "image": it["product"].image
            })
        order_items_data = json.dumps(order_items_payload)

        # Customer Account Creation / Linking
        account_password = request.form.get("account_password", "").strip()
        customer = current_customer
        if customer:
            if customer.phone != phone:
                flash("Sign in to the account that owns this mobile number, or continue with another number as a guest.", "danger")
                return redirect(url_for("checkout"))
        elif account_password and len(account_password) >= 6:
            if not CustomerUser.query.filter_by(phone=phone).first():
                customer = CustomerUser(
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    city=city,
                    pincode=pincode
                )
                customer.set_password(account_password)
                db.session.add(customer)
                db.session.commit()
                _establish_customer_session(customer)

        new_order = Order(
            product_id=raw_items[0]["product"].id,
            product_name=items_summary,
            price=final_calc["total"],
            customer_name=name,
            phone=phone,
            email=email,
            address=address,
            city=city,
            pincode=pincode,
            tracking_id=tracking_id,
            customer_id=customer.id if customer else None,
            size=size,
            top_length=top_length,
            sleeves_length=sleeves_length,
            bust=bust,
            waist=waist,
            hip=hip,
            shoulder=shoulder,
            estimated_delivery_days=est_days,
            estimated_delivery_date=est_date,
            advance_paid=0.0,
            balance_due=final_calc["total"],
            coupon_code=applied_coupon.get("code") if applied_coupon else None,
            discount_amount=final_calc["discount_amount"],
            shipping_fee=order_shipping_fee,
            shipping_provider=order_shipping_quote.get("provider", "Insured Courier"),
            shipping_service=order_shipping_quote.get("service", "Standard"),
            whatsapp_opt_in=whatsapp_opt_in,
            whatsapp_opt_in_at=whatsapp_opt_in_at,
            whatsapp_opt_in_source=whatsapp_opt_in_source,
            whatsapp_notification_status="Pending" if whatsapp_opt_in else "Not opted in",
            email_notification_status="Pending",
            order_items_data=order_items_data,
            delivery_window_start=delivery_window_start,
            delivery_window_end=delivery_window_end,
            status="Payment Pending"
        )

        if coupon_obj:
            coupon_obj.times_used = (coupon_obj.times_used or 0) + 1

        db.session.add(new_order)
        db.session.commit()

        if customer:
            session["customer_id"] = customer.id
            session["customer_name"] = customer.name
            session["customer_phone"] = customer.phone
        else:
            accessible_orders = session.get("authorized_order_ids", [])
            session["authorized_order_ids"] = (accessible_orders + [new_order.id])[-20:]

        # Clear cart and coupon upon order creation
        session["cart"] = []
        session.pop("applied_coupon", None)
        session.modified = True

        payment_method = request.form.get("payment_method", "razorpay").strip().lower()

        if payment_method in ("cod", "cash on delivery"):
            new_order.payment_method = "Cash on Delivery"
            new_order.payment_status = "Pending"
            new_order.status = "Confirmed"
            new_order.advance_paid = 0.0
            new_order.balance_due = final_calc["total"]
            if not new_order.tracking_id:
                new_order.tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"
            try:
                admin_user = AdminUser.query.first()
                est_days = admin_user.default_delivery_days if admin_user else 10
            except Exception:
                est_days = 10
            new_order.estimated_delivery_days = est_days
            new_order.estimated_delivery_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")
            db.session.commit()

            try:
                from services.notification_service import trigger_order_notifications
                trigger_order_notifications(new_order.id, event_type="order_confirmation", trigger_source="cod_checkout")
            except Exception as exc:
                app.logger.error(f"COD notification error: {exc}")

            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.form.get("checkout_mode") == "ajax":
                return jsonify({
                    "success": True,
                    "payment_method": "Cash on Delivery",
                    "order_id": new_order.id,
                    "redirect_url": url_for("order_success", order_id=new_order.id)
                })
            return redirect(url_for("order_success", order_id=new_order.id))

        new_order.payment_method = "Razorpay Online"
        new_order.payment_status = "Pending"
        amount_in_paise = int(round(final_calc["total"] * 100))
        active_razorpay_key = get_razorpay_credentials()["key_id"]

        try:
            rzp_order = create_razorpay_order(
                amount_inr=final_calc["total"],
                receipt=f"atelier_{new_order.id}",
                notes={"order_id": str(new_order.id), "customer": new_order.customer_name}
            )
            new_order.razorpay_order_id = rzp_order["order_id"]
            active_razorpay_key = rzp_order["key_id"]
            db.session.commit()
        except Exception as e:
            app.logger.error(f"Razorpay order creation error: {e}")
            new_order.razorpay_order_id = f"atelier_ord_{new_order.id}"
            db.session.commit()

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.form.get("checkout_mode") == "ajax":
            return jsonify({
                "success": True,
                "payment_method": "razorpay",
                "order_id": new_order.id,
                "razorpay_order_id": new_order.razorpay_order_id,
                "amount": amount_in_paise,
                "currency": "INR",
                "key_id": active_razorpay_key,
                "customer_name": new_order.customer_name,
                "customer_email": new_order.email,
                "customer_phone": new_order.phone,
                "product_name": new_order.product_name,
                "redirect_url": url_for("order_success", order_id=new_order.id)
            })

        active_upi_id, active_upi_name = get_merchant_upi_config()

        return render_template(
            "payment.html",
            order=new_order,
            product=raw_items[0]["product"],
            razorpay_key_id=active_razorpay_key,
            razorpay_order_id=new_order.razorpay_order_id,
            upi_id=active_upi_id,
            upi_payee_name=active_upi_name
        )

    return render_template(
        "checkout.html",
        product=raw_items[0]["product"],
        cart_items=calc["items"],
        total=calc["total"],
        subtotal=calc["subtotal"],
        discount_amount=calc["discount_amount"],
        applied_coupon=applied_coupon,
        shipping_quote=shipping_quote,
        is_cart_checkout=True
    )


# =========================================
# PRODUCT DETAILS
# =========================================

@app.route(
    "/product/<int:product_id>"
)
def product_detail(product_id):

    product = Product.query.get_or_404(
        product_id
    )

    return render_template(
        "product.html",
        product=product
    )


# =========================================
# BUY NOW / CHECKOUT
# =========================================

@app.route(
    "/buy-now/<int:product_id>",
    methods=["GET", "POST"]
)
def buy_now(product_id):

    product = Product.query.get_or_404(
        product_id
    )


    # =====================================
    # CUSTOMER SUBMITS CHECKOUT
    # =====================================

    # Coupon calculation
    applied_coupon = session.get("applied_coupon")
    discount_amount = 0.0
    # Retrieve applied coupon if present
    applied_coupon = session.get("applied_coupon")
    coupon_obj = None
    if applied_coupon and applied_coupon.get("code"):
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()

    admin_user = AdminUser.query.first()
    warehouse_info = {
        "pincode": admin_user.warehouse_pincode if (admin_user and admin_user.warehouse_pincode) else DEFAULT_WAREHOUSE["pincode"],
        "city": admin_user.warehouse_city if (admin_user and admin_user.warehouse_city) else DEFAULT_WAREHOUSE["city"],
        "state": admin_user.warehouse_state if (admin_user and admin_user.warehouse_state) else DEFAULT_WAREHOUSE["state"]
    }
    shiprocket_creds = {
        "token": admin_user.shiprocket_token if admin_user else None
    }
    fallback_enabled = bool(admin_user.shipping_fallback_enabled) if admin_user else True
    fallback_amount = float(admin_user.shipping_flat_fallback or 0.0) if admin_user else 0.0

    customer_id = session.get("customer_id")
    current_customer = CustomerUser.query.get(customer_id) if customer_id else None
    default_pincode = current_customer.pincode if current_customer and current_customer.pincode else ""

    single_item = [{"product": product, "quantity": 1}]
    shipping_quote = None
    shipping_paise = 0
    if default_pincode:
        shipping_quote = get_shipping_quote(
            destination_pincode=default_pincode,
            destination_country="India",
            products_with_qty=single_item,
            warehouse_info=warehouse_info,
            shiprocket_creds=shiprocket_creds,
            fallback_enabled=fallback_enabled,
            fallback_amount=fallback_amount
        )
        if shipping_quote.get("serviceable"):
            shipping_paise = to_paise(shipping_quote.get("shipping_fee", 0.0))

    calc = calculate_bag_and_checkout(single_item, coupon_obj=coupon_obj, shipping_paise=shipping_paise)

    if coupon_obj and calc["coupon_valid"]:
        applied_coupon["discount_amount"] = calc["discount_amount"]
        session["applied_coupon"] = applied_coupon
    elif applied_coupon:
        session.pop("applied_coupon", None)
        applied_coupon = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        pincode = request.form.get("pincode", "").strip()

        if not name or not phone or not address or not city or not pincode:
            flash("⚠️ All delivery details (Name, Mobile Phone, Address, City, PIN code) are mandatory.", "danger")
            return redirect(url_for("buy_now", product_id=product.id))

        is_valid_phone, clean_phone = validate_indian_phone(phone)
        if not is_valid_phone:
            flash("⚠️ Please enter a genuine 10-digit Indian mobile number (e.g. 9876543210).", "danger")
            return redirect(url_for("buy_now", product_id=product.id))

        clean_pincode = re.sub(r"\D", "", pincode)
        if len(clean_pincode) != 6:
            flash("⚠️ Please enter a valid 6-digit Indian PIN code.", "danger")
            return redirect(url_for("buy_now", product_id=product.id))

        order_shipping_quote = get_shipping_quote(
            destination_pincode=clean_pincode,
            destination_country="India",
            products_with_qty=single_item,
            warehouse_info=warehouse_info,
            shiprocket_creds=shiprocket_creds,
            fallback_enabled=fallback_enabled,
            fallback_amount=fallback_amount
        )

        if not order_shipping_quote.get("serviceable"):
            flash(f"⚠️ Delivery Serviceability Notice: {order_shipping_quote.get('error')}", "danger")
            return redirect(url_for("buy_now", product_id=product.id))

        order_shipping_fee = float(order_shipping_quote.get("shipping_fee", 0.0))
        final_calc = calculate_bag_and_checkout(
            single_item,
            coupon_obj=coupon_obj,
            shipping_paise=to_paise(order_shipping_fee)
        )

        phone = clean_phone
        pincode = clean_pincode

        # Measurement specs
        size = request.form.get("size", "M").strip()
        top_length = request.form.get("top_length", "30").strip()
        sleeves_length = request.form.get("sleeves_length", "18").strip()
        bust = request.form.get("bust", "").strip()
        waist = request.form.get("waist", "").strip()
        hip = request.form.get("hip", "").strip()
        shoulder = request.form.get("shoulder", "").strip()

        tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"
        est_days = order_shipping_quote.get("estimated_days") or (admin_user.default_delivery_days if admin_user else 10)
        est_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")

        # WhatsApp opt-in consent (unchecked by default)
        whatsapp_opt_in = (request.form.get("whatsapp_opt_in") == "1")
        whatsapp_opt_in_at = datetime.utcnow() if whatsapp_opt_in else None
        whatsapp_opt_in_source = "buy_now" if whatsapp_opt_in else None

        # 7–15 Day Delivery Timeline Calculation
        from services.notification_service import calculate_delivery_window
        delivery_window = calculate_delivery_window()
        delivery_window_start = delivery_window["start_str"]
        delivery_window_end = delivery_window["end_str"]

        # Itemized snapshot for persistent receipt & notification accuracy
        order_items_data = json.dumps([{
            "product_id": product.id,
            "name": product.name,
            "quantity": 1,
            "price": float(product.price or 0.0),
            "size": size,
            "top_length": top_length,
            "bust": bust,
            "image": product.image
        }])

        # Customer Account Creation / Linking
        account_password = request.form.get("account_password", "").strip()
        customer = current_customer
        if customer:
            if customer.phone != phone:
                flash("Sign in to the account that owns this mobile number, or continue with another number as a guest.", "danger")
                return redirect(url_for("buy_now", product_id=product.id))
        elif account_password and len(account_password) >= 6:
            if not CustomerUser.query.filter_by(phone=phone).first():
                customer = CustomerUser(
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    city=city,
                    pincode=pincode
                )
                customer.set_password(account_password)
                db.session.add(customer)
                db.session.commit()
                _establish_customer_session(customer)

        new_order = Order(
            product_id=product.id,
            product_name=product.name,
            price=final_calc["total"],
            customer_name=name,
            phone=phone,
            email=email,
            address=address,
            city=city,
            pincode=pincode,
            tracking_id=tracking_id,
            customer_id=customer.id if customer else None,
            size=size,
            top_length=top_length,
            sleeves_length=sleeves_length,
            bust=bust,
            waist=waist,
            hip=hip,
            shoulder=shoulder,
            estimated_delivery_days=est_days,
            estimated_delivery_date=est_date,
            advance_paid=0.0,
            balance_due=final_calc["total"],
            coupon_code=applied_coupon.get("code") if applied_coupon else None,
            discount_amount=final_calc["discount_amount"],
            shipping_fee=order_shipping_fee,
            shipping_provider=order_shipping_quote.get("provider", "Insured Courier"),
            shipping_service=order_shipping_quote.get("service", "Standard"),
            whatsapp_opt_in=whatsapp_opt_in,
            whatsapp_opt_in_at=whatsapp_opt_in_at,
            whatsapp_opt_in_source=whatsapp_opt_in_source,
            whatsapp_notification_status="Pending" if whatsapp_opt_in else "Not opted in",
            email_notification_status="Pending",
            order_items_data=order_items_data,
            delivery_window_start=delivery_window_start,
            delivery_window_end=delivery_window_end,
            status="Payment Pending"
        )

        if coupon_obj:
            coupon_obj.times_used = (coupon_obj.times_used or 0) + 1

        db.session.add(new_order)
        db.session.commit()

        if customer:
            session["customer_id"] = customer.id
            session["customer_name"] = customer.name
            session["customer_phone"] = customer.phone
        else:
            accessible_orders = session.get("authorized_order_ids", [])
            session["authorized_order_ids"] = (accessible_orders + [new_order.id])[-20:]

        session.pop("applied_coupon", None)
        session.modified = True

        payment_method = request.form.get("payment_method", "razorpay").strip().lower()

        if payment_method in ("cod", "cash on delivery"):
            new_order.payment_method = "Cash on Delivery"
            new_order.payment_status = "Pending"
            new_order.status = "Confirmed"
            new_order.advance_paid = 0.0
            new_order.balance_due = final_calc["total"]
            if not new_order.tracking_id:
                new_order.tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"
            try:
                admin_user = AdminUser.query.first()
                est_days = admin_user.default_delivery_days if admin_user else 10
            except Exception:
                est_days = 10
            new_order.estimated_delivery_days = est_days
            new_order.estimated_delivery_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")
            db.session.commit()

            try:
                from services.notification_service import trigger_order_notifications
                trigger_order_notifications(new_order.id, event_type="order_confirmation", trigger_source="cod_direct_checkout")
            except Exception as exc:
                app.logger.error(f"COD notification error: {exc}")

            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.form.get("checkout_mode") == "ajax":
                return jsonify({
                    "success": True,
                    "payment_method": "Cash on Delivery",
                    "order_id": new_order.id,
                    "redirect_url": url_for("order_success", order_id=new_order.id)
                })
            return redirect(url_for("order_success", order_id=new_order.id))

        new_order.payment_method = "Razorpay Online"
        new_order.payment_status = "Pending"
        amount_in_paise = int(round(final_calc["total"] * 100))
        active_razorpay_key = get_razorpay_credentials()["key_id"]

        try:
            rzp_order = create_razorpay_order(
                amount_inr=final_calc["total"],
                receipt=f"atelier_{new_order.id}",
                notes={"order_id": str(new_order.id), "customer": new_order.customer_name}
            )
            new_order.razorpay_order_id = rzp_order["order_id"]
            active_razorpay_key = rzp_order["key_id"]
            db.session.commit()
        except Exception as e:
            app.logger.error(f"Razorpay order creation error: {e}")
            new_order.razorpay_order_id = f"atelier_ord_{new_order.id}"
            db.session.commit()

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.form.get("checkout_mode") == "ajax":
            return jsonify({
                "success": True,
                "payment_method": "razorpay",
                "order_id": new_order.id,
                "razorpay_order_id": new_order.razorpay_order_id,
                "amount": amount_in_paise,
                "currency": "INR",
                "key_id": active_razorpay_key,
                "customer_name": new_order.customer_name,
                "customer_email": new_order.email,
                "customer_phone": new_order.phone,
                "product_name": new_order.product_name,
                "redirect_url": url_for("order_success", order_id=new_order.id)
            })

        active_upi_id, active_upi_name = get_merchant_upi_config()

        return render_template(
            "payment.html",
            order=new_order,
            product=product,
            razorpay_key_id=active_razorpay_key,
            razorpay_order_id=new_order.razorpay_order_id,
            upi_id=active_upi_id,
            upi_payee_name=active_upi_name
        )

    sizing_defaults = {
        "size": request.args.get("size", "M").strip(),
        "top_length": request.args.get("top_length", "30").strip(),
        "sleeves_length": request.args.get("sleeves_length", "18").strip(),
        "bust": request.args.get("bust", "").strip(),
        "waist": request.args.get("waist", "").strip(),
        "hip": request.args.get("hip", "").strip(),
        "shoulder": request.args.get("shoulder", "").strip(),
    }

    return render_template(
        "checkout.html",
        product=product,
        sizing=sizing_defaults,
        total=calc["total"],
        subtotal=calc["subtotal"],
        discount_amount=calc["discount_amount"],
        applied_coupon=applied_coupon,
        shipping_quote=shipping_quote,
        is_cart_checkout=False
    )


# =========================================
# PAYMENT PROOF VIEW & SECURE SUBMISSION
# =========================================

def _can_access_order(order):
    if session.get("admin_logged_in"):
        return True
    customer_id = session.get("customer_id")
    if customer_id and order.customer_id == customer_id:
        return True
    return order.id in session.get("authorized_order_ids", [])

@app.route("/payment-step/<int:order_id>", methods=["GET"])
@app.route("/submit-payment-proof/<int:order_id>", methods=["GET"])
@app.route("/confirm-dev-payment/<int:order_id>", methods=["GET"])
def view_payment_step(order_id):
    order = db.session.get(Order, order_id) if hasattr(db.session, "get") else Order.query.get_or_404(order_id)
    if not order or not _can_access_order(order):
        return "Not found", 404
    product = (db.session.get(Product, order.product_id) if hasattr(db.session, "get") else Product.query.get(order.product_id)) or Product.query.first()

    if not order.razorpay_order_id or "dev" in str(order.razorpay_order_id).lower():
        try:
            rzp_order = create_razorpay_order(
                amount_inr=order.price,
                receipt=f"atelier_{order.id}",
                notes={"order_id": str(order.id), "customer": order.customer_name}
            )
            order.razorpay_order_id = rzp_order["order_id"]
            db.session.commit()
        except Exception as exc:
            app.logger.warning(f"Could not generate Razorpay order for #{order.id}: {exc}")

    creds = get_razorpay_credentials()
    active_razorpay_key = creds["key_id"]
    active_upi_id, active_upi_name = get_merchant_upi_config()
    is_test_mode = str(active_razorpay_key).startswith("rzp_test_")
    return render_template(
        "payment.html",
        order=order,
        product=product,
        razorpay_key_id=active_razorpay_key,
        razorpay_order_id=order.razorpay_order_id,
        is_test_mode=is_test_mode,
        upi_id=active_upi_id,
        upi_payee_name=active_upi_name
    )


# =========================================
# DYNAMIC UPI QR CODE API
# =========================================

@app.route("/api/order/<int:order_id>/upi-qr.png")
def get_order_upi_qr(order_id):
    order = db.session.get(Order, order_id) if hasattr(db.session, "get") else Order.query.get_or_404(order_id)
    if not order or not _can_access_order(order):
        return "Not found", 404

    upi_id, payee_name = get_merchant_upi_config()
    amount = float(order.price)
    note = f"Order_{order.id}_Tulsa"
    txn_ref = f"{order.id}"

    upi_uri = f"upi://pay?pa={upi_id}&pn={urllib.parse.quote(payee_name)}&am={amount:.2f}&cu=INR&tr={txn_ref}&tn={note}"

    if qrcode is not None:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=3,
        )
        qr.add_data(upi_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#121316", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    else:
        return redirect(f"https://api.qrserver.com/v1/create-qr-code/?size=240x240&data={urllib.parse.quote(upi_uri)}")


@app.route("/api/order/<int:order_id>/payment-qr-details")
def get_order_payment_qr_details(order_id):
    order = db.session.get(Order, order_id) if hasattr(db.session, "get") else Order.query.get_or_404(order_id)
    if not order or not _can_access_order(order):
        return jsonify({"success": False, "message": "Order not found"}), 404

    upi_id, payee_name = get_merchant_upi_config()
    amount = float(order.price)
    note = f"Order_{order.id}_Tulsa"
    txn_ref = f"{order.id}"
    upi_uri = f"upi://pay?pa={upi_id}&pn={urllib.parse.quote(payee_name)}&am={amount:.2f}&cu=INR&tr={txn_ref}&tn={note}"

    return jsonify({
        "success": True,
        "order_id": order.id,
        "amount": amount,
        "upi_id": upi_id,
        "payee_name": payee_name,
        "upi_uri": upi_uri,
        "qr_image_url": url_for("get_order_upi_qr", order_id=order.id)
    })


@app.route(
    "/submit-payment-proof/<int:order_id>",
    methods=["POST"]
)
@app.route(
    "/confirm-dev-payment/<int:order_id>",
    methods=["POST"]
)
def submit_payment_proof(order_id):
    order = Order.query.get_or_404(order_id)
    if not _can_access_order(order):
        return "Not found", 404
    if order.status != "Payment Pending":
        return "Order is no longer accepting payment submissions", 409

    payment_method = request.form.get("payment_method", "").strip()
    valid_upi_methods = {
        "UPI (GPay / PhonePe / QR)",
        "Google Pay",
        "PhonePe",
        "Paytm / UPI",
        "UPI"
    }
    if payment_method not in valid_upi_methods and payment_method != "Cash on Delivery":
        return "Invalid payment method", 400

    if payment_method == "Cash on Delivery":
        if order.status not in {"Payment Pending", "COD Pending"}:
            return "Order payment is already being processed", 409
        order.payment_method = "Cash on Delivery"
        order.status = "COD Pending"
        order.advance_paid = 0.0
        order.balance_due = order.price
        db.session.commit()

        try:
            from services.notification_service import trigger_order_notifications
            trigger_order_notifications(order.id, event_type="order_confirmation", trigger_source="cod_submission")
        except Exception as exc:
            app.logger.error(f"COD notification trigger error: {exc}")

        return redirect(url_for("order_success", order_id=order.id))

    upi_utr = request.form.get("upi_utr", "").strip()
    if not validate_utr(upi_utr):
        flash("⚠️ Please enter a genuine UPI UTR / Transaction Reference ID (min 8 alphanumeric characters from your payment app).", "danger")
        return redirect(url_for("view_payment_step", order_id=order.id))

    # Store submitted payment evidence privately; optional screenshot, mandatory UTR
    if "payment_screenshot" in request.files:
        file = request.files["payment_screenshot"]
        if file and file.filename:
            try:
                order.payment_screenshot = upload_payment_proof(file, order.id)
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("view_payment_step", order_id=order.id))
            except Exception as exc:
                app.logger.warning("Private payment-proof storage unavailable (%s)", type(exc).__name__)

    order.payment_method = payment_method
    order.status = "Payment Verification Required"
    order.upi_utr = upi_utr

    if not order.tracking_id:
        order.tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"

    try:
        admin_user = AdminUser.query.first()
        est_days = admin_user.default_delivery_days if admin_user else 10
    except Exception:
        est_days = 10

    order.estimated_delivery_days = est_days
    order.estimated_delivery_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")

    # A customer-provided UTR or image is a claim only, never a payment record.
    order.advance_paid = 0.0
    order.balance_due = order.price

    try:
        traffic = TrafficLog(
            event_type="order_placed",
            ip_address=request.remote_addr,
            page_url=f"/submit-payment-proof/{order.id}",
            customer_id=order.customer_id
        )
        db.session.add(traffic)
    except Exception:
        pass

    db.session.commit()

    try:
        from services.notification_service import trigger_order_notifications
        trigger_order_notifications(order.id, event_type="payment_pending", trigger_source="upi_submission")
    except Exception as exc:
        app.logger.error(f"UPI payment pending notification error: {exc}")

    return redirect(
        url_for("order_success", order_id=order.id)
    )

# Alias for backwards compatibility
confirm_dev_payment = submit_payment_proof


# =========================================
# RAZORPAY PAYMENT GATEWAY API & WEBHOOKS
# =========================================

@app.route("/api/create-order", methods=["POST"])
@app.route("/api/razorpay/create-order", methods=["POST"])
def api_create_razorpay_order():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    order_id = data.get("order_id")
    order = None

    if order_id:
        try:
            order = db.session.get(Order, int(order_id)) if hasattr(db.session, "get") else Order.query.get(int(order_id))
        except (ValueError, TypeError):
            pass
        if not order:
            return jsonify({"success": False, "message": "Order not found."}), 404
        if not _can_access_order(order):
            return jsonify({"success": False, "message": "Unauthorized access to order."}), 403
        amount_in_paise = int(round(order.price * 100))
        receipt = f"tulsa_ord_{order.id}"
        notes = {
            "order_id": str(order.id),
            "customer_name": (order.customer_name or "")[:45],
            "customer_phone": (order.phone or "")[:20]
        }
    else:
        req_amount = data.get("amount")
        if req_amount is None:
            cart = session.get("cart", [])
            applied_coupon = session.get("applied_coupon")
            calc = calculate_bag_and_checkout(cart, applied_coupon)
            amount_in_paise = int(round(calc["total"] * 100))
        else:
            try:
                amt_val = float(req_amount)
                amount_in_paise = int(amt_val)
            except (ValueError, TypeError):
                return jsonify({"success": False, "message": f"Invalid amount: {req_amount}"}), 400

        receipt = data.get("receipt") or f"tulsa_{uuid.uuid4().hex[:8]}"
        notes = data.get("notes") or {
            "customer_name": data.get("name", "")[:45],
            "customer_phone": data.get("phone", "")[:20]
        }

    # Minimum amount validation (100 paise / Rs 1.00)
    if amount_in_paise < 100:
        return jsonify({"success": False, "message": "Amount must be at least 100 paise."}), 400

    currency = data.get("currency", "INR")

    try:
        rzp_res = create_razorpay_order(amount_in_paise=amount_in_paise, currency=currency, receipt=receipt, notes=notes)
        if order:
            order.razorpay_order_id = rzp_res["order_id"]
            db.session.commit()

        return jsonify({
            "success": True,
            "order_id": rzp_res["order_id"],
            "razorpay_order_id": rzp_res["order_id"],
            "id": rzp_res["order_id"],
            "amount": rzp_res["amount"],
            "currency": rzp_res["currency"],
            "key_id": rzp_res["key_id"],
            "receipt": rzp_res.get("receipt"),
            "customer_name": order.customer_name if order else data.get("name", ""),
            "customer_email": order.email if order else data.get("email", ""),
            "customer_phone": order.phone if order else data.get("phone", ""),
            "product_name": order.product_name if order else "Tulsa Wear Couture"
        }), 200

    except ValueError as ve:
        return jsonify({"success": False, "message": str(ve)}), 400
    except razorpay.errors.BadRequestError as bre:
        app.logger.error(f"Razorpay Bad Request: {bre}")
        return jsonify({"success": False, "message": str(bre)}), 400
    except (razorpay.errors.GatewayError, razorpay.errors.ServerError) as se:
        app.logger.error(f"Razorpay Gateway/Server Error: {se}")
        return jsonify({"success": False, "message": "Razorpay service temporarily unavailable."}), 500
    except Exception as exc:
        err_str = str(exc)
        app.logger.exception("Failed to create Razorpay order")
        if "401" in err_str or "auth" in err_str.lower():
            return jsonify({"success": False, "message": "Razorpay authentication failed. Verify API credentials."}), 401
        return jsonify({"success": False, "message": "Failed to create order on payment gateway."}), 500


@app.route("/api/verify-payment", methods=["POST"])
@app.route("/api/razorpay/verify-payment", methods=["POST"])
@app.route("/payment/<int:order_id>", methods=["POST"])
def verify_payment_endpoint(order_id=None):
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    razorpay_order_id = (data.get("razorpay_order_id") or "").strip()
    razorpay_payment_id = (data.get("razorpay_payment_id") or "").strip()
    razorpay_signature = (data.get("razorpay_signature") or "").strip()
    req_order_id = data.get("order_id") or order_id

    # Validation: missing fields
    if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
        return jsonify({
            "success": False,
            "message": "Missing required parameters: razorpay_order_id, razorpay_payment_id, and razorpay_signature are required."
        }), 400

    # 1. Cryptographic HMAC-SHA256 signature verification
    is_valid, err_msg = verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature)
    if not is_valid:
        app.logger.warning(f"Payment signature failed: {err_msg}")
        return jsonify({
            "success": False,
            "message": "Payment signature verification failed. Untrusted response."
        }), 400

    # 2. Match local Order (if present)
    order = None
    if req_order_id:
        try:
            order = db.session.get(Order, int(req_order_id)) if hasattr(db.session, "get") else Order.query.get(int(req_order_id))
        except (ValueError, TypeError):
            pass
    if not order and razorpay_order_id:
        order = Order.query.filter_by(razorpay_order_id=razorpay_order_id).first()

    # 3. If local order exists, atomically capture payment and confirm
    if order:
        payment_details = fetch_payment_details(razorpay_payment_id)
        success, capture_msg = capture_order_payment(
            order=order,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_order_id=razorpay_order_id,
            razorpay_signature=razorpay_signature,
            payment_details=payment_details
        )
        if not success:
            return jsonify({"success": False, "message": capture_msg}), 400

        accessible_orders = session.get("authorized_order_ids", [])
        if order.id not in accessible_orders:
            session["authorized_order_ids"] = (accessible_orders + [order.id])[-20:]
            session.modified = True

        redirect_url = url_for("order_success", order_id=order.id)
    else:
        redirect_url = url_for("home")

    return jsonify({
        "success": True,
        "message": "Payment verified and order confirmed.",
        "order_id": order.id if order else None,
        "razorpay_payment_id": razorpay_payment_id,
        "redirect_url": redirect_url
    }), 200


@app.route("/api/webhooks/razorpay", methods=["POST"])
@app.route("/api/webhook/razorpay", methods=["POST"])
def api_razorpay_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    success, msg, status_code = process_webhook_payload(raw_body, signature)
    return jsonify({"success": success, "message": msg}), status_code


@app.route("/payment-failed/<int:order_id>", methods=["POST"])
def payment_failed(order_id):
    order = Order.query.get_or_404(order_id)
    if not _can_access_order(order):
        return jsonify({"success": False}), 404
    data = request.get_json(silent=True) or {}
    error_code = data.get("code") or data.get("error_code")
    error_desc = data.get("description") or data.get("reason") or data.get("error_description")
    device = data.get("device")
    env = "test" if os.environ.get("RAZORPAY_KEY_ID", "").startswith("rzp_test_") else "live"

    if order.status != "Confirmed" and not order.razorpay_payment_id:
        order.status = "Payment Failed"
        if error_code:
            order.payment_error_code = str(error_code)[:100]
        if error_desc:
            order.payment_error_desc = str(error_desc)
        if device:
            order.payment_device = str(device)[:50]
        order.payment_environment = env
        db.session.commit()
    return jsonify({"success": True})


# =========================================
# ORDER SUCCESS
# =========================================

@app.route(
    "/order-success/<int:order_id>"
)
def order_success(order_id):
    order = Order.query.get_or_404(
        order_id
    )
    if not _can_access_order(order):
        return "Not found", 404
    if order.status not in {"Confirmed", "Payment Verification Required", "COD Pending"}:
        return redirect(url_for("view_payment_step", order_id=order.id))

    import urllib.parse
    wa_lines = [
        "Namaste Tulsa Wears! 🌸",
        "",
        "I have submitted an order on your website:",
        f"• Order ID: #{order.id}",
        f"• Tracking ID: {order.tracking_id or 'TW-TRACK-' + str(order.id)}",
        f"• Status: {order.status}",
        f"• Garment: {order.product_name}",
        f"• Total Amount: ₹{order.price:,.0f}",
        f"• Payment Method: {order.payment_method or 'UPI'}",
        f"• Payment UTR / Ref: {order.upi_utr or 'Submitted in app'}",
        f"• Advance Paid: ₹{order.advance_paid:,.0f}",
        f"• Balance Due on Delivery: ₹{order.balance_due:,.0f}",
        f"• Address: {order.address}, {order.city} - {order.pincode}",
        "",
        "I have attached my payment screenshot for priority 1-2 hr verification. Please approve and confirm my order!"
    ]
    wa_message = urllib.parse.quote("\n".join(wa_lines))
    whatsapp_url = f"https://wa.me/919350439667?text={wa_message}"

    return render_template(
        "order-success.html",
        order=order,
        whatsapp_url=whatsapp_url
    )


# =========================================
# RETURN & REFUND POLICY
# =========================================

@app.route("/return-policy")
def return_policy():
    return render_template("return-policy.html")


# =========================================
# CUSTOMER AUTHENTICATION (REGISTER / LOGIN / LOGOUT)
# =========================================

# =========================================
# CUSTOMER AUTHENTICATION & AMAZON-LIKE ACCOUNT
# =========================================

CUSTOMER_RATE_LIMITS = {}  # key -> [timestamps]

def check_customer_rate_limit(key: str, max_requests: int = 6, window_seconds: int = 300) -> bool:
    now = time.time()
    timestamps = CUSTOMER_RATE_LIMITS.setdefault(key, [])
    CUSTOMER_RATE_LIMITS[key] = [t for t in timestamps if now - t < window_seconds]
    if len(CUSTOMER_RATE_LIMITS[key]) >= max_requests:
        return False
    CUSTOMER_RATE_LIMITS[key].append(now)
    return True

def generate_captcha_challenge():
    n1 = random.randint(3, 11)
    n2 = random.randint(2, 9)
    ans = str(n1 + n2)
    expiry = str(int(time.time()) + 600)
    salt = secrets.token_hex(4)
    raw = f"{ans}:{expiry}:{salt}".encode("utf-8")
    sig = hmac.new(app.config["SECRET_KEY"].encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return f"{n1} + {n2} = ?", f"{sig}:{expiry}:{salt}"

def verify_captcha_challenge(answer: str, token: str) -> bool:
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        sig, expiry, salt = parts
        if time.time() > int(expiry):
            return False
        raw = f"{answer.strip()}:{expiry}:{salt}".encode("utf-8")
        expected_sig = hmac.new(app.config["SECRET_KEY"].encode("utf-8"), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False

def customer_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("customer_id"):
            if request.is_json:
                return jsonify({"success": False, "message": "Please sign in to access your account.", "redirect": url_for("customer_login")}), 401
            return redirect(url_for("customer_login", next=request.url))
        customer = db.session.get(CustomerUser, session["customer_id"])
        if not customer:
            session.pop("customer_id", None)
            session.pop("customer_name", None)
            session.pop("customer_phone", None)
            if request.is_json:
                return jsonify({"success": False, "message": "Session expired.", "redirect": url_for("customer_login")}), 401
            return redirect(url_for("customer_login", next=request.url))
        return view(customer, *args, **kwargs)
    return wrapped

def _establish_customer_session(customer):
    guest_cart = session.get("cart", [])
    saved_cart = []
    if getattr(customer, "saved_cart_json", None):
        try:
            saved_cart = json.loads(customer.saved_cart_json)
        except Exception:
            saved_cart = []

    merged_cart = list(saved_cart)
    seen_keys = {(item.get("product_id") or item.get("id"), item.get("size")) for item in merged_cart}
    for g_item in guest_cart:
        k = (g_item.get("product_id") or g_item.get("id"), g_item.get("size"))
        if k not in seen_keys:
            merged_cart.append(g_item)
            seen_keys.add(k)

    session["cart"] = merged_cart
    session["customer_id"] = customer.id
    session["customer_name"] = customer.name
    session["customer_phone"] = customer.phone
    session["customer_email"] = customer.email
    session["csrf_token"] = session.get("csrf_token") or secrets.token_urlsafe(32)

    try:
        customer.saved_cart_json = json.dumps(merged_cart)
        customer.last_login = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()

@app.route("/api/captcha/generate")
def api_captcha_generate():
    q, token = generate_captcha_challenge()
    return jsonify({"question": q, "token": token})

@app.route("/customer/register", methods=["GET", "POST"])
def customer_register():
    if request.method == "GET":
        if session.get("customer_id"):
            return redirect(url_for("customer_account_dashboard"))
        return render_template("customer_auth.html", initial_tab="register")

    data = request.get_json(silent=True) or request.form.to_dict()
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()

    if not name or not phone:
        if request.is_json:
            return jsonify({"success": False, "message": "Name and mobile number are required."}), 400
        flash("Name and mobile number are required.", "danger")
        return redirect(url_for("customer_register"))

    is_valid_phone, clean_phone = validate_indian_phone(phone)
    if is_valid_phone:
        phone = clean_phone

    existing = CustomerUser.query.filter_by(phone=phone).first()
    if existing:
        if request.is_json:
            return jsonify({"success": False, "message": "An account already exists with this phone number. Please sign in."}), 409
        flash("An account already exists with this phone number. Please sign in.", "danger")
        return redirect(url_for("customer_login"))

    new_cust = CustomerUser(name=name, phone=phone, email=email or None, is_verified=True)
    if password:
        new_cust.set_password(password)
    db.session.add(new_cust)
    db.session.commit()

    _establish_customer_session(new_cust)

    if request.is_json:
        return jsonify({"success": True, "message": "Account created successfully.", "redirect": url_for("customer_account_dashboard")})
    flash("Welcome to Tulsa! Your account has been created.", "success")
    return redirect(url_for("customer_account_dashboard"))

@app.route("/api/customer/register-initiate", methods=["POST"])
def api_customer_register_initiate():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    email = data.get("email", "").strip()
    captcha_answer = data.get("captcha_answer", "").strip()
    captcha_token = data.get("captcha_token", "").strip()

    ip = request.remote_addr or "unknown"
    if not check_customer_rate_limit(f"reg_init:{ip}", max_requests=8, window_seconds=300):
        return jsonify({"success": False, "message": "Too many attempts. Please try again in 5 minutes."}), 429

    if not verify_captcha_challenge(captcha_answer, captcha_token):
        return jsonify({"success": False, "message": "Incorrect human verification answer. Please try again."}), 400

    if not name or not phone:
        return jsonify({"success": False, "message": "Name and phone number are required."}), 400

    is_valid, clean_phone = validate_indian_phone(phone)
    if is_valid:
        phone = clean_phone

    existing = CustomerUser.query.filter_by(phone=phone).first()
    if existing and existing.is_verified:
        return jsonify({"success": False, "message": "An account already exists with this phone number. Please sign in."}), 409

    otp = f"{random.randint(100000, 999999)}"
    expiry = datetime.utcnow() + timedelta(minutes=5)

    if not existing:
        user = CustomerUser(name=name, phone=phone, email=email or None, is_verified=False)
        db.session.add(user)
    else:
        user = existing
        user.name = name
        if email:
            user.email = email

    user.otp_code = otp
    user.otp_expiry = expiry
    user.otp_attempts = 0
    user.otp_last_sent = datetime.utcnow()
    db.session.commit()

    app.logger.info(f"[TULSA_AUTH_OTP] Sent 6-digit OTP {otp} to {phone}")
    return jsonify({"success": True, "requires_otp": True, "message": "Verification code dispatched.", "phone": phone})

@app.route("/api/customer/login-initiate", methods=["POST"])
def api_customer_login_initiate():
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier", "").strip()
    password = data.get("password", "").strip()
    use_otp = data.get("use_otp", False)

    if not identifier:
        return jsonify({"success": False, "message": "Phone number or email is required."}), 400

    ip = request.remote_addr or "unknown"
    if not check_customer_rate_limit(f"login_init:{ip}", max_requests=10, window_seconds=300):
        return jsonify({"success": False, "message": "Too many login attempts. Please wait a few minutes."}), 429

    customer = CustomerUser.query.filter_by(phone=identifier).first()
    if not customer:
        is_valid, clean_phone = validate_indian_phone(identifier)
        if is_valid:
            customer = CustomerUser.query.filter_by(phone=clean_phone).first()
    if not customer and "@" in identifier:
        customer = CustomerUser.query.filter_by(email=identifier).first()

    if not customer:
        return jsonify({"success": False, "message": "No registered Tulsa account found. Please register."}), 404

    if use_otp or not password:
        otp = f"{random.randint(100000, 999999)}"
        customer.otp_code = otp
        customer.otp_expiry = datetime.utcnow() + timedelta(minutes=5)
        customer.otp_attempts = 0
        customer.otp_last_sent = datetime.utcnow()
        db.session.commit()
        app.logger.info(f"[TULSA_AUTH_OTP] Sent OTP {otp} to {customer.phone}")
        return jsonify({"success": True, "requires_otp": True, "phone": customer.phone})
    else:
        if not customer.check_password(password):
            return jsonify({"success": False, "message": "Incorrect password. You can also sign in with OTP."}), 401
        _establish_customer_session(customer)
        return jsonify({"success": True, "requires_otp": False, "message": f"Welcome back, {customer.name}!"})

@app.route("/api/customer/verify-otp", methods=["POST"])
def api_customer_verify_otp():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()
    code = data.get("otp_code", "").strip()

    if not phone or not code:
        return jsonify({"success": False, "message": "Phone and 6-digit code are required."}), 400

    customer = CustomerUser.query.filter_by(phone=phone).first()
    if not customer:
        is_valid, clean_phone = validate_indian_phone(phone)
        if is_valid:
            customer = CustomerUser.query.filter_by(phone=clean_phone).first()

    if not customer:
        return jsonify({"success": False, "message": "Account not found."}), 404

    customer.otp_attempts = (customer.otp_attempts or 0) + 1
    if customer.otp_attempts > 6:
        db.session.commit()
        return jsonify({"success": False, "message": "Too many incorrect attempts. Please request a new code."}), 429

    if not customer.otp_code or not customer.otp_expiry:
        return jsonify({"success": False, "message": "No active code. Please request a new code."}), 400

    if datetime.utcnow() > customer.otp_expiry:
        return jsonify({"success": False, "message": "Verification code expired. Please request a new code."}), 400

    if customer.otp_code != code:
        db.session.commit()
        return jsonify({"success": False, "message": "Incorrect verification code. Please try again."}), 400

    customer.is_verified = True
    customer.otp_code = None
    customer.otp_expiry = None
    customer.otp_attempts = 0
    db.session.commit()

    _establish_customer_session(customer)
    return jsonify({"success": True, "message": "Authentication successful.", "redirect": url_for("customer_account_dashboard")})

@app.route("/api/customer/resend-otp", methods=["POST"])
def api_customer_resend_otp():
    data = request.get_json(silent=True) or {}
    phone = data.get("phone", "").strip()

    if not phone:
        return jsonify({"success": False, "message": "Phone number is required."}), 400

    customer = CustomerUser.query.filter_by(phone=phone).first()
    if not customer:
        is_valid, clean_phone = validate_indian_phone(phone)
        if is_valid:
            customer = CustomerUser.query.filter_by(phone=clean_phone).first()

    if not customer:
        return jsonify({"success": False, "message": "Account not found."}), 404

    now = datetime.utcnow()
    if customer.otp_last_sent and (now - customer.otp_last_sent).total_seconds() < 55:
        remaining = 60 - int((now - customer.otp_last_sent).total_seconds())
        return jsonify({"success": False, "message": f"Please wait {remaining} seconds before resending."}), 429

    otp = f"{random.randint(100000, 999999)}"
    customer.otp_code = otp
    customer.otp_expiry = now + timedelta(minutes=5)
    customer.otp_attempts = 0
    customer.otp_last_sent = now
    db.session.commit()

    app.logger.info(f"[TULSA_AUTH_OTP] Resent OTP {otp} to {customer.phone}")
    return jsonify({"success": True, "message": "A new verification code has been dispatched."})

@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    if request.method == "GET":
        if session.get("customer_id"):
            return redirect(url_for("customer_account_dashboard"))
        return render_template("customer_auth.html", initial_tab="login")

    data = request.get_json(silent=True) or request.form.to_dict()
    identifier = (data.get("phone") or data.get("email") or data.get("login_identifier") or "").strip()
    password = (data.get("password") or "").strip()

    if not identifier:
        if request.is_json:
            return jsonify({"success": False, "message": "Phone number or email is required."}), 400
        flash("Phone number or email is required.", "danger")
        return redirect(url_for("customer_login"))

    customer = CustomerUser.query.filter((CustomerUser.phone == identifier) | (CustomerUser.email == identifier)).first()
    if not customer:
        is_valid, clean_phone = validate_indian_phone(identifier)
        if is_valid:
            customer = CustomerUser.query.filter_by(phone=clean_phone).first()

    if not customer or not customer.check_password(password):
        if request.is_json:
            return jsonify({"success": False, "message": "Invalid phone number or password."}), 401
        flash("Invalid phone number or password.", "danger")
        return redirect(url_for("customer_login"))

    _establish_customer_session(customer)
    if request.is_json:
        return jsonify({"success": True, "message": f"Welcome back, {customer.name}!", "redirect": url_for("customer_account_dashboard")})
    flash(f"Welcome back, {customer.name}!", "success")
    return redirect(url_for("customer_account_dashboard"))

@app.route("/customer/logout")
def customer_logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    session.pop("customer_phone", None)
    flash("You have been signed out of your Tulsa account.", "info")
    return redirect(url_for("home"))

# Amazon-like Customer Account Dashboard
@app.route("/account")
@app.route("/customer/dashboard")
@customer_required
def customer_account_dashboard(customer):
    orders = Order.query.filter((Order.customer_id == customer.id) | (Order.phone == customer.phone)).order_by(Order.created_at.desc()).all()
    addresses = CustomerAddress.query.filter_by(customer_id=customer.id).order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at.desc()).all()
    wishlist_items = []
    try:
        from models.customer_wishlist import CustomerWishlist
        wishlist_items = CustomerWishlist.query.filter_by(customer_id=customer.id).order_by(CustomerWishlist.created_at.desc()).all()
    except Exception:
        pass

    return render_template(
        "customer_account.html",
        customer=customer,
        orders=orders,
        addresses=addresses,
        wishlist_items=wishlist_items
    )

@app.route("/account/profile", methods=["POST"])
@customer_required
def customer_profile_update(customer):
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()

    if not name:
        flash("Full name is required.", "danger")
    else:
        customer.name = name
        customer.email = email or None
        db.session.commit()
        session["customer_name"] = name
        flash("Your profile details have been saved.", "success")
    return redirect(url_for("customer_account_dashboard"))

@app.route("/account/address/add", methods=["POST"])
@customer_required
def customer_address_add(customer):
    label = request.form.get("label", "Home").strip()
    recipient = request.form.get("recipient_name", "").strip()
    phone = request.form.get("phone", "").strip()
    address_text = request.form.get("address", "").strip()
    city = request.form.get("city", "").strip()
    pincode = request.form.get("pincode", "").strip()
    is_default = bool(request.form.get("is_default"))

    if not recipient or not phone or not address_text or not city or not pincode:
        flash("Please complete all required address fields.", "danger")
        return redirect(url_for("customer_account_dashboard"))

    if is_default:
        CustomerAddress.query.filter_by(customer_id=customer.id).update({"is_default": False})

    new_addr = CustomerAddress(
        customer_id=customer.id,
        label=label or "Home",
        recipient_name=recipient,
        phone=phone,
        address=address_text,
        city=city,
        pincode=pincode,
        is_default=is_default
    )
    db.session.add(new_addr)
    db.session.commit()
    flash("New delivery address added.", "success")
    return redirect(url_for("customer_account_dashboard"))

@app.route("/account/address/<int:address_id>/delete", methods=["POST"])
@customer_required
def customer_address_delete(customer, address_id):
    addr = CustomerAddress.query.filter_by(id=address_id, customer_id=customer.id).first_or_404()
    db.session.delete(addr)
    db.session.commit()
    flash("Delivery address removed.", "info")
    return redirect(url_for("customer_account_dashboard"))

@app.route("/account/address/<int:address_id>/default", methods=["POST"])
@customer_required
def customer_address_default(customer, address_id):
    addr = CustomerAddress.query.filter_by(id=address_id, customer_id=customer.id).first_or_404()
    CustomerAddress.query.filter_by(customer_id=customer.id).update({"is_default": False})
    addr.is_default = True
    db.session.commit()
    flash(f"Set '{addr.label}' as your default delivery address.", "success")
    return redirect(url_for("customer_account_dashboard"))

@app.route("/account/wishlist/add/<int:product_id>", methods=["POST"])
@customer_required
def customer_wishlist_add(customer, product_id):
    product = Product.query.get_or_404(product_id)
    try:
        from models.customer_wishlist import CustomerWishlist
        existing = CustomerWishlist.query.filter_by(customer_id=customer.id, product_id=product.id).first()
        if not existing:
            db.session.add(CustomerWishlist(customer_id=customer.id, product_id=product.id))
            db.session.commit()
        if request.is_json:
            return jsonify({"success": True, "message": f"{product.name} saved to wishlist."})
        flash(f"Added '{product.name}' to your saved silhouettes.", "success")
    except Exception:
        db.session.rollback()
    return redirect(request.referrer or url_for("customer_account_dashboard"))

@app.route("/account/wishlist/remove/<int:product_id>", methods=["POST"])
@customer_required
def customer_wishlist_remove(customer, product_id):
    try:
        from models.customer_wishlist import CustomerWishlist
        existing = CustomerWishlist.query.filter_by(customer_id=customer.id, product_id=product_id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        if request.is_json:
            return jsonify({"success": True, "message": "Removed from wishlist."})
        flash("Removed from saved silhouettes.", "info")
    except Exception:
        db.session.rollback()
    return redirect(request.referrer or url_for("customer_account_dashboard"))

@app.route("/customer/invoice/<int:order_id>")
@customer_required
def customer_invoice(customer, order_id):
    order = Order.query.filter(Order.id == order_id, (Order.customer_id == customer.id) | (Order.phone == customer.phone)).first_or_404()
    return render_template("admin-invoice.html", order=order)

# AI Customer Support Concierge API
@app.route("/api/customer-support", methods=["POST"])
def api_customer_support():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"message": "How may I assist your styling or shopping journey today?", "products": [], "show_human_handoff": False}), 400

    current_customer = None
    if session.get("customer_id"):
        try:
            current_customer = CustomerUser.query.get(session["customer_id"])
        except Exception:
            pass

    from services.ai_stylist import answer_customer_support
    res = answer_customer_support(query, current_customer=current_customer)
    return jsonify(res)


# =========================================
# ADMIN AUTHENTICATION SETUP
# =========================================

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD) if ADMIN_PASSWORD else None


def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# =========================================
# ADMIN LOGIN & LOGOUT
# =========================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_orders"))

    error = None
    client_ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "127.0.0.1"
    )
    attempt_info = FAILED_ADMIN_LOGINS.get(client_ip, {"count": 0, "lockout_until": 0.0})

    # Check active lockout
    now = time.time()
    if attempt_info["lockout_until"] > now:
        remaining_mins = max(1, int((attempt_info["lockout_until"] - now) / 60) + 1)
        error = f"🔒 Security Lockout Active: Too many failed login attempts. Portal access is locked for {remaining_mins} more minute(s)."
        return render_template("admin-login.html", error=error), 429

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        valid = False
        try:
            admin_user = AdminUser.query.filter_by(username=username).first()
            if admin_user:
                valid = admin_user.check_password(password)
        except Exception:
            pass

        if not valid and ADMIN_PASSWORD_HASH and username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            valid = True

        if valid:
            FAILED_ADMIN_LOGINS.pop(client_ip, None)
            session["admin_authenticated"] = True
            session["admin_user"] = username
            session.permanent = True
            return redirect(url_for("admin_dashboard"))
        else:
            attempt_info["count"] += 1
            if attempt_info["count"] >= 5:
                attempt_info["lockout_until"] = now + 900  # 15 minutes lockout
                FAILED_ADMIN_LOGINS[client_ip] = attempt_info
                error = "🔒 Security Lockout: 5 consecutive failed login attempts detected. Admin access is temporarily locked for 15 minutes."
                return render_template("admin-login.html", error=error), 429
            else:
                remaining = 5 - attempt_info["count"]
                FAILED_ADMIN_LOGINS[client_ip] = attempt_info
                error = f"Invalid username or password. ({remaining} attempt{'s' if remaining > 1 else ''} remaining before security lockout)."

    return render_template("admin-login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_authenticated", None)
    return redirect(url_for("admin_login"))


# =========================================
# ADMIN PORTAL DASHBOARD (CENTRAL MISSION CONTROL)
# =========================================

@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    products = Product.query.order_by(Product.created_at.desc()).all()
    coupons = Coupon.query.all()
    custom_orders = CustomOrder.query.order_by(CustomOrder.created_at.desc()).all()
    inquiries = ContactInquiry.query.order_by(ContactInquiry.created_at.desc()).all()
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).all()

    total_orders = len(orders)
    total_revenue = sum(o.price or 0 for o in orders)
    pending_approval_count = sum(1 for o in orders if o.status and "approval" in o.status.lower())
    confirmed_count = sum(1 for o in orders if o.status and "confirm" in o.status.lower())
    shipped_count = sum(1 for o in orders if o.status and "ship" in o.status.lower())
    delivered_count = sum(1 for o in orders if o.status and "deliver" in o.status.lower())

    low_stock_products = [p for p in products if (p.stock or 0) <= 5]

    recent_orders = orders[:10]
    recent_products = products[:8]

    admin_user = AdminUser.query.first()

    return render_template(
        "admin-dashboard.html",
        admin_user=admin_user,
        total_orders=total_orders,
        total_revenue=total_revenue,
        pending_approval_count=pending_approval_count,
        confirmed_count=confirmed_count,
        shipped_count=shipped_count,
        delivered_count=delivered_count,
        products=products,
        product_count=len(products),
        low_stock_count=len(low_stock_products),
        coupons=coupons,
        coupon_count=len(coupons),
        custom_orders=custom_orders,
        custom_orders_count=len(custom_orders),
        inquiries=inquiries,
        inquiries_count=len(inquiries),
        feedbacks=feedbacks,
        feedback_count=len(feedbacks),
        recent_orders=recent_orders,
        recent_products=recent_products
    )


# =========================================
# ADMIN FORGOT PASSWORD & 2-STEP OTP VERIFICATION
# =========================================

@app.route("/admin/forgot-password", methods=["GET", "POST"])
def admin_forgot_password():
    admin_user = AdminUser.query.first()
    if not admin_user:
        flash("No admin user found.", "danger")
        return redirect(url_for("admin_login"))

    step = request.args.get("step", "select_method")
    error = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "send_otp":
            method = request.form.get("method", "phone")  # 'phone' or 'email'
            otp = f"{random.randint(100000, 999999)}"
            admin_user.reset_otp = otp
            admin_user.reset_otp_expiry = datetime.now() + timedelta(minutes=10)
            db.session.commit()

            session["reset_method"] = method
            session["otp_sent_time"] = time.time()

            if method == "phone":
                flash(f"✓ 6-Digit OTP sent to Permanent Master Phone: +91 93504 39667. (Master Security Code: {otp})", "info")
            else:
                emails_list = [admin_user.studio_email]
                if admin_user.additional_emails:
                    extras = [e.strip() for e in admin_user.additional_emails.split(",") if e.strip()]
                    emails_list.extend(extras)
                flash(f"✓ 6-Digit OTP dispatched to Admin Gmail ({', '.join(emails_list)}). (Master Security Code: {otp})", "info")

            return redirect(url_for("admin_forgot_password", step="verify_otp"))

        elif action == "verify_and_reset":
            submitted_otp = request.form.get("otp", "").strip()
            new_password = request.form.get("new_password", "").strip()
            confirm_password = request.form.get("confirm_password", "").strip()

            if not admin_user.reset_otp or submitted_otp != admin_user.reset_otp:
                error = "Invalid 6-digit OTP code entered. Please check and try again."
                step = "verify_otp"
            elif admin_user.reset_otp_expiry and datetime.now() > admin_user.reset_otp_expiry:
                error = "OTP has expired. Please generate a fresh OTP code."
                step = "select_method"
            elif not new_password or len(new_password) < 4:
                error = "New password must be at least 4 characters long."
                step = "verify_otp"
            elif new_password != confirm_password:
                error = "Passwords do not match. Please re-enter."
                step = "verify_otp"
            else:
                admin_user.set_password(new_password)
                admin_user.reset_otp = None
                admin_user.reset_otp_expiry = None
                db.session.commit()
                flash("✓ Admin password reset successfully! You can now log in with your new password.", "success")
                return redirect(url_for("admin_login"))

    return render_template(
        "admin-forgot-password.html",
        admin_user=admin_user,
        step=step,
        error=error
    )


# =========================================
# ADMIN ORDERS & STATUS MANAGEMENT
# =========================================

@app.route("/admin/payment-proof/<path:filename>")
@admin_required
def serve_payment_proof(filename):
    stored = read_payment_proof(filename)
    if not stored:
        return "Not found", 404
    content, content_type = stored
    response = send_file(io.BytesIO(content), mimetype=content_type, as_attachment=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/admin/orders")
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()

    # Calculate status counts & metrics
    total_orders = len(orders)
    pending_approval_count = sum(1 for o in orders if o.status and "approval" in o.status.lower())
    pending_count = sum(1 for o in orders if o.status and "pending" in o.status.lower() and "approval" not in o.status.lower())
    confirmed_count = sum(1 for o in orders if o.status and "confirm" in o.status.lower())
    processing_count = sum(1 for o in orders if o.status and ("process" in o.status.lower() or "product" in o.status.lower()))
    shipped_count = sum(1 for o in orders if o.status and "ship" in o.status.lower())
    delivered_count = sum(1 for o in orders if o.status and "deliver" in o.status.lower())
    cancelled_count = sum(1 for o in orders if o.status and "cancel" in o.status.lower())

    total_revenue = sum(o.price or 0 for o in orders)
    total_advance = sum(o.advance_paid or 0 for o in orders)
    total_balance = sum(o.balance_due or 0 for o in orders)

    # Traffic & Visitor Analytics
    total_visits = TrafficLog.query.filter_by(event_type="visit").count()
    total_clicks = TrafficLog.query.count()
    total_logins = TrafficLog.query.filter(TrafficLog.event_type.in_(["login", "register"])).count()
    total_customers = CustomerUser.query.count()
    conversion_rate = round((total_orders / max(1, total_visits)) * 100, 1)

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_visits = TrafficLog.query.filter(TrafficLog.timestamp >= today_start).count()
    today_logins = TrafficLog.query.filter(TrafficLog.timestamp >= today_start, TrafficLog.event_type.in_(["login", "register"])).count()

    recent_traffic = TrafficLog.query.order_by(TrafficLog.timestamp.desc()).limit(20).all()

    # Date-based grouping for trend graph
    from collections import defaultdict
    date_counts = defaultdict(int)
    date_revenue = defaultdict(float)

    for o in sorted(orders, key=lambda x: x.created_at if x.created_at else datetime.min):
        if o.created_at:
            d_str = o.created_at.strftime("%d %b")
            date_counts[d_str] += 1
            date_revenue[d_str] += (o.price or 0)

    trend_dates = list(date_counts.keys())
    trend_orders = [date_counts[d] for d in trend_dates]
    trend_revenue = [round(date_revenue[d], 2) for d in trend_dates]

    stats = {
        "total": total_orders,
        "pending_approval": pending_approval_count,
        "pending": pending_count,
        "confirmed": confirmed_count,
        "processing": processing_count,
        "shipped": shipped_count,
        "delivered": delivered_count,
        "cancelled": cancelled_count,
        "total_revenue": total_revenue,
        "total_advance": total_advance,
        "total_balance": total_balance,
        "total_visits": total_visits,
        "total_clicks": total_clicks,
        "total_logins": total_logins,
        "total_customers": total_customers,
        "conversion_rate": conversion_rate,
        "today_visits": today_visits,
        "today_logins": today_logins,
        "trend_dates": trend_dates,
        "trend_orders": trend_orders,
        "trend_revenue": trend_revenue
    }

    return render_template(
        "admin-orders.html",
        orders=orders,
        stats=stats,
        recent_traffic=recent_traffic
    )


@app.route("/admin/orders/quick-approve/<int:order_id>", methods=["POST"])
@admin_required
def admin_quick_approve_order(order_id):
    order = Order.query.get_or_404(order_id)
    if order.status == "Confirmed" and (order.razorpay_payment_id or order.manual_payment_verified_at):
        flash("This payment is already confirmed.", "info")
        return redirect(url_for("admin_orders"))
    flash("An order cannot be marked paid with a quick status change. Verify a Razorpay capture or trusted bank record first.", "warning")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/verify-manual-payment/<int:order_id>", methods=["POST"])
@admin_required
def admin_verify_manual_payment(order_id):
    order = Order.query.get_or_404(order_id)
    if (order.status != "Payment Verification Required" or not order.upi_utr
            or request.form.get("bank_record_checked") != "yes"):
        flash("Confirm that the UTR matches a trusted bank/payment-provider record before verifying.", "danger")
        return redirect(url_for("admin_orders"))
    order.manual_payment_verified_by = session.get("admin_user", "Admin")
    order.manual_payment_verified_at = datetime.utcnow()
    order.status = "Confirmed"
    order.advance_paid = order.price
    order.balance_due = 0.0
    db.session.commit()

    try:
        from services.notification_service import trigger_order_notifications
        trigger_order_notifications(order.id, event_type="order_confirmation", trigger_source="admin_payment_verified")
    except Exception as exc:
        app.logger.error(f"Manual payment verified notification error: {exc}")

    flash(f"Order #{order.id} payment verified against the payment record.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/update-status/<int:order_id>", methods=["POST"])
@admin_required
def admin_update_order_status(order_id):

    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status", "").strip()

    if new_status:
        if new_status == "Confirmed" and not (order.razorpay_payment_id or order.manual_payment_verified_at):
            flash("An unpaid order cannot be marked Confirmed. Verify its Razorpay capture or trusted bank record first.", "danger")
            return redirect(url_for("admin_orders"))
        order.status = new_status
        db.session.commit()

        if new_status in ("Confirmed", "Dispatched", "Out for Delivery", "Delivered"):
            try:
                from services.notification_service import trigger_order_notifications
                trigger_order_notifications(order.id, event_type=f"order_{new_status.lower().replace(' ', '_')}", trigger_source="admin_status_update")
            except Exception as exc:
                app.logger.error(f"Status update notification error: {exc}")

    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/<int:order_id>/resend-notification/<channel>", methods=["POST"])
@admin_required
def admin_resend_order_notification(order_id, channel):
    order = Order.query.get_or_404(order_id)
    if channel not in ("whatsapp", "email"):
        flash("Invalid notification channel.", "danger")
        return redirect(url_for("admin_orders"))

    from services.notification_service import send_whatsapp_order_confirmation, send_email_order_confirmation
    admin_name = session.get("admin_user", "Admin")

    if channel == "whatsapp":
        res = send_whatsapp_order_confirmation(order, event_type="order_confirmation", force_resend=True)
        if res.get("success"):
            flash(f"Order #{order.id} WhatsApp confirmation resent to {order.phone}.", "success")
        else:
            flash(f"WhatsApp resend for Order #{order.id}: {res.get('error') or res.get('message')}", "warning")
    elif channel == "email":
        res = send_email_order_confirmation(order, event_type="order_confirmation", force_resend=True)
        if res.get("success"):
            flash(f"Order #{order.id} confirmation email resent to {order.email}.", "success")
        else:
            flash(f"Email resend for Order #{order.id}: {res.get('error') or res.get('message')}", "warning")

    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/<int:order_id>/notifications", methods=["GET"])
@admin_required
def admin_get_order_notifications(order_id):
    order = Order.query.get_or_404(order_id)
    from models.order_notification import OrderNotification
    notifs = OrderNotification.query.filter_by(order_id=order.id).order_by(OrderNotification.created_at.desc()).all()
    return jsonify({
        "success": True,
        "order_id": order.id,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "email": order.email,
        "whatsapp_opt_in": order.whatsapp_opt_in,
        "delivery_window": f"{order.delivery_window_start} – {order.delivery_window_end}" if order.delivery_window_start else None,
        "notifications": [n.to_dict() for n in notifs]
    })


@app.route("/api/notifications/process-outbox", methods=["POST"])
def api_process_notification_outbox():
    cron_secret = os.getenv("NOTIFICATION_CRON_SECRET", "").strip()
    req_secret = request.headers.get("X-Cron-Secret", "").strip() or request.args.get("secret", "").strip()
    if cron_secret and req_secret != cron_secret:
        return jsonify({"error": "Unauthorized"}), 401

    from services.notification_service import process_pending_notifications
    result = process_pending_notifications()
    return jsonify({"success": True, "result": result})


@app.route("/whatsapp-opt-out", methods=["GET", "POST"])
def whatsapp_opt_out():
    """Customer opt-out route for WhatsApp notifications."""
    phone = request.args.get("phone") or request.form.get("phone")
    order_id = request.args.get("order_id") or request.form.get("order_id")
    opted_out = False

    if request.method == "POST" and phone:
        clean = re.sub(r"\D", "", phone)[-10:]
        orders = Order.query.filter(Order.phone.like(f"%{clean}")).all()
        for o in orders:
            o.whatsapp_opt_in = False
            o.whatsapp_notification_status = "Opted out"
        db.session.commit()
        opted_out = True

    return render_template(
        "whatsapp-opt-out.html",
        phone=phone,
        order_id=order_id,
        opted_out=opted_out
    )


@app.route("/admin/orders/delete/<int:order_id>", methods=["POST"])
@admin_required
def admin_delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    action = request.form.get("action", "archive").strip().lower()
    reason = request.form.get("reason", "Admin action").strip()
    admin_name = session.get("admin_user", "Admin")

    if action == "permanent_delete":
        if not order.can_safely_delete_permanently():
            order.archive(admin_username=admin_name, reason=f"Safe archive: {reason}")
            db.session.commit()
            flash(f"Order #{order_id} has payment/invoice records and was safely archived.", "warning")
            return redirect(url_for("admin_orders"))
        try:
            from models.order_notification import OrderNotification
            from models.production_allocation import ProductionAllocation
            OrderNotification.query.filter_by(order_id=order.id).delete()
            ProductionAllocation.query.filter_by(order_id=order.id).delete()
            db.session.delete(order)
            db.session.commit()
            flash(f"Draft Order #{order_id} was permanently deleted.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Could not delete order: {exc}", "danger")
        return redirect(url_for("admin_orders"))

    # Safe Archive
    order.archive(admin_username=admin_name, reason=reason)
    db.session.commit()
    flash(f"Order #{order_id} safely archived. Historical records remain preserved.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/restore/<int:order_id>", methods=["POST"])
@admin_required
def admin_restore_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.restore()
    db.session.commit()
    flash(f"Order #{order_id} restored to active orders list.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/clear-all", methods=["POST"])
@admin_required
def admin_clear_all_orders():
    Order.query.delete()
    db.session.commit()
    flash("✓ All test orders cleared. Portal is pure, fresh, and at 0 orders.", "info")
    return redirect(url_for("admin_orders"))


# =========================================
# ADMIN & SECURE CUSTOMER ORDER INVOICE
# =========================================

@app.route("/invoice/<int:order_id>")
def public_secure_invoice(order_id):
    from services.notification_service import verify_invoice_token
    token = request.args.get("token", "")
    order = Order.query.get_or_404(order_id)
    is_admin = session.get("admin_authenticated") or session.get("admin_logged_in")
    is_customer_auth = order.id in session.get("authorized_order_ids", [])
    if not (is_admin or is_customer_auth or verify_invoice_token(order.id, token)):
        return "Unauthorized: Invalid or expired invoice access link.", 403
    return render_template("admin-invoice.html", order=order)


@app.route("/admin/orders/invoice/<int:order_id>")
@admin_required
def admin_order_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template("admin-invoice.html", order=order)


@app.route("/admin/orders/export-csv")
@admin_required
def admin_export_orders_csv():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID", "Tracking ID", "Created Date", "Customer Name", "Mobile Phone",
        "Email", "Delivery Address", "City", "PIN Code", "Product Items",
        "Total Price (INR)", "Shipping Fee (INR)", "Shipping Provider", "Shipping Service",
        "Payment Method", "Advance Paid (INR)", "Balance Due (INR)",
        "UPI UTR", "Status", "Size", "Top Length", "Sleeves Length", "Bust", "Waist", "Hip", "Shoulder"
    ])
    for o in orders:
        writer.writerow([
            o.id,
            o.tracking_id or "",
            o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
            o.customer_name or "",
            o.phone or "",
            o.email or "",
            (o.address or "").replace("\n", " "),
            o.city or "",
            o.pincode or "",
            o.product_name or "",
            o.price or 0.0,
            o.shipping_fee or 0.0,
            o.shipping_provider or "",
            o.shipping_service or "",
            o.payment_method or "",
            o.advance_paid or 0.0,
            o.balance_due or 0.0,
            o.upi_utr or "",
            o.status or "",
            o.size or "",
            o.top_length or "",
            o.sleeves_length or "",
            o.bust or "",
            o.waist or "",
            o.hip or "",
            o.shoulder or ""
        ])
    output.seek(0)
    filename = f"tulsa_wears_orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# Compatibility alias
app.add_url_rule("/admin/orders/export-csv-alias", "admin_orders_export_csv", admin_export_orders_csv)


@app.route("/admin/backup-database")
@admin_required
def admin_backup_database():
    db_path = os.path.join(app.root_path, "database", "fashion.db")
    if not os.path.exists(db_path):
        flash("Database file not found on server.", "danger")
        return redirect(url_for("admin_settings"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        db_path,
        as_attachment=True,
        download_name=f"tulsa_wears_backup_{timestamp}.db",
        mimetype="application/x-sqlite3"
    )



# =========================================
# AI STYLE STUDIO / FASHION CONCIERGE API
# =========================================

@app.route("/api/ai-stylist", methods=["POST"])
def api_ai_stylist():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()

    if not query:
        return jsonify({
            "message": "Please share what occasion, fabric, or style you are looking for.",
            "products": []
        }), 400

    result = ask_ai_stylist(query)
    return jsonify(result)


@app.route("/api/ai-product-qa/<int:product_id>", methods=["POST"])
def api_ai_product_qa(product_id):
    product = Product.query.get_or_404(product_id)
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"answer": "Please ask a question about this piece."}), 400

    answer = ask_ai_about_product(product, question)
    return jsonify({"answer": answer})


# =========================================
# CUSTOMER FEEDBACK API
# =========================================

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    try:
        rating = int(data.get("rating", 5) or 5)
    except (ValueError, TypeError):
        rating = 5
    message = data.get("message", "").strip()

    if not name or not message:
        if request.is_json:
            return jsonify({"success": False, "message": "Please provide your name and feedback."}), 400
        flash("Please provide your name and feedback.", "warning")
        return redirect(url_for("home"))

    new_feedback = Feedback(
        customer_name=name,
        email=email,
        rating=max(1, min(5, rating)),
        message=message,
        is_approved=False
    )
    db.session.add(new_feedback)
    db.session.commit()

    if request.is_json:
        return jsonify({
            "success": True,
            "message": "Thank you for sharing your experience. Your review will appear on our homepage after studio moderation."
        })
    flash("Thank you! Your feedback has been received and will appear after moderation.", "success")
    return redirect(url_for("home"))


# =========================================
# CUSTOM / MADE-TO-ORDER API
# =========================================

@app.route("/api/custom-order", methods=["POST"])
def api_custom_order():
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    email = data.get("email", "").strip()
    outfit_type = data.get("outfit_type", "").strip()
    fabric_preference = data.get("fabric_preference", "").strip()
    color_preference = data.get("color_preference", "").strip()
    embroidery_preference = data.get("embroidery_preference", "").strip()
    occasion = data.get("occasion", "").strip()
    measurements = data.get("measurements", "").strip()
    notes = data.get("notes", "").strip()

    if not name or not phone or not outfit_type:
        if request.is_json:
            return jsonify({"success": False, "message": "Please provide your name, phone number, and desired outfit type."}), 400
        flash("Please provide your name, phone number, and outfit type.", "warning")
        return redirect(url_for("home"))

    ref_img_name = None
    file = request.files.get("reference_image")
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        ref_img_name = f"custom_ref_{uuid.uuid4().hex[:8]}.{ext}"
        target_dir = os.path.join(app.config["UPLOAD_FOLDER"], "custom_orders")
        os.makedirs(target_dir, exist_ok=True)
        file.save(os.path.join(target_dir, ref_img_name))
    elif data.get("reference_image"):
        ref_img_name = os.path.basename(data.get("reference_image"))

    custom_order = CustomOrder(
        customer_name=name,
        phone=phone,
        email=email,
        outfit_type=outfit_type,
        fabric_preference=fabric_preference,
        color_preference=color_preference,
        embroidery_preference=embroidery_preference,
        occasion=occasion,
        measurements=measurements,
        notes=notes,
        reference_image=ref_img_name,
        status="Inquiry Received"
    )
    db.session.add(custom_order)
    db.session.commit()

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "message": f"Thank you, {name}! Your bespoke inquiry has been received. Our studio will connect with you on WhatsApp ({phone}) within 24 hours."
        })
    flash(f"Thank you, {name}. Your bespoke inquiry has been received.", "success")
    return redirect(url_for("home"))


# =========================================
# TRACK ORDER ROUTE
# =========================================

@app.route("/track-order", methods=["GET", "POST"])
def track_order():
    query = request.args.get("query", "").strip() or request.form.get("query", "").strip()
    order = None
    error = None

    if query:
        clean_q = query.strip()
        order = Order.query.filter(
            (Order.tracking_id.ilike(f"%{clean_q}%")) |
            (Order.phone == clean_q)
        ).order_by(Order.created_at.desc()).first()

        if not order and clean_q.isdigit():
            order = Order.query.get(int(clean_q))

        if not order:
            error = f"No order found matching '{query}'. Please verify your Tracking ID or Phone Number."

    return render_template("track-order.html", order=order, query=query, error=error)


# =========================================
# AI VISUAL SEARCH / STYLE SCANNER API
# =========================================

@app.route("/api/ai-visual-search", methods=["POST"])
def api_ai_visual_search():
    file = request.files.get("photo")
    if not file or not file.filename or not allowed_file(file.filename):
        return jsonify({"success": False, "message": "Please upload a valid image file (.jpg, .jpeg, .png, .webp)."}), 400

    ext = file.filename.rsplit(".", 1)[1].lower()
    safe_filename = f"ai_trend_{uuid.uuid4().hex[:8]}.{ext}"
    ai_dir = os.path.join(app.config["UPLOAD_FOLDER"], "ai_uploads")
    os.makedirs(ai_dir, exist_ok=True)
    file.save(os.path.join(ai_dir, safe_filename))

    trend = TrendUpload(
        image=safe_filename,
        search_query="Style Visual Scan",
        source="AI Concierge"
    )
    db.session.add(trend)
    db.session.commit()

    products = Product.query.order_by(Product.best_seller.desc(), Product.created_at.desc()).limit(3).all()
    matches = [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "image": p.image,
            "category": p.category
        }
        for p in products
    ]

    return jsonify({
        "success": True,
        "filename": safe_filename,
        "image_url": f"/static/images/ai_uploads/{safe_filename}",
        "message": "AI Studio has analyzed your outfit design. Explore matching ready-to-wear pieces below, or request Tulsa Wears artisans to handcraft this exact bespoke design for you!",
        "matches": matches
    })



# =========================================
# ADMIN: CUSTOM ORDERS & FEEDBACK
# =========================================

@app.route("/admin/feedback")
@admin_required
def admin_feedback():
    reviews = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template("admin-feedback.html", reviews=reviews)


@app.route("/admin/feedback/toggle/<int:feedback_id>", methods=["POST"])
@admin_required
def admin_toggle_feedback(feedback_id):
    fb = Feedback.query.get_or_404(feedback_id)
    fb.is_approved = not fb.is_approved
    db.session.commit()
    return redirect(url_for("admin_feedback"))


@app.route("/admin/custom-orders")
@admin_required
def admin_custom_orders():
    custom_orders = CustomOrder.query.order_by(CustomOrder.created_at.desc()).all()
    return render_template("admin-custom-orders.html", custom_orders=custom_orders)


@app.route("/admin/custom-orders/update-status/<int:order_id>", methods=["POST"])
@admin_required
def admin_update_custom_order_status(order_id):
    co = CustomOrder.query.get_or_404(order_id)
    new_status = request.form.get("status", "").strip()
    if new_status:
        co.status = new_status
        db.session.commit()
    return redirect(url_for("admin_custom_orders"))


# =========================================
# ADMIN: PRODUCTS, PRICES & MEDIA MANAGER
# =========================================

def save_product_upload(file, fallback_prefix="prod"):
    """Durable upload helper supporting Vercel Blob with local file fallback."""
    if not file or not file.filename:
        return None
    if os.getenv("PUBLIC_BLOB_READ_WRITE_TOKEN") or (os.getenv("VERCEL") == "1" and os.getenv("BLOB_READ_WRITE_TOKEN")):
        try:
            from services.media_storage import put_public_image
            data = file.read()
            content_type = file.content_type or "image/jpeg"
            url = put_public_image("products", data, content_type=content_type)
            return url
        except Exception as e:
            app.logger.warning(f"Vercel blob upload fallback: {e}")
            file.seek(0)

    if allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "jpg"
        safe_name = f"{fallback_prefix}_{uuid.uuid4().hex[:8]}.{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
        file.save(save_path)
        return safe_name
    return None


@app.route("/admin/products")
@admin_required
def admin_products():
    from services.category_service import PRIMARY_CATEGORIES
    products = Product.query.order_by(Product.created_at.desc()).all()
    categories = PRIMARY_CATEGORIES

    total_value = sum(p.price * (p.stock or 0) for p in products)
    low_stock = sum(1 for p in products if (p.stock or 0) < 5)

    return render_template(
        "admin-products.html",
        products=products,
        categories=categories,
        total_value=total_value,
        low_stock=low_stock
    )


@app.route("/admin/products/quick-update/<int:product_id>", methods=["POST"])
@admin_required
def admin_quick_update_product(product_id):
    product = Product.query.get_or_404(product_id)

    try:
        new_price = float(request.form.get("price", product.price))
        if new_price > 0:
            product.price = new_price
    except (ValueError, TypeError):
        pass

    try:
        new_stock = int(request.form.get("stock", product.stock))
        if new_stock >= 0:
            product.stock = new_stock
    except (ValueError, TypeError):
        pass

    product.best_seller = bool(request.form.get("best_seller"))
    db.session.commit()

    flash(f"Updated '{product.name}' — Price: ₹{product.price:,.0f}, Stock: {product.stock}.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/update-image/<int:product_id>", methods=["POST"])
@admin_required
def admin_update_product_image(product_id):
    product = Product.query.get_or_404(product_id)
    file = request.files.get("image")

    if file and file.filename and allowed_file(file.filename):
        saved = save_product_upload(file, fallback_prefix=f"prod_{product.id}")
        if saved:
            product.image = saved
            first_gallery = ProductImage.query.filter_by(product_id=product.id, sort_order=0).first()
            if first_gallery:
                first_gallery.image_url = saved
            else:
                db.session.add(ProductImage(product_id=product.id, image_url=saved, sort_order=0))
            db.session.commit()
            flash(f"Uploaded new photograph for '{product.name}'.", "success")
        else:
            flash("Image upload failed.", "danger")
    else:
        flash("Please choose a valid image file (.jpg, .jpeg, .png, .webp, .avif).", "warning")

    return redirect(url_for("admin_products"))


@app.route("/admin/products/add", methods=["POST"])
@admin_required
def admin_add_product():
    from services.category_service import resolve_canonical_category
    from models.product_category import ProductCategory

    name = request.form.get("name", "").strip()
    primary_category = resolve_canonical_category(request.form.get("category", "Palazzo Set").strip())
    
    # Alternative categories
    cat2 = request.form.get("category_2", "").strip()
    cat3 = request.form.get("category_3", "").strip()
    cat4 = request.form.get("category_4", "").strip()

    cat2_resolved = resolve_canonical_category(cat2) if cat2 else None
    cat3_resolved = resolve_canonical_category(cat3) if cat3 else None
    cat4_resolved = resolve_canonical_category(cat4) if cat4 else None

    # Avoid duplicate category assignments
    unique_alts = []
    for c in [cat2_resolved, cat3_resolved, cat4_resolved]:
        if c and c != primary_category and c not in unique_alts:
            unique_alts.append(c)

    alt1 = unique_alts[0] if len(unique_alts) > 0 else None
    alt2 = unique_alts[1] if len(unique_alts) > 1 else None
    alt3 = unique_alts[2] if len(unique_alts) > 2 else None

    fabric = request.form.get("fabric", "").strip()
    color = request.form.get("color", "").strip()
    description = request.form.get("description", "").strip()
    best_seller = bool(request.form.get("best_seller"))

    try:
        price = float(request.form.get("price", 1500))
    except (ValueError, TypeError):
        price = 1500.0

    original_price_raw = request.form.get("original_price")
    try:
        original_price = float(original_price_raw) if original_price_raw and float(original_price_raw) > 0 else None
    except (ValueError, TypeError):
        original_price = None

    discount_percent_raw = request.form.get("discount_percent")
    try:
        discount_percent = int(discount_percent_raw) if discount_percent_raw and int(discount_percent_raw) > 0 else None
    except (ValueError, TypeError):
        discount_percent = None

    if original_price and original_price > price and not discount_percent:
        discount_percent = int(round(((original_price - price) / original_price) * 100))

    try:
        stock = int(request.form.get("stock", 10))
    except (ValueError, TypeError):
        stock = 10

    try:
        weight_kg = float(request.form.get("weight_kg", 0.5))
    except (ValueError, TypeError):
        weight_kg = 0.5

    try:
        length_cm = float(request.form.get("length_cm", 30.0))
    except (ValueError, TypeError):
        length_cm = 30.0

    try:
        width_cm = float(request.form.get("width_cm", 25.0))
    except (ValueError, TypeError):
        width_cm = 25.0

    try:
        height_cm = float(request.form.get("height_cm", 5.0))
    except (ValueError, TypeError):
        height_cm = 5.0

    if not name:
        flash("Please enter a name for the new garment.", "warning")
        return redirect(url_for("admin_products"))

    primary_image_file = request.files.get("image")
    saved_primary = save_product_upload(primary_image_file, fallback_prefix="prod") if primary_image_file else None
    image_filename = saved_primary or "product-1.jpg"

    new_product = Product(
        name=name,
        price=price,
        original_price=original_price,
        discount_percent=discount_percent,
        category=primary_category,
        category_2=alt1,
        category_3=alt2,
        category_4=alt3,
        fabric=fabric or "Handwoven Cotton",
        color=color or "Natural",
        description=description or "A bespoke handcrafted garment created slowly by atelier artisans.",
        image=image_filename,
        stock=stock,
        best_seller=best_seller,
        weight_kg=weight_kg,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm
    )
    db.session.add(new_product)
    db.session.flush()

    # Create primary gallery image record
    if saved_primary:
        db.session.add(ProductImage(product_id=new_product.id, image_url=saved_primary, sort_order=0))

    # Add any additional gallery images
    gallery_files = request.files.getlist("gallery_images")
    if gallery_files:
        current_sort = 1
        for gfile in gallery_files:
            if gfile and gfile.filename and allowed_file(gfile.filename):
                saved_gallery = save_product_upload(gfile, fallback_prefix=f"prod_{new_product.id}_gallery")
                if saved_gallery:
                    db.session.add(ProductImage(product_id=new_product.id, image_url=saved_gallery, sort_order=current_sort))
                    current_sort += 1

    # Populate normalized product_categories table
    db.session.add(ProductCategory(product_id=new_product.id, category=primary_category, is_primary=True))
    for alt_cat in [alt1, alt2, alt3]:
        if alt_cat:
            db.session.add(ProductCategory(product_id=new_product.id, category=alt_cat, is_primary=False))

    db.session.commit()

    flash(f"Added '{name}' (₹{price:,.0f}) to the atelier catalog.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):
    from services.category_service import PRIMARY_CATEGORIES, resolve_canonical_category
    from models.product_category import ProductCategory

    product = Product.query.get_or_404(product_id)

    if request.method == "GET":
        return render_template(
            "admin-product-edit.html",
            product=product,
            categories=PRIMARY_CATEGORIES
        )

    # POST: Save changes
    name = request.form.get("name", "").strip()
    if name:
        product.name = name

    try:
        price = float(request.form.get("price", product.price))
        if price > 0:
            product.price = price
    except (ValueError, TypeError):
        pass

    original_price_raw = request.form.get("original_price")
    try:
        product.original_price = float(original_price_raw) if original_price_raw and float(original_price_raw) > 0 else None
    except (ValueError, TypeError):
        product.original_price = None

    discount_percent_raw = request.form.get("discount_percent")
    try:
        product.discount_percent = int(discount_percent_raw) if discount_percent_raw and int(discount_percent_raw) > 0 else None
    except (ValueError, TypeError):
        product.discount_percent = None

    if product.original_price and product.original_price > product.price and not product.discount_percent:
        product.discount_percent = int(round(((product.original_price - product.price) / product.original_price) * 100))

    try:
        stock = int(request.form.get("stock", product.stock))
        if stock >= 0:
            product.stock = stock
    except (ValueError, TypeError):
        pass

    if request.form.get("weight_kg"):
        try:
            product.weight_kg = float(request.form.get("weight_kg"))
        except (ValueError, TypeError):
            pass
    if request.form.get("length_cm"):
        try:
            product.length_cm = float(request.form.get("length_cm"))
        except (ValueError, TypeError):
            pass
    if request.form.get("width_cm"):
        try:
            product.width_cm = float(request.form.get("width_cm"))
        except (ValueError, TypeError):
            pass
    if request.form.get("height_cm"):
        try:
            product.height_cm = float(request.form.get("height_cm"))
        except (ValueError, TypeError):
            pass

    # Category and Multi-Category Handling
    primary_category = resolve_canonical_category(request.form.get("category", product.category).strip())
    product.category = primary_category

    cat2 = request.form.get("category_2", "").strip()
    cat3 = request.form.get("category_3", "").strip()
    cat4 = request.form.get("category_4", "").strip()

    cat2_resolved = resolve_canonical_category(cat2) if cat2 else None
    cat3_resolved = resolve_canonical_category(cat3) if cat3 else None
    cat4_resolved = resolve_canonical_category(cat4) if cat4 else None

    unique_alts = []
    for c in [cat2_resolved, cat3_resolved, cat4_resolved]:
        if c and c != primary_category and c not in unique_alts:
            unique_alts.append(c)

    product.category_2 = unique_alts[0] if len(unique_alts) > 0 else None
    product.category_3 = unique_alts[1] if len(unique_alts) > 1 else None
    product.category_4 = unique_alts[2] if len(unique_alts) > 2 else None

    product.fabric = request.form.get("fabric", product.fabric).strip()
    product.color = request.form.get("color", product.color).strip()
    product.description = request.form.get("description", product.description).strip()
    product.best_seller = bool(request.form.get("best_seller"))

    # Replace primary image if provided
    file = request.files.get("image")
    if file and file.filename and allowed_file(file.filename):
        saved = save_product_upload(file, fallback_prefix=f"prod_{product.id}")
        if saved:
            product.image = saved
            first_gallery = ProductImage.query.filter_by(product_id=product.id, sort_order=0).first()
            if first_gallery:
                first_gallery.image_url = saved
            else:
                db.session.add(ProductImage(product_id=product.id, image_url=saved, sort_order=0))

    # Add new gallery photos
    gallery_files = request.files.getlist("gallery_images")
    if gallery_files:
        existing_count = ProductImage.query.filter_by(product_id=product.id).count()
        current_sort = existing_count
        for gfile in gallery_files:
            if gfile and gfile.filename and allowed_file(gfile.filename):
                saved_gallery = save_product_upload(gfile, fallback_prefix=f"prod_{product.id}_gallery")
                if saved_gallery:
                    db.session.add(ProductImage(product_id=product.id, image_url=saved_gallery, sort_order=current_sort))
                    current_sort += 1

    # Sync ProductCategory records
    ProductCategory.query.filter_by(product_id=product.id).delete()
    db.session.add(ProductCategory(product_id=product.id, category=primary_category, is_primary=True))
    for alt_cat in [product.category_2, product.category_3, product.category_4]:
        if alt_cat:
            db.session.add(ProductCategory(product_id=product.id, category=alt_cat, is_primary=False))

    db.session.commit()
    flash(f"Garment details and collection placements updated for '{product.name}'.", "success")
    return redirect(url_for("admin_edit_product", product_id=product.id))


@app.route("/admin/products/<int:product_id>/gallery/<int:image_id>/delete", methods=["POST"])
@admin_required
def admin_delete_product_gallery_image(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    img = ProductImage.query.filter_by(id=image_id, product_id=product.id).first_or_404()
    db.session.delete(img)
    db.session.commit()
    flash("Gallery photo removed.", "info")
    return redirect(url_for("admin_edit_product", product_id=product.id))


@app.route("/admin/products/<int:product_id>/gallery/<int:image_id>/set-primary", methods=["POST"])
@admin_required
def admin_set_primary_gallery_image(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    img = ProductImage.query.filter_by(id=image_id, product_id=product.id).first_or_404()
    product.image = img.image_url
    img.sort_order = 0
    db.session.commit()
    flash("Primary cover photo updated.", "success")
    return redirect(url_for("admin_edit_product", product_id=product.id))



@app.route("/admin/products/delete/<int:product_id>", methods=["POST"])
@admin_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    name = product.name
    db.session.delete(product)
    db.session.commit()

    flash(f"Removed '{name}' from the atelier collection.", "info")
    return redirect(url_for("admin_products"))


@app.route("/admin/upload-section-image", methods=["POST"])
@admin_required
def admin_upload_section_image():
    section = request.form.get("section", "").strip().lower()
    file = request.files.get("section_image")

    if not file or not file.filename or not allowed_file(file.filename):
        flash("Please select a valid image file (.jpg, .jpeg, .png, .webp).", "warning")
        return redirect(url_for("admin_products"))

    filename_map = {
        "hero": "hero-new.jpg",
        "collection": "collection.jpg",
        "designer": "designer.jpg"
    }

    target_name = filename_map.get(section)
    if not target_name:
        flash("Unknown homepage section specified.", "warning")
        return redirect(url_for("admin_products"))

    save_path = os.path.join(app.config["UPLOAD_FOLDER"], target_name)
    file.save(save_path)

    flash(f"Successfully replaced photo for homepage {section.capitalize()} section!", "success")
    return redirect(url_for("admin_products"))


# =========================================
# ADMIN: WEBSITE MANAGEMENT & CMS STUDIO (10 SECTIONS)
# =========================================

@app.route("/admin/website-management", methods=["GET", "POST"])
@app.route("/admin/customizer", methods=["GET", "POST"])
@admin_required
def admin_customizer():
    cms = get_site_content(preview_draft=True)

    if request.method == "POST":
        data = request.form.to_dict()

        # Handle image removal request if specified
        remove_image_key = request.form.get("remove_image_key")
        if remove_image_key and remove_image_key in cms:
            cms[remove_image_key] = ""
            save_site_content(cms, publish=False)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
                return jsonify({"status": "success", "message": f"Image removed from {remove_image_key}.", "cms": cms})
            flash(f"Image reference removed from section. The shared file was preserved.", "info")
            return redirect(url_for("admin_customizer"))

        for k in list(data.keys()):
            if k.startswith("remove_image_") and k != "remove_image_key":
                target_key = k[len("remove_image_"):]
                if target_key in cms:
                    cms[target_key] = ""

        # Update text values from form
        for key, value in data.items():
            if key not in {"action", "editor_sections_json", "custom_sections_json", "editor_accent", "editor_background", "editor_heading_font", "editor_section_spacing", "remove_image_key"} and not key.endswith("_file"):
                cms[key] = value.strip()

        if "editor_sections_json" in data:
            layout = validate_editor_layout(data.get("editor_sections_json", ""), data.get("custom_sections_json", "[]"))
            if layout is None:
                flash("The section layout was invalid. The saved draft was left unchanged.", "danger")
                return redirect(url_for("admin_customizer"))
            cms["editor_sections"], cms["custom_sections"] = layout
        cms["editor_theme"] = validate_editor_theme(
            data.get("editor_accent", cms.get("editor_theme", {}).get("accent", "#C9A96E")),
            data.get("editor_background", cms.get("editor_theme", {}).get("background", "#F7F4EF")),
            data.get("editor_heading_font", cms.get("editor_theme", {}).get("heading_font", "Cormorant Garamond")),
            data.get("editor_section_spacing", cms.get("editor_theme", {}).get("section_spacing", 96)),
        )

        # Process image file uploads across all 10 management sections
        image_fields = {
            "hero_image_file": ("hero_image", "hero"),
            "mood_cat1_image_file": ("mood_cat1_image", "mood_cat1"),
            "mood_cat2_image_file": ("mood_cat2_image", "mood_cat2"),
            "mood_cat3_image_file": ("mood_cat3_image", "mood_cat3"),
            "mood_cat4_image_file": ("mood_cat4_image", "mood_cat4"),
            "collection_image_file": ("collection_image", "collection"),
            "bridal_image_file": ("bridal_image", "bridal"),
            "seasonal_img1_file": ("seasonal_img1", "seasonal1"),
            "seasonal_img2_file": ("seasonal_img2", "seasonal2"),
            "seasonal_img3_file": ("seasonal_img3", "seasonal3"),
            "trends_image_file": ("trends_image", "trends"),
            "designer_image_file": ("designer_image", "designer"),
            "lookbook_slide1_image_file": ("lookbook_slide1_image", "lb1"),
            "lookbook_slide2_image_file": ("lookbook_slide2_image", "lb2"),
            "lookbook_slide3_image_file": ("lookbook_slide3_image", "lb3"),
            "lookbook_slide4_image_file": ("lookbook_slide4_image", "lb4"),
            "brand_logo_file": ("brand_logo", "logo"),
        }

        updated_count = 0
        for form_file_key, (cms_key, prefix) in image_fields.items():
            if form_file_key in request.files:
                file_obj = request.files[form_file_key]
                if file_obj and file_obj.filename:
                    saved_filename = process_image_upload(file_obj, app.config["UPLOAD_FOLDER"], prefix=prefix)
                    if saved_filename:
                        cms[cms_key] = saved_filename
                        updated_count += 1

        save_site_content(cms, publish=False)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({
                "status": "success",
                "message": "Draft saved. Publish it when ready.",
                "cms": cms
            })

        flash("Draft saved. Preview it and publish when you are ready.", "success")
        return redirect(url_for("admin_customizer"))

    return render_template(
        "admin-customizer.html",
        cms=cms,
        total_products=Product.query.count(),
        server_host=request.host_url.rstrip("/"),
        revisions=SiteContentRevision.query.order_by(SiteContentRevision.id.desc()).limit(20).all()
    )


@app.route("/admin/customizer/publish", methods=["POST"])
@app.route("/admin/website-management/publish", methods=["POST"])
@admin_required
def admin_customizer_publish():
    if not publish_site_content():
        flash("No saved draft was available to publish.", "danger")
        return redirect(url_for("admin_customizer"))
    cms = get_site_content()
    admin_user = AdminUser.query.first()
    if admin_user:
        admin_user.studio_phone = cms.get("studio_phone", cms.get("contact_phone", admin_user.studio_phone))
        admin_user.studio_whatsapp = cms.get("studio_whatsapp", cms.get("contact_whatsapp", admin_user.studio_whatsapp))
        admin_user.studio_email = cms.get("studio_email", cms.get("contact_email", admin_user.studio_email))
        admin_user.studio_address = cms.get("studio_address", cms.get("contact_address", admin_user.studio_address))
        admin_user.studio_hours = cms.get("studio_hours", cms.get("contact_hours", admin_user.studio_hours))
        db.session.commit()
    flash("The saved storefront draft is now live.", "success")
    return redirect(url_for("admin_customizer"))


@app.route("/admin/customizer/restore/<int:revision>", methods=["POST"])
@admin_required
def admin_customizer_restore(revision):
    snapshot = SiteContentRevision.query.filter_by(revision=revision).first_or_404()
    try:
        save_site_content(json.loads(snapshot.content_json), publish=False)
        flash("Revision restored as a draft. Publish it to make it live.", "success")
    except Exception:
        db.session.rollback()
        flash("That revision could not be restored.", "danger")
    return redirect(url_for("admin_customizer"))


@app.route("/admin/customizer/reset", methods=["POST"])
@admin_required
def admin_customizer_reset():
    reset_site_content(publish=False)
    flash("Factory defaults are saved as a draft. Publish to make them live.", "info")
    return redirect(url_for("admin_customizer"))


# =========================================
# ADMIN: SETTINGS, CREDENTIALS & DELIVERY CONFIG
# =========================================

@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    admin_user = AdminUser.query.first()
    if not admin_user:
        admin_user = AdminUser(username="admin", default_delivery_days=10)
        admin_user.set_password("atelier-admin-2026")
        db.session.add(admin_user)
        db.session.commit()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            new_username = request.form.get("username", "").strip()
            new_days = request.form.get("default_delivery_days", "").strip()

            if new_username:
                admin_user.username = new_username
                session["admin_user"] = new_username

            try:
                if new_days:
                    admin_user.default_delivery_days = max(1, int(new_days))
            except (ValueError, TypeError):
                pass

            db.session.commit()
            flash("Admin username and default delivery timeframe updated successfully.", "success")

        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not admin_user.check_password(current_password):
                flash("Current password entered is incorrect.", "danger")
            elif not new_password or len(new_password) < 4:
                flash("New password must be at least 4 characters long.", "warning")
            elif new_password != confirm_password:
                flash("New passwords do not match.", "warning")
            else:
                admin_user.set_password(new_password)
                db.session.commit()
                flash("Password successfully changed! Please use your new password next time you log in.", "success")

        elif action == "update_payment_settings":
            upi_id = request.form.get("upi_id", "").strip()
            upi_payee_name = request.form.get("upi_payee_name", "").strip()

            admin_user.upi_id = upi_id
            admin_user.upi_payee_name = upi_payee_name or "Tulsa Wears"
            db.session.commit()
            flash("UPI display settings saved. Razorpay credentials are read only from server environment variables.", "success")

        elif action == "update_shipping_settings":
            admin_user.warehouse_pincode = request.form.get("warehouse_pincode", "125033").strip()
            admin_user.warehouse_city = request.form.get("warehouse_city", "Hansi").strip()
            admin_user.warehouse_state = request.form.get("warehouse_state", "Haryana").strip()
            admin_user.warehouse_address = request.form.get("warehouse_address", "Tulsa Wears Atelier, Hansi").strip()
            admin_user.shiprocket_email = request.form.get("shiprocket_email", "").strip()
            if request.form.get("shiprocket_password"):
                admin_user.shiprocket_password = request.form.get("shiprocket_password", "").strip()
            admin_user.shipping_fallback_enabled = request.form.get("shipping_fallback_enabled") == "1"
            try:
                admin_user.shipping_flat_fallback = float(request.form.get("shipping_flat_fallback", 0.0))
            except (ValueError, TypeError):
                admin_user.shipping_flat_fallback = 0.0

            db.session.commit()
            flash("Warehouse origin location & courier logistics settings updated successfully!", "success")

        elif action == "update_contact_settings":
            studio_phone = request.form.get("studio_phone", "").strip()
            studio_whatsapp = request.form.get("studio_whatsapp", "").strip()
            studio_email = request.form.get("studio_email", "").strip()
            studio_address = request.form.get("studio_address", "").strip()
            studio_hours = request.form.get("studio_hours", "").strip()

            admin_user.studio_phone = studio_phone or "+91 93504 39667"
            admin_user.studio_whatsapp = studio_whatsapp or "919350439667"
            admin_user.studio_email = studio_email or "contact@tulsawear.com"
            admin_user.studio_address = studio_address or "Tulsa Wears Atelier, Hansi, Haryana, India - 125033"
            admin_user.studio_hours = studio_hours or "Mon – Sat: 10:00 AM – 7:00 PM IST"
            db.session.commit()
            flash("Studio Contact Information & Atelier details updated successfully!", "success")

        elif action == "update_admin_security":
            additional_emails = request.form.get("additional_emails", "").strip()
            admin_user.additional_emails = additional_emails
            db.session.commit()
            flash("Admin security contacts & additional recovery emails updated successfully!", "success")

        return redirect(url_for("admin_settings"))

    return render_template(
        "admin-settings.html",
        admin_user=admin_user,
        server_host=request.host_url.rstrip("/")
    )


# =========================================
# ADMIN: AI CONCIERGE TREND UPLOADS
# =========================================

@app.route("/admin/trends")
@admin_required
def admin_trends():
    trends = TrendUpload.query.order_by(TrendUpload.created_at.desc()).all()
    return render_template("admin-trends.html", trends=trends)


# =========================================
# CLIENT SERVICES: CONTACT US & INQUIRIES
# =========================================

@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/api/contact", methods=["POST"])
def api_contact():
    try:
        data = request.get_json(silent=True) or request.form
        name = (data.get("name") or "").strip()
        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        subject = (data.get("subject") or "General Inquiry").strip()
        message = (data.get("message") or "").strip()

        if not name or not phone or not message:
            return jsonify({
                "success": False,
                "message": "Please provide your name, phone number, and message."
            }), 400

        inquiry = ContactInquiry(
            customer_name=name,
            phone=phone,
            email=email,
            subject=subject,
            message=message,
            status="New"
        )
        db.session.add(inquiry)
        db.session.commit()

        # WhatsApp prefill link
        admin_user = AdminUser.query.first()
        wa_number = admin_user.studio_whatsapp.replace("+", "").replace(" ", "").replace("-", "") if (admin_user and getattr(admin_user, 'studio_whatsapp', None)) else "919876543210"
        
        wa_text = f"Namaste Tulsa Wears! My name is {name} ({phone}). I have an inquiry regarding '{subject}': {message}"
        wa_link = f"https://wa.me/{wa_number}?text={urllib.parse.quote(wa_text)}"

        return jsonify({
            "success": True,
            "message": f"Thank you {name}! Your message has been received by our atelier. We will contact you shortly.",
            "inquiry_id": inquiry.id,
            "whatsapp_link": wa_link
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": f"Error saving inquiry: {str(e)}"
        }), 500


# =========================================
# ADMIN: CLIENT CONTACT INQUIRIES
# =========================================

@app.route("/admin/inquiries")
@admin_required
def admin_inquiries():
    status_filter = request.args.get("status")
    query = ContactInquiry.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    inquiries = query.order_by(ContactInquiry.created_at.desc()).all()

    total_count = ContactInquiry.query.count()
    new_count = ContactInquiry.query.filter_by(status="New").count()
    in_progress_count = ContactInquiry.query.filter_by(status="In Progress").count()
    resolved_count = ContactInquiry.query.filter_by(status="Resolved").count()

    return render_template(
        "admin-inquiries.html",
        inquiries=inquiries,
        total_count=total_count,
        new_count=new_count,
        in_progress_count=in_progress_count,
        resolved_count=resolved_count,
        current_filter=status_filter
    )


@app.route("/admin/inquiries/<int:inquiry_id>/status", methods=["POST"])
@admin_required
def admin_update_inquiry_status(inquiry_id):
    inquiry = ContactInquiry.query.get_or_404(inquiry_id)
    new_status = request.form.get("status")
    if new_status in ["New", "In Progress", "Resolved"]:
        inquiry.status = new_status
        db.session.commit()
        flash(f"Inquiry #{inquiry.id} updated to '{new_status}'.", "success")
    return redirect(request.referrer or url_for("admin_inquiries"))


@app.route("/admin/inquiries/<int:inquiry_id>/delete", methods=["POST"])
@admin_required
def admin_delete_inquiry(inquiry_id):
    inquiry = ContactInquiry.query.get_or_404(inquiry_id)
    db.session.delete(inquiry)
    db.session.commit()
    flash(f"Inquiry #{inquiry_id} removed.", "success")
    return redirect(url_for("admin_inquiries"))


# =========================================
# PROMOTIONS & COUPONS: API
# =========================================

@app.route("/api/coupon/apply", methods=["POST"])
def api_apply_coupon():
    data = request.get_json(silent=True) or request.form
    code = (data.get("code") or "").strip().upper()

    product_id = data.get("product_id")
    raw_items = []

    if product_id:
        p = Product.query.get(product_id)
        if p:
            raw_items.append({"product": p, "quantity": 1})
    else:
        cart = session.get("cart", [])
        for item in cart:
            p = Product.query.get(item.get("product_id"))
            if p:
                qty = max(1, min(int(item.get("quantity", 1)), p.stock or 999))
                raw_items.append({"product": p, "quantity": qty})

    if not raw_items:
        return jsonify({"success": False, "message": "Your bag is empty."}), 400

    if not code:
        return jsonify({"success": False, "message": "Please enter a promo / coupon code."}), 400

    coupon = Coupon.query.filter_by(code=code, is_active=True).first()
    if not coupon:
        return jsonify({"success": False, "message": f"Coupon code '{code}' is invalid or expired."}), 404

    calc = calculate_bag_and_checkout(raw_items, coupon_obj=coupon, shipping_paise=0)

    if not calc["coupon_valid"]:
        return jsonify({
            "success": False,
            "message": calc["coupon_message"] or f"Coupon '{code}' is not applicable to this order."
        }), 400

    session["applied_coupon"] = {
        "id": coupon.id,
        "code": coupon.code,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "discount_amount": calc["discount_amount"]
    }
    session.modified = True

    return jsonify({
        "success": True,
        "message": f"Coupon '{coupon.code}' applied! You saved ₹{calc['discount_amount']:,.0f}.",
        "coupon_code": coupon.code,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "discount_amount": calc["discount_amount"],
        "subtotal": calc["subtotal"],
        "final_total": calc["total"]
    })


@app.route("/api/coupon/remove", methods=["POST"])
def api_remove_coupon():
    session.pop("applied_coupon", None)
    session.modified = True
    return jsonify({"success": True, "message": "Coupon removed successfully."})


# =========================================
# SHIPPING & COURIER QUOTATION API
# =========================================

@app.route("/api/shipping/quote", methods=["POST"])
def api_shipping_quote():
    data = request.get_json(silent=True) or request.form
    pincode = (data.get("pincode") or "").strip()
    country = (data.get("country") or "India").strip()
    product_id = data.get("product_id")

    raw_items = []
    if product_id:
        p = Product.query.get(product_id)
        if p:
            raw_items.append({"product": p, "quantity": 1})
    else:
        cart = session.get("cart", [])
        for item in cart:
            p = Product.query.get(item.get("product_id"))
            if p:
                raw_items.append({"product": p, "quantity": max(1, int(item.get("quantity", 1)))})

    admin_user = AdminUser.query.first()
    warehouse_info = {
        "pincode": admin_user.warehouse_pincode if (admin_user and admin_user.warehouse_pincode) else DEFAULT_WAREHOUSE["pincode"],
        "city": admin_user.warehouse_city if (admin_user and admin_user.warehouse_city) else DEFAULT_WAREHOUSE["city"],
        "state": admin_user.warehouse_state if (admin_user and admin_user.warehouse_state) else DEFAULT_WAREHOUSE["state"]
    }
    shiprocket_creds = {
        "token": admin_user.shiprocket_token if admin_user else None
    }
    fallback_enabled = bool(admin_user.shipping_fallback_enabled) if admin_user else True
    fallback_amount = float(admin_user.shipping_flat_fallback or 0.0) if admin_user else 0.0

    quote = get_shipping_quote(
        destination_pincode=pincode,
        destination_country=country,
        products_with_qty=raw_items,
        warehouse_info=warehouse_info,
        shiprocket_creds=shiprocket_creds,
        fallback_enabled=fallback_enabled,
        fallback_amount=fallback_amount
    )

    if not quote.get("serviceable"):
        return jsonify({
            "success": False,
            "serviceable": False,
            "message": quote.get("error", "Destination is currently not serviceable.")
        }), 400

    # Also compute new order totals with this shipping fee
    applied_coupon = session.get("applied_coupon")
    coupon_obj = None
    if applied_coupon and applied_coupon.get("code"):
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()

    shipping_fee = float(quote.get("shipping_fee", 0.0))
    calc = calculate_bag_and_checkout(
        raw_items,
        coupon_obj=coupon_obj,
        shipping_paise=to_paise(shipping_fee)
    )

    return jsonify({
        "success": True,
        "serviceable": True,
        "shipping_fee": shipping_fee,
        "rate_rupees": shipping_fee,
        "courier": quote.get("courier") or quote.get("provider"),
        "provider": quote.get("provider"),
        "service": quote.get("service"),
        "estimated_days": quote.get("estimated_days"),
        "subtotal": calc["subtotal"],
        "discount_amount": calc["discount_amount"],
        "final_total": calc["total"]
    })


# =========================================
# ADMIN: COUPONS MANAGEMENT
# =========================================

@app.route("/admin/coupons")
@admin_required
def admin_coupons():
    coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template("admin-coupons.html", coupons=coupons)


@app.route("/admin/coupons/create", methods=["POST"])
@admin_required
def admin_create_coupon():
    code = (request.form.get("code") or "").strip().upper()
    discount_type = request.form.get("discount_type", "percentage").strip().lower()
    try:
        discount_value = float(request.form.get("discount_value") or 0.0)
    except (ValueError, TypeError):
        discount_value = 0.0

    try:
        min_order_amount = float(request.form.get("min_order_amount") or 0.0)
    except (ValueError, TypeError):
        min_order_amount = 0.0

    max_discount_raw = request.form.get("max_discount")
    try:
        max_discount = float(max_discount_raw) if max_discount_raw and max_discount_raw.strip() else None
    except (ValueError, TypeError):
        max_discount = None

    is_active = bool(request.form.get("is_active"))

    if not code:
        flash("Coupon code cannot be empty.", "warning")
        return redirect(url_for("admin_coupons"))

    existing = Coupon.query.filter_by(code=code).first()
    if existing:
        flash(f"Coupon code '{code}' already exists.", "warning")
        return redirect(url_for("admin_coupons"))

    if discount_value <= 0:
        flash("Discount value must be greater than 0.", "warning")
        return redirect(url_for("admin_coupons"))

    coupon = Coupon(
        code=code,
        discount_type=discount_type,
        discount_value=discount_value,
        min_order_amount=min_order_amount,
        max_discount=max_discount,
        is_active=is_active
    )
    db.session.add(coupon)
    db.session.commit()

    flash(f"Coupon '{code}' created and published successfully!", "success")
    return redirect(url_for("admin_coupons"))


@app.route("/admin/coupons/<int:coupon_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    status_str = "activated" if coupon.is_active else "deactivated"
    flash(f"Coupon '{coupon.code}' {status_str}.", "success")
    return redirect(url_for("admin_coupons"))


@app.route("/admin/coupons/<int:coupon_id>/delete", methods=["POST"])
@admin_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    code = coupon.code
    db.session.delete(coupon)
    db.session.commit()
    flash(f"Coupon '{code}' deleted.", "success")
    return redirect(url_for("admin_coupons"))


# =========================================
# CREATE DATABASE TABLES
# =========================================

with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass

    ensure_schema_migrations()


# =========================================
# RUN FLASK
# =========================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5050,
        debug=False
    )
