from .database import db
from werkzeug.security import generate_password_hash, check_password_hash

class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, default="admin")
    password_hash = db.Column(db.String(255), nullable=False)
    default_delivery_days = db.Column(db.Integer, default=10)
    upi_id = db.Column(db.String(100), default="")
    upi_payee_name = db.Column(db.String(100), default="Tulsa Wears")
    razorpay_key_id = db.Column(db.String(100), default="")
    razorpay_key_secret = db.Column(db.String(100), default="")
    studio_phone = db.Column(db.String(50), default="+91 93504 39667")
    studio_whatsapp = db.Column(db.String(50), default="919350439667")
    permanent_phone = db.Column(db.String(50), default="9350439667")
    additional_emails = db.Column(db.Text, default="")
    reset_otp = db.Column(db.String(10), nullable=True)
    reset_otp_expiry = db.Column(db.DateTime, nullable=True)
    studio_email = db.Column(db.String(100), default="contact@tulsawear.com")
    studio_address = db.Column(db.String(255), default="Tulsa Wears Atelier, Hansi, Haryana, India - 125033")
    studio_hours = db.Column(db.String(100), default="Mon – Sat: 10:00 AM – 7:00 PM IST")

    # Warehouse & Shipping Logistics
    warehouse_pincode = db.Column(db.String(20), default="125033")
    warehouse_city = db.Column(db.String(100), default="Hansi")
    warehouse_state = db.Column(db.String(100), default="Haryana")
    warehouse_address = db.Column(db.String(255), default="Tulsa Wears Atelier, Hansi")
    shiprocket_email = db.Column(db.String(150), default="")
    shiprocket_password = db.Column(db.String(255), default="")
    shiprocket_token = db.Column(db.Text, default="")
    shiprocket_token_expiry = db.Column(db.DateTime, nullable=True)
    shipping_fallback_enabled = db.Column(db.Boolean, default=True)
    shipping_flat_fallback = db.Column(db.Float, default=0.0)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<AdminUser {self.username}>"
