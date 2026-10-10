from .database import db

class Coupon(db.Model):
    __tablename__ = "coupons"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), default="percentage")  # 'percentage' or 'flat'
    discount_value = db.Column(db.Float, nullable=False)            # e.g., 10.0 for 10%, 500.0 for ₹500
    min_order_amount = db.Column(db.Float, default=0.0)             # Minimum cart subtotal required
    max_discount = db.Column(db.Float, nullable=True)               # Optional cap for percentage discounts
    is_active = db.Column(db.Boolean, default=True)
    times_used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def calculate_discount(self, subtotal):
        """Calculate discount amount in Rupees given a subtotal amount."""
        if not self.is_active:
            return 0.0
        if subtotal < (self.min_order_amount or 0.0):
            return 0.0

        if self.discount_type == "percentage":
            discount = (self.discount_value / 100.0) * subtotal
            if self.max_discount and self.max_discount > 0:
                discount = min(discount, self.max_discount)
        else:  # flat
            discount = min(self.discount_value, subtotal)

        return round(float(discount), 2)

    def __repr__(self):
        return f"<Coupon {self.code} ({self.discount_type} {self.discount_value})>"
