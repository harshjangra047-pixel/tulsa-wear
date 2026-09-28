import os
import json
import logging
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

CONTENT_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "site_content.json")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "svg"}

DEFAULT_SITE_CONTENT = {
    # Announcement Bar
    "announcement_enabled": "true",
    "announcement_text": "✦ FESTIVE ATELIER — COMPLIMENTARY BESPOKE TAILORING ON ALL PRE-ORDERS ✦",
    "announcement_link": "#collections",

    # Brand Identity
    "brand_name": "Tulsa Wears",
    "brand_tagline": "Handcrafted Slow Fashion • Est. 2025",
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


def is_allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_site_content() -> dict:
    """Reads the custom site content from disk, falling back to defaults."""
    content = dict(DEFAULT_SITE_CONTENT)
    if os.path.exists(CONTENT_FILE_PATH):
        try:
            with open(CONTENT_FILE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    content.update(saved)
        except Exception as e:
            logger.error(f"Error loading site_content.json: {e}")
    return content


def save_site_content(content_dict: dict) -> bool:
    """Saves the given dictionary to database/site_content.json."""
    try:
        os.makedirs(os.path.dirname(CONTENT_FILE_PATH), exist_ok=True)
        with open(CONTENT_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(content_dict, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving site_content.json: {e}")
        return False


def reset_site_content() -> dict:
    """Resets site content back to default factory settings."""
    save_site_content(DEFAULT_SITE_CONTENT)
    return dict(DEFAULT_SITE_CONTENT)


def process_image_upload(file_storage, upload_folder: str, prefix: str = "cms") -> str:
    """Saves uploaded image file safely into upload_folder with binary verification."""
    if not file_storage or not file_storage.filename:
        return ""
    if not is_allowed_file(file_storage.filename):
        return ""

    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else "jpg"

    # SVG is text/xml based, for binary images verify with PIL
    if ext != "svg":
        try:
            from PIL import Image
            pos = file_storage.stream.tell()
            img = Image.open(file_storage.stream)
            img.verify()
            file_storage.stream.seek(pos)
        except Exception as e:
            logger.warning(f"Rejected invalid or malicious image upload: {e}")
            try:
                file_storage.stream.seek(0)
            except Exception:
                pass
            return ""

    unique_name = f"{prefix}_{os.urandom(6).hex()}.{ext}"
    target_path = os.path.join(upload_folder, unique_name)
    
    file_storage.save(target_path)
    return unique_name
