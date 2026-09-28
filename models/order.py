from .database import db


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    product_id = db.Column(
        db.Integer,
        nullable=False
    )

    product_name = db.Column(
        db.String(150),
        nullable=False
    )

    price = db.Column(
        db.Float,
        nullable=False
    )

    customer_name = db.Column(
        db.String(150),
        nullable=False
    )

    phone = db.Column(
        db.String(30),
        nullable=False
    )

    email = db.Column(
        db.String(150),
        nullable=False
    )

    address = db.Column(
        db.Text,
        nullable=False
    )

    city = db.Column(
        db.String(100),
        nullable=False
    )

    pincode = db.Column(
        db.String(20),
        nullable=False
    )

    status = db.Column(
        db.String(50),
        default="Pending"
    )

    razorpay_order_id = db.Column(
        db.String(100),
        nullable=True
    )

    razorpay_payment_id = db.Column(
        db.String(100),
        nullable=True
    )

    payment_method = db.Column(
        db.String(50),
        nullable=True
    )

    tracking_id = db.Column(
        db.String(100),
        unique=True,
        nullable=True
    )

    size = db.Column(
        db.String(20),
        nullable=True
    )

    top_length = db.Column(
        db.String(50),
        nullable=True
    )

    sleeves_length = db.Column(
        db.String(50),
        nullable=True
    )

    bust = db.Column(
        db.String(50),
        nullable=True
    )

    waist = db.Column(
        db.String(50),
        nullable=True
    )

    hip = db.Column(
        db.String(50),
        nullable=True
    )

    shoulder = db.Column(
        db.String(50),
        nullable=True
    )

    advance_paid = db.Column(
        db.Float,
        default=0.0
    )

    balance_due = db.Column(
        db.Float,
        default=0.0
    )

    estimated_delivery_days = db.Column(
        db.Integer,
        default=10
    )

    estimated_delivery_date = db.Column(
        db.String(100),
        nullable=True
    )

    upi_utr = db.Column(
        db.String(100),
        nullable=True
    )

    coupon_code = db.Column(
        db.String(50),
        nullable=True
    )

    discount_amount = db.Column(
        db.Float,
        default=0.0
    )

    payment_screenshot = db.Column(
        db.String(255),
        nullable=True
    )

    customer_id = db.Column(
        db.Integer,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )