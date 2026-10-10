from .database import db

class ContactInquiry(db.Model):
    __tablename__ = "contact_inquiries"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    subject = db.Column(db.String(150), default="General Inquiry")
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default="New")  # New, In Progress, Resolved
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<ContactInquiry #{self.id} - {self.customer_name} ({self.status})>"
