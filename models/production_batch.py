"""Production Batch model for Tulsa Wears Garment Manufacturing ERP."""
import json
from datetime import datetime, date
from .database import db


class ProductionBatch(db.Model):
    __tablename__ = "production_batches"

    id = db.Column(db.Integer, primary_key=True)
    batch_number = db.Column(db.String(50), unique=True, nullable=False, index=True)

    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    product_name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(50), nullable=True)

    total_quantity = db.Column(db.Integer, default=0, nullable=False)
    completed_quantity = db.Column(db.Integer, default=0, nullable=False)

    # Size breakdowns stored as JSON strings: {"XS": 1, "S": 2, "M": 5, "L": 3, "XL": 2}
    size_breakdown = db.Column(db.Text, nullable=True)
    size_completed = db.Column(db.Text, nullable=True)

    priority = db.Column(db.String(20), default="Medium", nullable=False)  # Critical, High, Medium, Low
    priority_reason = db.Column(db.String(255), nullable=True)

    # Production lifecycle status:
    # Pending -> Material Required -> Ready to Start -> In Production -> Partially Completed -> Completed -> Quality Check -> Ready for Packing -> Packed -> Ready for Dispatch -> Dispatched
    status = db.Column(db.String(50), default="Pending", nullable=False, index=True)

    # Material & Fabric Readiness
    material_status = db.Column(db.String(50), default="Available", nullable=False)  # Available, Partially Available, Required, Waiting
    material_notes = db.Column(db.Text, nullable=True)

    # Quality Check (QC) Gate
    qc_checked = db.Column(db.Integer, default=0)
    qc_approved = db.Column(db.Integer, default=0)
    qc_rejected = db.Column(db.Integer, default=0)
    qc_notes = db.Column(db.Text, nullable=True)

    # Scheduling & Planning
    planned_start_date = db.Column(db.Date, nullable=True)
    target_completion_date = db.Column(db.Date, nullable=True)
    estimated_hours = db.Column(db.Float, default=0.0)
    assigned_worker = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # Relationship to allocations
    allocations = db.relationship(
        "ProductionAllocation",
        backref="batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        if "size_breakdown" in kwargs and isinstance(kwargs["size_breakdown"], dict):
            kwargs["size_breakdown"] = json.dumps(kwargs["size_breakdown"])
        if "size_completed" in kwargs and isinstance(kwargs["size_completed"], dict):
            kwargs["size_completed"] = json.dumps(kwargs["size_completed"])
        super().__init__(**kwargs)

    def get_sizes(self):
        """Return dict of required quantities per size."""
        if self.size_breakdown:
            try:
                res = json.loads(self.size_breakdown)
                if isinstance(res, dict):
                    return res
            except Exception:
                pass
        return {}

    def get_completed_sizes(self):
        """Return dict of completed quantities per size."""
        if self.size_completed:
            try:
                res = json.loads(self.size_completed)
                if isinstance(res, dict):
                    return res
            except Exception:
                pass
        return {}

    def get_remaining_quantity(self):
        return max(0, (self.total_quantity or 0) - (self.completed_quantity or 0))

    @property
    def remaining_quantity(self):
        return self.get_remaining_quantity()

    def record_size_completion(self, size, qty_completed):
        """Record completed pieces for a specific garment size and update batch totals and status."""
        sizes = self.get_completed_sizes()
        size_str = str(size).strip().upper()
        sizes[size_str] = sizes.get(size_str, 0) + int(qty_completed)
        self.size_completed = json.dumps(sizes)
        self.completed_quantity = sum(sizes.values())
        if self.completed_quantity >= self.total_quantity and self.total_quantity > 0:
            self.status = "Completed"
        elif self.completed_quantity > 0:
            self.status = "In Production"
        return self.completed_quantity

    @classmethod
    def generate_batch_number(cls, prefix="BAT"):
        import time, random
        clean_p = (prefix or "BAT").strip().upper()[:3]
        return f"BATCH-{clean_p}-{int(time.time()) % 100000:05d}-{random.randint(10, 99)}"

    def get_linked_order_ids(self):
        return [alloc.order_id for alloc in self.allocations if alloc.order_id]

    def to_dict(self):
        return {
            "id": self.id,
            "batch_number": self.batch_number,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "sku": self.sku,
            "color": self.color,
            "total_quantity": self.total_quantity,
            "completed_quantity": self.completed_quantity,
            "remaining_quantity": self.get_remaining_quantity(),
            "size_breakdown": self.get_sizes(),
            "size_completed": self.get_completed_sizes(),
            "priority": self.priority,
            "priority_reason": self.priority_reason,
            "status": self.status,
            "material_status": self.material_status,
            "material_notes": self.material_notes,
            "qc_checked": self.qc_checked,
            "qc_approved": self.qc_approved,
            "qc_rejected": self.qc_rejected,
            "planned_start_date": self.planned_start_date.isoformat() if self.planned_start_date else None,
            "target_completion_date": self.target_completion_date.isoformat() if self.target_completion_date else None,
            "estimated_hours": self.estimated_hours,
            "assigned_worker": self.assigned_worker,
            "linked_orders_count": len(self.allocations),
            "linked_order_ids": self.get_linked_order_ids(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<ProductionBatch {self.batch_number} - {self.product_name} ({self.total_quantity} pcs)>"
