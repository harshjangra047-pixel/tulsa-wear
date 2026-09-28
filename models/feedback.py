from .database import db

class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    rating = db.Column(db.Integer, nullable=False, default=5)
    message = db.Column(db.Text, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<Feedback {self.customer_name} - {self.rating} stars>"
