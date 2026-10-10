from .database import db


class SiteContent(db.Model):
    """Single live storefront document shared with the admin application."""

    __tablename__ = "site_content"

    id = db.Column(db.Integer, primary_key=True)
    content_json = db.Column(db.Text, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())


class SiteContentRevision(db.Model):
    """Immutable snapshots used for editor draft/publish and recovery."""

    __tablename__ = "site_content_revisions"

    id = db.Column(db.Integer, primary_key=True)
    content_json = db.Column(db.Text, nullable=False)
    revision = db.Column(db.Integer, nullable=False, unique=True)
    state = db.Column(db.String(20), nullable=False, default="published")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
