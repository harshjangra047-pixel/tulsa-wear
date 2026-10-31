"""Production Allocation model linking Production Batches to Customer Orders."""
from .database import db


class ProductionAllocation(db.Model):
    __tablename__ = "production_allocations"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, nullable=True)
    size = db.Column(db.String(20), nullable=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "order_id": self.order_id,
            "product_id": self.product_id,
            "size": self.size,
            "quantity": self.quantity,
            "is_completed": self.is_completed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<ProductionAllocation Batch #{self.batch_id} -> Order #{self.order_id} ({self.size} x {self.quantity})>"

