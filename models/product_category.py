from .database import db


class ProductCategory(db.Model):
    """Normalized multi-category mapping table for Tulsa products."""
    __tablename__ = "product_categories"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(100), nullable=False, index=True)
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<ProductCategory #{self.product_id}: {self.category} (primary={self.is_primary})>"

