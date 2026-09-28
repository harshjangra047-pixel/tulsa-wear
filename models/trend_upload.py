from .database import db

class TrendUpload(db.Model):
    __tablename__ = "trend_uploads"

    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(255), nullable=False)
    search_query = db.Column("query", db.String(255), nullable=True)
    source = db.Column(db.String(50), default="AI Concierge Visual Search")
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<TrendUpload #{self.id} - {self.image}>"
