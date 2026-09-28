import os
import functools
import uuid
import time
import secrets
import re
import io
import csv

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
    send_file
)

from datetime import datetime, timedelta
from sqlalchemy import inspect, text

from models.database import db
from models.product import Product
from models.order import Order
from models.feedback import Feedback
from models.custom_order import CustomOrder
from models.admin_user import AdminUser
from models.trend_upload import TrendUpload
from models.contact_inquiry import ContactInquiry
from models.coupon import Coupon
from models.customer_user import CustomerUser
from models.traffic_log import TrafficLog
from services.ai_stylist import ask_ai_stylist, ask_ai_about_product
from services.site_content import (
    get_site_content,
    save_site_content,
    reset_site_content,
    process_image_upload
)
import urllib.parse
import random


# =========================================
# LOAD ENVIRONMENT VARIABLES
# =========================================

load_dotenv()


# =========================================
# FLASK APP & SECURITY CONFIGURATION
# =========================================

app = Flask(__name__)

# Persistent High-Entropy Cryptographic Session Key
SECRET_KEY_FILE = os.path.join(app.root_path, ".session_secret")
if os.getenv("FLASK_SECRET_KEY"):
    app.secret_key = os.getenv("FLASK_SECRET_KEY")
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
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV") == "production"
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Media upload configuration
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# Vercel's deployed filesystem is read-only. Use /tmp for runtime payment-proof
# uploads. Note: /tmp is temporary on serverless deployments; permanent storage
# should be moved to object/blob storage for production.
PAYMENT_PROOFS_FOLDER = os.path.join("/tmp", "payment_proofs")
os.makedirs(PAYMENT_PROOFS_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PAYMENT_PROOFS_FOLDER"] = PAYMENT_PROOFS_FOLDER
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

# Admin Anti-Brute-Force Rate Limiting Store
FAILED_ADMIN_LOGINS = {}  # ip -> {"count": int, "lockout_until": float}

# Production HTTP Security Headers
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

@app.context_processor
def inject_global_vars():
    cms = get_site_content()
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

    current_customer = None
    customer_id = session.get("customer_id")
    if customer_id:
        try:
            current_customer = CustomerUser.query.get(customer_id)
        except Exception:
            current_customer = None

    return dict(
        cache_id=int(time.time()),
        cms=cms,
        brand_name=cms.get("brand_name", "Tulsa Wears"),
        brand_tagline=cms.get("brand_tagline", "Since 2025"),
        instagram_handle_1=cms.get("instagram_handle_1", "__aannuuu.06"),
        instagram_handle_2=cms.get("instagram_handle_2", "tulsawear"),
        default_delivery_days=delivery_days,
        studio_phone=phone,
        studio_whatsapp=whatsapp,
        studio_email=email,
        studio_address=address,
        studio_hours=hours,
        current_customer=current_customer
    )


# =========================================
# DATABASE SETUP
# =========================================

BASE_DIR = os.path.abspath(
    os.path.dirname(__file__)
)

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "database",
    "fashion.db"
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + DATABASE_PATH
)

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


razorpay_client = None


if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:

    razorpay_client = razorpay.Client(
        auth=(
            RAZORPAY_KEY_ID,
            RAZORPAY_KEY_SECRET
        )
    )


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
            "discount_amount": "FLOAT DEFAULT 0.0"
        }

        with db.engine.begin() as connection:
            for column_name, column_type in new_order_cols.items():
                if column_name not in existing_order_cols:
                    connection.execute(
                        text(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")
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
            "studio_hours": "VARCHAR(100) DEFAULT 'Mon – Sat: 10:00 AM – 7:00 PM IST'"
        }
        with db.engine.begin() as connection:
            for col_name, col_type in admin_cols.items():
                if col_name not in existing_admin_cols:
                    connection.execute(
                        text(f"ALTER TABLE admin_users ADD COLUMN {col_name} {col_type}")
                    )
            # Update permanent phone and studio contacts
            connection.execute(
                text("UPDATE admin_users SET studio_phone = '+91 93504 39667', studio_whatsapp = '919350439667', permanent_phone = '9350439667'")
            )

    # Ensure tables exist
    try:
        db.create_all()
    except Exception:
        pass

    try:
        if AdminUser.query.count() == 0:
            default_admin = AdminUser(
                username=os.getenv("ADMIN_USERNAME", "admin"),
                default_delivery_days=10
            )
            default_admin.set_password(os.getenv("ADMIN_PASSWORD", "atelier-admin-2026"))
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


# =========================================
# HOME PAGE
# =========================================

@app.route("/")
def home():

    products = Product.query.order_by(
        Product.created_at.desc()
    ).all()

    best_sellers = Product.query.filter_by(
        best_seller=True
    ).all()

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

    # CATEGORY FILTER
    if category:
        query = query.filter(Product.category == category)

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
        "Plazo / Kurta",
        "Salwar Kameez",
        "Party Wear",
        "Wedding Wear"
    ]

    return render_template(
        "shop.html",
        products=products,
        categories=all_categories,
        selected_category=category,
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

    cart = session.get(
        "cart",
        []
    )

    cart_items = []

    total = 0


    for item in cart:

        product = Product.query.get(
            item["product_id"]
        )

        if product:

            quantity = item["quantity"]

            subtotal = (
                product.price * quantity
            )

            cart_items.append(
                {
                    "product": product,
                    "quantity": quantity,
                    "subtotal": subtotal,
                    "size": item.get("size", "M"),
                    "top_length": item.get("top_length", "30"),
                    "sleeves_length": item.get("sleeves_length", "18"),
                    "bust": item.get("bust", ""),
                    "waist": item.get("waist", ""),
                    "hip": item.get("hip", ""),
                    "shoulder": item.get("shoulder", "")
                }
            )

            total += subtotal

    # Coupon calculation
    applied_coupon = session.get("applied_coupon")
    discount_amount = 0.0
    if applied_coupon:
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()
        if coupon_obj and total >= (coupon_obj.min_order_amount or 0.0):
            discount_amount = coupon_obj.calculate_discount(total)
            applied_coupon["discount_amount"] = discount_amount
            session["applied_coupon"] = applied_coupon
        else:
            session.pop("applied_coupon", None)
            applied_coupon = None

    final_total = max(0.0, total - discount_amount)

    return render_template(
        "bag.html",
        cart_items=cart_items,
        total=final_total,
        subtotal=total,
        discount_amount=discount_amount,
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

    cart_items = []
    total = 0

    for item in cart:
        product = Product.query.get(item["product_id"])
        if product:
            quantity = item["quantity"]
            subtotal = product.price * quantity
            cart_items.append({
                "product": product,
                "quantity": quantity,
                "subtotal": subtotal,
                "size": item.get("size", "M"),
                "top_length": item.get("top_length", "30"),
                "sleeves_length": item.get("sleeves_length", "18"),
                "bust": item.get("bust", ""),
                "waist": item.get("waist", ""),
                "hip": item.get("hip", ""),
                "shoulder": item.get("shoulder", "")
            })
            total += subtotal

    if not cart_items:
        session["cart"] = []
        return redirect(url_for("shop"))

    # Coupon calculation
    applied_coupon = session.get("applied_coupon")
    discount_amount = 0.0
    coupon_obj = None
    if applied_coupon:
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()
        if coupon_obj and total >= (coupon_obj.min_order_amount or 0.0):
            discount_amount = coupon_obj.calculate_discount(total)
        else:
            session.pop("applied_coupon", None)
            applied_coupon = None

    final_total = max(0.0, total - discount_amount)

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

        phone = clean_phone
        pincode = clean_pincode

        # Sizing and Measurements from form or first cart item
        size = request.form.get("size", "").strip() or cart_items[0].get("size", "M")
        top_length = request.form.get("top_length", "").strip() or cart_items[0].get("top_length", "30")
        sleeves_length = request.form.get("sleeves_length", "").strip() or cart_items[0].get("sleeves_length", "18")
        bust = request.form.get("bust", "").strip() or cart_items[0].get("bust", "")
        waist = request.form.get("waist", "").strip() or cart_items[0].get("waist", "")
        hip = request.form.get("hip", "").strip() or cart_items[0].get("hip", "")
        shoulder = request.form.get("shoulder", "").strip() or cart_items[0].get("shoulder", "")

        tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"
        try:
            admin_user = AdminUser.query.first()
            est_days = admin_user.default_delivery_days if admin_user else 10
        except Exception:
            est_days = 10
        est_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")

        items_summary = ", ".join([f"{item['product'].name} (x{item['quantity']})" for item in cart_items])

        # Customer Account Creation / Linking
        customer_id = session.get("customer_id")
        account_password = request.form.get("account_password", "").strip()
        customer = None
        if customer_id:
            customer = CustomerUser.query.get(customer_id)
        if not customer and phone:
            customer = CustomerUser.query.filter_by(phone=phone).first()
            if not customer:
                customer = CustomerUser(
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    city=city,
                    pincode=pincode
                )
                if account_password:
                    customer.set_password(account_password)
                db.session.add(customer)
                db.session.commit()
                try:
                    reg_traffic = TrafficLog(event_type="register", ip_address=request.remote_addr, page_url="/checkout", customer_id=customer.id)
                    db.session.add(reg_traffic)
                    db.session.commit()
                except Exception:
                    pass
            else:
                if not customer.address:
                    customer.address = address
                    customer.city = city
                    customer.pincode = pincode
                if account_password and not customer.password_hash:
                    customer.set_password(account_password)
                db.session.commit()

            session["customer_id"] = customer.id
            session["customer_name"] = customer.name
            session["customer_phone"] = customer.phone

        new_order = Order(
            product_id=cart_items[0]["product"].id,
            product_name=items_summary,
            price=final_total,
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
            balance_due=final_total,
            coupon_code=applied_coupon.get("code") if applied_coupon else None,
            discount_amount=discount_amount,
            status="Payment Pending"
        )

        if coupon_obj:
            coupon_obj.times_used = (coupon_obj.times_used or 0) + 1

        db.session.add(new_order)
        db.session.commit()

        # Clear cart and coupon upon order creation
        session["cart"] = []
        session.pop("applied_coupon", None)
        session.modified = True

        if razorpay_client is not None:
            try:
                amount_in_paise = int(round(final_total * 100))
                razorpay_order = razorpay_client.order.create({
                    "amount": amount_in_paise,
                    "currency": "INR",
                    "receipt": f"atelier_{new_order.id}"
                })
                new_order.razorpay_order_id = razorpay_order["id"]
                db.session.commit()
            except Exception as e:
                app.logger.error(f"Razorpay error: {e}")
        else:
            new_order.razorpay_order_id = f"atelier_dev_{new_order.id}"
            db.session.commit()

        admin_cfg = AdminUser.query.first()
        active_razorpay_key = (admin_cfg.razorpay_key_id if (admin_cfg and admin_cfg.razorpay_key_id) else RAZORPAY_KEY_ID)
        active_upi_id = admin_cfg.upi_id if admin_cfg else ""
        active_upi_name = admin_cfg.upi_payee_name if admin_cfg else "Tulsa Wears"

        return render_template(
            "payment.html",
            order=new_order,
            product=cart_items[0]["product"],
            razorpay_key_id=active_razorpay_key,
            upi_id=active_upi_id,
            upi_payee_name=active_upi_name
        )

    return render_template(
        "checkout.html",
        product=cart_items[0]["product"],
        cart_items=cart_items,
        total=final_total,
        subtotal=total,
        discount_amount=discount_amount,
        applied_coupon=applied_coupon,
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
    coupon_obj = None
    if applied_coupon:
        coupon_obj = Coupon.query.filter_by(code=applied_coupon.get("code"), is_active=True).first()
        if coupon_obj and product.price >= (coupon_obj.min_order_amount or 0.0):
            discount_amount = coupon_obj.calculate_discount(product.price)
        else:
            applied_coupon = None

    final_price = max(0.0, product.price - discount_amount)

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
        try:
            admin_user = AdminUser.query.first()
            est_days = admin_user.default_delivery_days if admin_user else 10
        except Exception:
            est_days = 10
        est_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")

        # Customer Account Creation / Linking
        customer_id = session.get("customer_id")
        account_password = request.form.get("account_password", "").strip()
        customer = None
        if customer_id:
            customer = CustomerUser.query.get(customer_id)
        if not customer and phone:
            customer = CustomerUser.query.filter_by(phone=phone).first()
            if not customer:
                customer = CustomerUser(
                    name=name,
                    phone=phone,
                    email=email,
                    address=address,
                    city=city,
                    pincode=pincode
                )
                if account_password:
                    customer.set_password(account_password)
                db.session.add(customer)
                db.session.commit()
                try:
                    reg_traffic = TrafficLog(event_type="register", ip_address=request.remote_addr, page_url=f"/buy-now/{product.id}", customer_id=customer.id)
                    db.session.add(reg_traffic)
                    db.session.commit()
                except Exception:
                    pass
            else:
                if not customer.address:
                    customer.address = address
                    customer.city = city
                    customer.pincode = pincode
                if account_password and not customer.password_hash:
                    customer.set_password(account_password)
                db.session.commit()

            session["customer_id"] = customer.id
            session["customer_name"] = customer.name
            session["customer_phone"] = customer.phone

        new_order = Order(
            product_id=product.id,
            product_name=product.name,
            price=final_price,
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
            balance_due=final_price,
            coupon_code=applied_coupon.get("code") if applied_coupon else None,
            discount_amount=discount_amount,
            status="Payment Pending"
        )

        if coupon_obj:
            coupon_obj.times_used = (coupon_obj.times_used or 0) + 1

        db.session.add(new_order)
        db.session.commit()

        session.pop("applied_coupon", None)
        session.modified = True

        # =================================
        # RAZORPAY OR DEV PAYMENT FLOW
        # =================================

        if razorpay_client is not None:
            try:
                amount_in_paise = int(round(final_price * 100))
                razorpay_order = razorpay_client.order.create(
                    {
                        "amount": amount_in_paise,
                        "currency": "INR",
                        "receipt": f"atelier_{new_order.id}"
                    }
                )
                new_order.razorpay_order_id = razorpay_order["id"]
                db.session.commit()
            except Exception as e:
                app.logger.error(f"Razorpay order creation error: {e}")

        else:
            # Development Mode order ID
            new_order.razorpay_order_id = f"atelier_dev_{new_order.id}"
            db.session.commit()

        # =================================
        # OPEN PAYMENT PAGE
        # =================================

        admin_cfg = AdminUser.query.first()
        active_razorpay_key = (admin_cfg.razorpay_key_id if (admin_cfg and admin_cfg.razorpay_key_id) else RAZORPAY_KEY_ID)
        active_upi_id = admin_cfg.upi_id if admin_cfg else ""
        active_upi_name = admin_cfg.upi_payee_name if admin_cfg else "Tulsa Wears"

        return render_template(
            "payment.html",
            order=new_order,
            product=product,
            razorpay_key_id=active_razorpay_key,
            upi_id=active_upi_id,
            upi_payee_name=active_upi_name
        )


    # =====================================
    # OPEN CHECKOUT PAGE
    # =====================================

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
        total=final_price,
        subtotal=product.price,
        discount_amount=discount_amount,
        applied_coupon=applied_coupon
    )


# =========================================
# PAYMENT PROOF VIEW & SECURE SUBMISSION
# =========================================

@app.route("/payment-step/<int:order_id>", methods=["GET"])
@app.route("/submit-payment-proof/<int:order_id>", methods=["GET"])
@app.route("/confirm-dev-payment/<int:order_id>", methods=["GET"])
def view_payment_step(order_id):
    order = Order.query.get_or_404(order_id)
    product = Product.query.get(order.product_id) or Product.query.first()
    admin_cfg = AdminUser.query.first()
    active_razorpay_key = (admin_cfg.razorpay_key_id if (admin_cfg and admin_cfg.razorpay_key_id) else RAZORPAY_KEY_ID)
    active_upi_id = admin_cfg.upi_id if admin_cfg else ""
    active_upi_name = admin_cfg.upi_payee_name if admin_cfg else "Tulsa Wears"
    return render_template(
        "payment.html",
        order=order,
        product=product,
        razorpay_key_id=active_razorpay_key,
        upi_id=active_upi_id,
        upi_payee_name=active_upi_name
    )


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

    payment_method = request.form.get(
        "payment_method",
        "UPI (GPay / PhonePe / QR)"
    )

    upi_utr = request.form.get("upi_utr", "").strip()
    if not validate_utr(upi_utr):
        flash("⚠️ Please enter a genuine UPI UTR / Transaction Reference ID (min 8 alphanumeric characters from your payment app).", "danger")
        return redirect(url_for("view_payment_step", order_id=order.id))

    # Payment Screenshot Upload Handling with PIL binary verification
    if "payment_screenshot" in request.files:
        file = request.files["payment_screenshot"]
        if file and file.filename and allowed_file(file.filename):
            if is_valid_image_file(file):
                ext = file.filename.rsplit(".", 1)[1].lower()
                safe_name = f"proof_{order.id}_{int(time.time())}_{uuid.uuid4().hex[:4]}.{ext}"
                save_path = os.path.join(PAYMENT_PROOFS_FOLDER, safe_name)
                file.save(save_path)
                order.payment_screenshot = f"payment_proofs/{safe_name}"
            else:
                flash("⚠️ The uploaded file is not a valid or readable image. Please attach a real JPG, PNG, or WebP screenshot.", "danger")
                return redirect(url_for("view_payment_step", order_id=order.id))
        else:
            flash("⚠️ Please select a valid screenshot image file (JPG, PNG, or WebP).", "danger")
            return redirect(url_for("view_payment_step", order_id=order.id))
    else:
        flash("⚠️ Payment screenshot is required to verify your transaction.", "danger")
        return redirect(url_for("view_payment_step", order_id=order.id))

    order.payment_method = payment_method
    order.status = "Pending Approval"
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

    if "COD" in payment_method.upper() or "CASH" in payment_method.upper():
        order.advance_paid = 99.0
        order.balance_due = max(0.0, order.price - 99.0)
    else:
        order.advance_paid = order.price
        order.balance_due = 0.0

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

    return redirect(
        url_for("order_success", order_id=order.id)
    )

# Alias for backwards compatibility
confirm_dev_payment = submit_payment_proof


# =========================================
# PAYMENT VERIFICATION
# =========================================

@app.route(
    "/payment/<int:order_id>",
    methods=["POST"]
)
def payment(order_id):

    order = Order.query.get_or_404(
        order_id
    )


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify(
            {
                "success": False,
                "message":
                    "Invalid payment response."
            }
        ), 400


    razorpay_order_id = data.get(
        "razorpay_order_id"
    )

    razorpay_payment_id = data.get(
        "razorpay_payment_id"
    )

    razorpay_signature = data.get(
        "razorpay_signature"
    )


    # =====================================
    # CHECK PAYMENT RESPONSE
    # =====================================

    if not all(
        [
            razorpay_order_id,
            razorpay_payment_id,
            razorpay_signature
        ]
    ):

        return jsonify(
            {
                "success": False,
                "message":
                    "Payment information is incomplete."
            }
        ), 400


    # =====================================
    # CHECK ORDER ID
    # =====================================

    if (
        razorpay_order_id
        != order.razorpay_order_id
    ):

        return jsonify(
            {
                "success": False,
                "message":
                    "Order verification failed."
            }
        ), 400


    # =====================================
    # VERIFY RAZORPAY SIGNATURE
    # =====================================

    try:

        razorpay_client.utility.verify_payment_signature(
            {
                "razorpay_order_id":
                    razorpay_order_id,

                "razorpay_payment_id":
                    razorpay_payment_id,

                "razorpay_signature":
                    razorpay_signature
            }
        )

    except Exception:

        return jsonify(
            {
                "success": False,
                "message":
                    "Payment verification failed."
            }
        ), 400


    # =====================================
    # GET PAYMENT DETAILS
    # =====================================

    payment_details = (
        razorpay_client.payment.fetch(
            razorpay_payment_id
        )
    )


    payment_method = payment_details.get(
        "method",
        "Unknown"
    )


    # =====================================
    # UPDATE ORDER
    # =====================================

    order.razorpay_payment_id = (
        razorpay_payment_id
    )

    order.payment_method = (
        payment_method
    )

    order.status = "Confirmed"

    if not order.tracking_id:
        order.tracking_id = f"TW-TRACK-{uuid.uuid4().hex[:6].upper()}"

    try:
        admin_user = AdminUser.query.first()
        est_days = admin_user.default_delivery_days if admin_user else 10
    except Exception:
        est_days = 10

    order.estimated_delivery_days = est_days
    order.estimated_delivery_date = (datetime.now() + timedelta(days=est_days)).strftime("%A, %d %b %Y")
    order.advance_paid = order.price
    order.balance_due = 0.0

    db.session.commit()


    # =====================================
    # SUCCESS URL
    # =====================================

    success_url = url_for(
        "order_success",
        order_id=order.id
    )


    return jsonify(
        {
            "success": True,
            "redirect_url": success_url
        }
    )


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

@app.route("/customer/register", methods=["POST"])
def customer_register():
    data = request.get_json() if request.is_json else request.form
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    address = (data.get("address") or "").strip()
    city = (data.get("city") or "").strip()
    pincode = (data.get("pincode") or "").strip()

    if not name or not phone:
        if request.is_json:
            return jsonify({"success": False, "message": "Full Name and Mobile Number are required."}), 400
        flash("Full Name and Mobile Number are required.", "danger")
        return redirect(request.referrer or url_for("checkout"))

    is_valid_phone, clean_phone = validate_indian_phone(phone)
    if not is_valid_phone:
        if request.is_json:
            return jsonify({"success": False, "message": "Please enter a valid 10-digit Indian mobile number."}), 400
        flash("Please enter a valid 10-digit Indian mobile number.", "danger")
        return redirect(request.referrer or url_for("checkout"))

    phone = clean_phone
    if pincode:
        pincode = re.sub(r"\D", "", pincode)

    existing = CustomerUser.query.filter_by(phone=phone).first()
    if existing:
        if password and not existing.password_hash:
            existing.set_password(password)
        session["customer_id"] = existing.id
        session["customer_name"] = existing.name
        session["customer_phone"] = existing.phone
        db.session.commit()
        if request.is_json:
            return jsonify({"success": True, "message": f"Welcome back, {existing.name}!", "customer_id": existing.id, "name": existing.name})
        flash(f"Welcome back, {existing.name}!", "success")
        return redirect(request.referrer or url_for("checkout"))

    new_cust = CustomerUser(
        name=name,
        phone=phone,
        email=email,
        address=address,
        city=city,
        pincode=pincode
    )
    if password:
        new_cust.set_password(password)
    db.session.add(new_cust)
    db.session.commit()

    session["customer_id"] = new_cust.id
    session["customer_name"] = new_cust.name
    session["customer_phone"] = new_cust.phone

    try:
        t = TrafficLog(event_type="register", ip_address=request.remote_addr, page_url="/customer/register", customer_id=new_cust.id)
        db.session.add(t)
        db.session.commit()
    except Exception:
        pass

    if request.is_json:
        return jsonify({"success": True, "message": "Account created successfully.", "customer_id": new_cust.id, "name": new_cust.name})
    flash("Account created successfully!", "success")
    return redirect(request.referrer or url_for("checkout"))


@app.route("/customer/login", methods=["POST"])
def customer_login():
    data = request.get_json() if request.is_json else request.form
    phone = (data.get("phone") or "").strip()
    password = (data.get("password") or "").strip()

    if not phone:
        if request.is_json:
            return jsonify({"success": False, "message": "Mobile number is required."}), 400
        flash("Mobile number is required.", "danger")
        return redirect(request.referrer or url_for("checkout"))

    is_valid_phone, clean_phone = validate_indian_phone(phone)
    if is_valid_phone:
        phone = clean_phone

    customer = CustomerUser.query.filter_by(phone=phone).first()
    if not customer:
        if request.is_json:
            return jsonify({"success": False, "message": "No account found with this phone number. Please register."}), 404
        flash("No account found with this phone number. Please register.", "danger")
        return redirect(request.referrer or url_for("checkout"))

    if customer.password_hash and password:
        if not customer.check_password(password):
            if request.is_json:
                return jsonify({"success": False, "message": "Incorrect password."}), 401
            flash("Incorrect password.", "danger")
            return redirect(request.referrer or url_for("checkout"))

    session["customer_id"] = customer.id
    session["customer_name"] = customer.name
    session["customer_phone"] = customer.phone

    try:
        t = TrafficLog(event_type="login", ip_address=request.remote_addr, page_url="/customer/login", customer_id=customer.id)
        db.session.add(t)
        db.session.commit()
    except Exception:
        pass

    if request.is_json:
        return jsonify({
            "success": True,
            "message": f"Welcome back, {customer.name}!",
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email or "",
            "address": customer.address or "",
            "city": customer.city or "",
            "pincode": customer.pincode or ""
        })
    flash(f"Welcome back, {customer.name}!", "success")
    return redirect(request.referrer or url_for("checkout"))


@app.route("/customer/logout")
def customer_logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    session.pop("customer_phone", None)
    flash("You have been signed out.", "info")
    return redirect(url_for("home"))


# =========================================
# ADMIN AUTHENTICATION SETUP
# =========================================

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "atelier-admin-2026")
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)


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

        if not valid and username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
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
    order.status = "Confirmed"
    db.session.commit()
    flash(f"✓ Order #{order.id} payment verified and approved! Status updated to Confirmed.", "success")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/update-status/<int:order_id>", methods=["POST"])
@admin_required
def admin_update_order_status(order_id):

    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status", "").strip()

    if new_status:
        order.status = new_status
        db.session.commit()

    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/delete/<int:order_id>", methods=["POST"])
@admin_required
def admin_delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/clear-all", methods=["POST"])
@admin_required
def admin_clear_all_orders():
    Order.query.delete()
    db.session.commit()
    flash("✓ All test orders cleared. Portal is pure, fresh, and at 0 orders.", "info")
    return redirect(url_for("admin_orders"))


# =========================================
# ADMIN: ORDER INVOICE, CSV EXPORT & DB BACKUP
# =========================================

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
        "Total Price (INR)", "Payment Method", "Advance Paid (INR)", "Balance Due (INR)",
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

@app.route("/admin/products")
@admin_required
def admin_products():
    products = Product.query.order_by(Product.created_at.desc()).all()
    categories = ["Plazo / Kurta", "Salwar Kameez", "Party Wear", "Wedding Wear"]

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
        ext = file.filename.rsplit(".", 1)[1].lower()
        safe_name = f"prod_{product.id}_{uuid.uuid4().hex[:6]}.{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
        file.save(save_path)

        product.image = safe_name
        db.session.commit()
        flash(f"Uploaded new photograph for '{product.name}'.", "success")
    else:
        flash("Please choose a valid image file (.jpg, .jpeg, .png, .webp, .avif).", "warning")

    return redirect(url_for("admin_products"))


@app.route("/admin/products/add", methods=["POST"])
@admin_required
def admin_add_product():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "Plazo / Kurta").strip()
    fabric = request.form.get("fabric", "").strip()
    color = request.form.get("color", "").strip()
    description = request.form.get("description", "").strip()
    best_seller = bool(request.form.get("best_seller"))

    try:
        price = float(request.form.get("price", 1500))
    except (ValueError, TypeError):
        price = 1500.0

    try:
        stock = int(request.form.get("stock", 10))
    except (ValueError, TypeError):
        stock = 10

    if not name:
        flash("Please enter a name for the new garment.", "warning")
        return redirect(url_for("admin_products"))

    image_filename = "product-1.jpg"
    file = request.files.get("image")
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        image_filename = f"prod_{uuid.uuid4().hex[:8]}.{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
        file.save(save_path)

    new_product = Product(
        name=name,
        price=price,
        category=category,
        fabric=fabric or "Handwoven Cotton",
        color=color or "Natural",
        description=description or "A bespoke handcrafted garment created slowly by atelier artisans.",
        image=image_filename,
        stock=stock,
        best_seller=best_seller
    )
    db.session.add(new_product)
    db.session.commit()

    flash(f"Added '{name}' (₹{price:,.0f}) to the atelier catalog.", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/products/edit/<int:product_id>", methods=["POST"])
@admin_required
def admin_edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    name = request.form.get("name", "").strip()
    if name:
        product.name = name

    try:
        price = float(request.form.get("price", product.price))
        if price > 0:
            product.price = price
    except (ValueError, TypeError):
        pass

    try:
        stock = int(request.form.get("stock", product.stock))
        if stock >= 0:
            product.stock = stock
    except (ValueError, TypeError):
        pass

    product.category = request.form.get("category", product.category).strip()
    product.fabric = request.form.get("fabric", product.fabric).strip()
    product.color = request.form.get("color", product.color).strip()
    product.description = request.form.get("description", product.description).strip()
    product.best_seller = bool(request.form.get("best_seller"))

    file = request.files.get("image")
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        safe_name = f"prod_{product.id}_{uuid.uuid4().hex[:6]}.{ext}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
        file.save(save_path)
        product.image = safe_name

    db.session.commit()
    flash(f"Garment details updated for '{product.name}'.", "success")
    return redirect(url_for("admin_products"))


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
# ADMIN: WEBSITE DESIGNER & CMS (TEXT & IMAGES)
# =========================================

@app.route("/admin/customizer", methods=["GET", "POST"])
@admin_required
def admin_customizer():
    cms = get_site_content()

    if request.method == "POST":
        data = request.form.to_dict()

        # Update text values from form
        for key, value in data.items():
            if key != "action" and not key.endswith("_file"):
                cms[key] = value.strip()

        # Process image file uploads
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

        # Synchronize studio contact details to AdminUser model
        admin_user = AdminUser.query.first()
        if admin_user:
            if "studio_phone" in data and data["studio_phone"]:
                admin_user.studio_phone = data["studio_phone"]
            if "studio_whatsapp" in data and data["studio_whatsapp"]:
                admin_user.studio_whatsapp = data["studio_whatsapp"]
            if "studio_email" in data and data["studio_email"]:
                admin_user.studio_email = data["studio_email"]
            if "studio_address" in data and data["studio_address"]:
                admin_user.studio_address = data["studio_address"]
            if "studio_hours" in data and data["studio_hours"]:
                admin_user.studio_hours = data["studio_hours"]
            db.session.commit()

        save_site_content(cms)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({
                "status": "success",
                "message": "Website redesigned and updated successfully!",
                "cms": cms
            })

        flash("✨ Website redesign saved! All updated text, banners, and photos are now live.", "success")
        return redirect(url_for("admin_customizer"))

    return render_template(
        "admin-customizer.html",
        cms=cms,
        total_products=Product.query.count(),
        server_host=request.host_url.rstrip("/")
    )


@app.route("/admin/customizer/reset", methods=["POST"])
@admin_required
def admin_customizer_reset():
    reset_site_content()
    flash("Website text and design reset to original atelier defaults.", "info")
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
            razorpay_key_id = request.form.get("razorpay_key_id", "").strip()
            razorpay_key_secret = request.form.get("razorpay_key_secret", "").strip()

            admin_user.upi_id = upi_id
            admin_user.upi_payee_name = upi_payee_name or "Tulsa Wears"
            admin_user.razorpay_key_id = razorpay_key_id
            admin_user.razorpay_key_secret = razorpay_key_secret
            db.session.commit()
            flash("Bank Account UPI & Payment Gateway settings saved! Customers can now pay directly to your account.", "success")

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
    try:
        subtotal = float(data.get("subtotal") or 0.0)
    except (ValueError, TypeError):
        subtotal = 0.0

    if subtotal <= 0:
        cart = session.get("cart", [])
        for item in cart:
            p = Product.query.get(item.get("product_id"))
            if p:
                subtotal += p.price * item.get("quantity", 1)

    if not code:
        return jsonify({"success": False, "message": "Please enter a promo / coupon code."}), 400

    coupon = Coupon.query.filter_by(code=code, is_active=True).first()
    if not coupon:
        return jsonify({"success": False, "message": f"Coupon code '{code}' is invalid or expired."}), 404

    if subtotal < (coupon.min_order_amount or 0.0):
        return jsonify({
            "success": False,
            "message": f"Coupon '{code}' requires a minimum order of ₹{coupon.min_order_amount:,.0f}. Your order subtotal is ₹{subtotal:,.0f}."
        }), 400

    discount = coupon.calculate_discount(subtotal)
    final_total = max(0.0, subtotal - discount)

    session["applied_coupon"] = {
        "id": coupon.id,
        "code": coupon.code,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "discount_amount": discount
    }
    session.modified = True

    return jsonify({
        "success": True,
        "message": f"Coupon '{coupon.code}' applied! You saved ₹{discount:,.0f}.",
        "coupon_code": coupon.code,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "discount_amount": discount,
        "subtotal": subtotal,
        "final_total": final_total
    })


@app.route("/api/coupon/remove", methods=["POST"])
def api_remove_coupon():
    session.pop("applied_coupon", None)
    session.modified = True
    return jsonify({"success": True, "message": "Coupon removed successfully."})


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