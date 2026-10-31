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

    # Shipping attributes
    shipping_fee = db.Column(
        db.Float,
        default=0.0
    )

    shipping_provider = db.Column(
        db.String(100),
        nullable=True
    )

    shipping_service = db.Column(
        db.String(100),
        nullable=True
    )

    payment_screenshot = db.Column(
        db.String(255),
        nullable=True
    )

    manual_payment_verified_by = db.Column(db.String(80), nullable=True)
    manual_payment_verified_at = db.Column(db.DateTime, nullable=True)

    customer_id = db.Column(
        db.Integer,
        nullable=True
    )

    # WhatsApp consent & notification statuses
    whatsapp_opt_in = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    whatsapp_opt_in_at = db.Column(
        db.DateTime,
        nullable=True
    )

    whatsapp_opt_in_source = db.Column(
        db.String(50),
        nullable=True
    )

    whatsapp_notification_status = db.Column(
        db.String(50),
        default="Not opted in",
        nullable=False
    )

    email_notification_status = db.Column(
        db.String(50),
        default="Pending",
        nullable=False
    )

    # Itemized order details snapshot (JSON array of line items)
    order_items_data = db.Column(
        db.Text,
        nullable=True
    )

    # Central 7-15 day delivery window dates
    delivery_window_start = db.Column(
        db.String(100),
        nullable=True
    )

    delivery_window_end = db.Column(
        db.String(100),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    def get_items(self):
        """Return list of item dictionaries from stored snapshot or fallback."""
        import json
        if self.order_items_data:
            try:
                data = json.loads(self.order_items_data)
                if isinstance(data, list) and len(data) > 0:
                    return data
            except Exception:
                pass
        return [{
            "product_id": self.product_id,
            "name": self.product_name,
            "price": self.price,
            "quantity": 1,
            "size": self.size or "M",
            "image": None
        }]
