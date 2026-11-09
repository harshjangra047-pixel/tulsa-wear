from .database import db

class CustomerWishlist(db.Model):
    __tablename__ = "customer_wishlists"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer_users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    product = db.relationship("Product", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("customer_id", "product_id", name="uq_customer_product_wishlist"),
    )

