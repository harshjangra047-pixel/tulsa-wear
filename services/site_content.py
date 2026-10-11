import os
import json
import logging
import re
import io
from models.database import db
from models.site_content import SiteContent, SiteContentRevision

logger = logging.getLogger(__name__)

CONTENT_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "site_content.json")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "avif"}

DEFAULT_SITE_CONTENT = {
    "editor_sections": [
        {"id": section_id, "visible": True} for section_id in (
            "hero-section", "mood-portals", "curved-carousel", "look-builder",
            "best-sellers", "collections", "bridal", "seasonal", "campaign-gallery",
            "trends", "categories", "shop-price", "process", "about", "contact",
            "ai-studio", "feedback", "faq-section", "contact-us", "instagram-section",
            "newsletter-section"
        )
    ],
    "custom_sections": [],
    "editor_theme": {"accent": "#C9A96E", "background": "#F7F4EF", "heading_font": "Cormorant Garamond", "section_spacing": 96},
    # Announcement Bar
    "announcement_enabled": "true",
    "announcement_text": "✦ FESTIVE ATELIER — COMPLIMENTARY BESPOKE TAILORING ON ALL PRE-ORDERS ✦",
    "announcement_link": "#collections",

    # Brand Identity
    "brand_name": "TULSA — BY ANJALI",
    "brand_tagline": "Handcrafted Slow Fashion • By Anjali",
    "brand_logo": "tulsa-brand-logo.png",
    "footer_bio": "Tulsa Wears is an artisanal fashion studio dedicated to the slow, thoughtful creation of handmade Indian garments.",

    # Hero Section
    "hero_badge": "✦ TULSA WEARS — ATELIER COUTURE ✦",
    "hero_title_line1": "The Art of",
    "hero_title_line2": "Handmade",
    "hero_subtitle": "Handcrafted silhouettes shaped slowly by fabric, memory and modern craft. Artisanal Indian couture for discerning souls.",
    "hero_cta1_text": "Explore Collection →",
    "hero_cta1_link": "#curved-carousel",
    "hero_cta2_text": "✦ AI Style Studio",
    "hero_cta2_link": "#ai-studio",
    "hero_image": "editorial-hero.jpg",

    # Arched Mood Portals (Categories)
    "mood_eyebrow": "CURATED EDITORIAL PORTALS",
    "mood_title": "Six Moods. Infinite Craft.",
    "mood_cat1_title": "Plazo & Kurta",
    "mood_cat1_sub": "Explore Pieces →",
    "mood_cat1_image": "editorial-category-1.jpg",
    "mood_cat2_title": "Salwar Kameez",
    "mood_cat2_sub": "Explore Pieces →",
    "mood_cat2_image": "editorial-category-2.jpg",
    "mood_cat3_title": "Party Wear",
    "mood_cat3_sub": "Explore Pieces →",
    "mood_cat3_image": "editorial-category-3.jpg",
    "mood_cat4_title": "Wedding Regalia",
    "mood_cat4_sub": "Explore Pieces →",
    "mood_cat4_image": "editorial-category-4.jpg",

    # Signatures 3D Carousel
    "signatures_eyebrow": "THE ATELIER SIGNATURES",
    "signatures_title": "Woven to Be Remembered",

    # Look Builder
    "look_eyebrow": "INTERACTIVE ATELIER STUDIO",
    "look_title": "Change Look. Personalize Your Silhouette.",

    # Best Sellers
    "bestseller_eyebrow": "02 / BEST SELLERS",
    "bestseller_title": "Most loved by you.",
    "bestseller_intro": "The pieces our clients return to, season after season.",

    # Featured Collection
    "collection_eyebrow": "COLLECTION 01",
    "collection_title": "Threads of Memory",
    "collection_desc": "A collection shaped by heritage craft and contemporary silhouette. Each piece carries the patience and precision of handmade artistry.",
    "collection_cta_text": "Explore Collection →",
    "collection_cta_link": "/shop",
    "collection_image": "editorial-collection.jpg",

    # Bridal & Festive Edit
    "bridal_eyebrow": "THE BRIDAL EDIT",
    "bridal_title": "Made for moments that stay with you.",
    "bridal_desc": "Opulent ensembles woven from heritage silks and embellished with handwork. Crafted to capture the light in sacred celebrations.",
    "bridal_cta_text": "View The Bridal Edit →",
    "bridal_cta_link": "/shop?category=Wedding+Wear",
    "bridal_image": "editorial-bridal.jpg",

    # Seasonal Forecast
    "seasonal_eyebrow": "AUTUMN — WINTER 2026",
    "seasonal_title": "The season, in fabric.",
    "seasonal_img1": "editorial-seasonal-1.jpg",
    "seasonal_cap1_tag": "Editorial",
    "seasonal_cap1_text": "Warmth in every stitch",
    "seasonal_img2": "editorial-seasonal-2.jpg",
    "seasonal_cap2_tag": "Craft",
    "seasonal_cap2_text": "Hand-finished details",
    "seasonal_img3": "editorial-seasonal-3.jpg",
    "seasonal_cap3_tag": "Texture",
    "seasonal_cap3_text": "Natural fibres, living colour",

    # Latest Trends
    "trends_eyebrow": "THE SEASONAL FORECAST",
    "trends_title": "LATEST TRENDS",
    "trends_desc": "Explore the most celebrated silhouettes, sculptural pleating, and living natural dyes of the season. Garments designed to outlive ephemeral trends and become family heirlooms.",
    "trends_cta_text": "Discover The Edit →",
    "trends_cta_link": "/shop",
    "trends_image": "editorial-trends.jpg",

    # Handmade Process
    "process_eyebrow": "THE CRAFT",
    "process_title": "Made by Hand.",
    "process_intro": "Every piece passes through a careful journey from idea to finished garment.",
    "process_step1_title": "The Idea",
    "process_step1_desc": "A sketch, a texture, a colour or an inspiration becomes the beginning.",
    "process_step2_title": "The Fabric",
    "process_step2_desc": "Fabrics and materials are selected for their character, drape and feel.",
    "process_step3_title": "The Handwork",
    "process_step3_desc": "Stitching, embroidery and finishing are completed carefully by hand.",
    "process_step4_title": "The Final Piece",
    "process_step4_desc": "Each garment receives a final quality check before it reaches its new home.",

    # Designer Story
    "designer_eyebrow": "THE DESIGNER",
    "designer_title": "The person behind the pieces.",
    "designer_desc": "Every garment carries a part of the person who imagined and made it. Discover the story behind the studio, the craft and the collection.",
    "designer_quote": "Craft is not decoration. It is memory made visible.",
    "designer_cta_text": "Meet the designer →",
    "designer_cta_link": "#contact",
    "designer_image": "editorial-designer.jpg",

    # Custom Bespoke Order
    "custom_eyebrow": "MADE TO ORDER",
    "custom_title": "Your piece. Your story.",
    "custom_desc": "Custom clothing made around your occasion, preferences and vision. Begin a conversation with the studio.",
    "custom_cta_text": "Start a custom order →",

    # Studio Contact & Social
    "studio_phone": "+91 93504 39667",
    "studio_whatsapp": "919350439667",
    "studio_email": "contact@tulsawear.com",
    "studio_address": "Tulsa Wears Atelier, Hansi, Haryana, India - 125033",
    "studio_hours": "Mon – Sat: 10:00 AM – 7:00 PM IST",
    "instagram_handle_1": "__aannuuu.06",
    "instagram_handle_2": "tulsawear"
}

BUILT_IN_EDITOR_SECTIONS = tuple(item["id"] for item in DEFAULT_SITE_CONTENT["editor_sections"])


def validate_editor_layout(sections_json: str, custom_json: str):
    """Accept only known section ids and plain text custom-section data."""
    try:
        sections = json.loads(sections_json or "[]")
        custom_sections = json.loads(custom_json or "[]")
        if not isinstance(sections, list) or not isinstance(custom_sections, list) or len(custom_sections) > 8:
            return None
        clean_custom = []
        allowed_backgrounds = {"ivory", "cream", "dark"}
        for section in custom_sections:
            if not isinstance(section, dict):
                return None
            section_id = str(section.get("id", ""))
            if not re.fullmatch(r"custom-[a-f0-9]{8}", section_id):
                return None
            clean_custom.append({
                "id": section_id,
                "title": str(section.get("title", ""))[:120],
                "body": str(section.get("body", ""))[:1200],
                "background": section.get("background") if section.get("background") in allowed_backgrounds else "ivory",
            })
        custom_ids = {section["id"] for section in clean_custom}
        valid_ids = set(BUILT_IN_EDITOR_SECTIONS) | custom_ids
        clean_layout, seen = [], set()
        for item in sections:
            if not isinstance(item, dict):
                return None
            section_id = str(item.get("id", ""))
            if section_id not in valid_ids or section_id in seen:
                return None
            seen.add(section_id)
            width = item.get("width", 100)
            if width not in {50, 75, 90, 100}:
                width = 100
            try:
                min_height = max(0, min(640, int(item.get("min_height", 0))))
            except (TypeError, ValueError):
                min_height = 0
            clean_layout.append({
                "id": section_id,
                "visible": item.get("visible") is not False,
                "width": width,
                "min_height": min_height,
            })
        for section_id in BUILT_IN_EDITOR_SECTIONS:
            if section_id not in seen:
                clean_layout.append({"id": section_id, "visible": True, "width": 100, "min_height": 0})
        for section_id in custom_ids:
            if section_id not in seen:
                clean_layout.append({"id": section_id, "visible": True, "width": 100, "min_height": 0})
        return clean_layout, clean_custom
    except (TypeError, ValueError):
        return None


def validate_editor_theme(accent: str, background: str, font: str, spacing):
    defaults = DEFAULT_SITE_CONTENT["editor_theme"]
    accent = accent if isinstance(accent, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", accent) else defaults["accent"]
    background = background if isinstance(background, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", background) else defaults["background"]
    fonts = {"Cormorant Garamond", "Inter", "Georgia", "Arial"}
    font = font if font in fonts else defaults["heading_font"]
    try:
        spacing = max(48, min(180, int(spacing)))
    except (ValueError, TypeError):
        spacing = defaults["section_spacing"]
    return {"accent": accent, "background": background, "heading_font": font, "section_spacing": spacing}


def is_allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _legacy_site_content() -> dict:
    content = dict(DEFAULT_SITE_CONTENT)
    if os.path.exists(CONTENT_FILE_PATH):
        try:
            with open(CONTENT_FILE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    content.update(saved)
        except Exception as e:
            logger.error(f"Error loading site_content.json: {e}")
    if content.get("brand_name") == "Tulsa Wears":
        content["brand_name"] = DEFAULT_SITE_CONTENT["brand_name"]
    return content


def get_site_content(preview_draft: bool = False) -> dict:
    """Read the shared database document, importing the old JSON once."""
    try:
        db.session.expire_all()
        document = SiteContent.query.get(2 if preview_draft else 1)
        if not document:
            content = _legacy_site_content()
            save_site_content(content, publish=not preview_draft)
            return content
        content = dict(DEFAULT_SITE_CONTENT)
        saved = json.loads(document.content_json)
        if isinstance(saved, dict):
            content.update(saved)
        if content.get("brand_name") == "Tulsa Wears":
            content["brand_name"] = DEFAULT_SITE_CONTENT["brand_name"]
        return content
    except Exception:
        db.session.rollback()
        logger.exception("Shared site content unavailable; using legacy content")
        return _legacy_site_content()


def save_site_content(content_dict: dict, publish: bool = True) -> bool:
    """Persist a draft or published document and retain an immutable snapshot."""
    try:
        document_id = 1 if publish else 2
        document = SiteContent.query.get(document_id)
        if document is None:
            document = SiteContent(id=document_id, content_json="{}", revision=0)
            db.session.add(document)
        payload = json.dumps(content_dict, indent=2, ensure_ascii=False)
        snapshot = SiteContentRevision(content_json=payload, revision=0,
                                       state="published" if publish else "draft")
        db.session.add(snapshot)
        db.session.flush()
        revision = snapshot.id
        document.content_json = payload
        document.revision = revision
        snapshot.revision = revision
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        logger.exception("Error saving shared site content")
        return False


def reset_site_content(publish: bool = True) -> dict:
    """Publish factory defaults as a new version without deleting history."""
    save_site_content(DEFAULT_SITE_CONTENT, publish=publish)
    return dict(DEFAULT_SITE_CONTENT)


def publish_site_content() -> bool:
    draft = SiteContent.query.get(2)
    if not draft:
        return False
    try:
        return save_site_content(json.loads(draft.content_json), publish=True)
    except Exception:
        db.session.rollback()
        logger.exception("Could not publish draft site content")
        return False


def restore_site_content_revision(revision: int) -> bool:
    snapshot = SiteContentRevision.query.filter_by(revision=revision).first()
    if not snapshot:
        return False
    try:
        return save_site_content(json.loads(snapshot.content_json), publish=True)
    except Exception:
        db.session.rollback()
        logger.exception("Could not restore site content revision")
        return False


def process_image_upload(file_storage, upload_folder: str, prefix: str = "cms") -> str:
    """Validate, optimize, and persist public CMS imagery in shared Blob storage."""
    if not file_storage or not file_storage.filename:
        return ""
    if not is_allowed_file(file_storage.filename):
        return ""
    from PIL import Image
    try:
        file_storage.stream.seek(0)
        raw = file_storage.stream.read(16 * 1024 * 1024 + 1)
        if not raw or len(raw) > 16 * 1024 * 1024:
            return ""
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
        image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        quality = 86
        image.save(output, format="WEBP", quality=quality, method=5)
        while output.tell() > 3 * 1024 * 1024 and quality > 50:
            quality -= 8
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=quality, method=5)
        if output.tell() > 3 * 1024 * 1024:
            return ""
        from services.media_storage import put_public_image
        return put_public_image(f"storefront/{prefix}", output.getvalue())
    except Exception as exc:
        logger.warning("Storefront image rejected or Blob upload unavailable (%s)", type(exc).__name__)
        return ""
