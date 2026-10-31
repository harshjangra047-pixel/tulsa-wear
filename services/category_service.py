"""Category resolution, canonical mappings, and multi-category query builder for Tulsa Wears."""

import re
from typing import List, Set


# Canonical Category Definitions & Display Names
CANONICAL_PALAZZO = "Palazzo Set"
CANONICAL_SALWAR = "Salwar Kameez"
CANONICAL_CASUAL = "Casual Wear"
CANONICAL_PARTY_WEDDING = "Party / Wedding Regalia"
CANONICAL_BEST_SELLERS = "Best Sellers"
CANONICAL_NEW_ARRIVALS = "New Arrivals"
CANONICAL_BESPOKE = "Bespoke Collection"

# Primary list of categories for dropdowns and navigation
PRIMARY_CATEGORIES = [
    CANONICAL_PALAZZO,
    CANONICAL_SALWAR,
    CANONICAL_CASUAL,
    CANONICAL_PARTY_WEDDING,
    CANONICAL_BEST_SELLERS,
    CANONICAL_NEW_ARRIVALS,
    CANONICAL_BESPOKE,
]

# Canonical Groups with all legacy and variant aliases
CATEGORY_GROUPS = {
    "palazzo": {
        "canonical": CANONICAL_PALAZZO,
        "aliases": [
            "Palazzo Set",
            "Palazzo & Kurta Set",
            "Plazo & Kurta",
            "Plazo / Kurta",
            "Plazo Kurta",
            "Plazo Set",
            "Palazzo",
            "Plazo",
            "palazzo-set",
            "palazzo-kurta-set",
            "plazo-kurta",
            "plazo-set",
        ],
    },
    "salwar": {
        "canonical": CANONICAL_SALWAR,
        "aliases": [
            "Salwar Kameez",
            "Salwar Suit",
            "Salwar",
            "Salwar / Suit",
            "salwar-kameez",
            "salwar-suit",
        ],
    },
    "casual": {
        "canonical": CANONICAL_CASUAL,
        "aliases": [
            "Casual Wear",
            "Casual / Kurti",
            "Casual Kurti",
            "Casual",
            "Casual Atelier",
            "Kurti",
            "Kurti Set",
            "casual-wear",
            "casual-kurti",
            "casual",
        ],
    },
    "party_wedding": {
        "canonical": CANONICAL_PARTY_WEDDING,
        "aliases": [
            "Party / Wedding Regalia",
            "Festival / Wedding Regalia",
            "Wedding Regalia",
            "Wedding Wear",
            "Party Wear",
            "Embroidered Party Outfit",
            "Wedding Ensemble",
            "Bridal",
            "Bridal Wear",
            "party-wedding-regalia",
            "festival-wedding-regalia",
            "wedding-regalia",
            "wedding-wear",
            "party-wear",
        ],
    },
    "best_sellers": {
        "canonical": CANONICAL_BEST_SELLERS,
        "aliases": [
            "Best Sellers",
            "Best Seller",
            "Bestsellers",
            "Bestseller",
            "best-sellers",
            "bestsellers",
        ],
    },
    "new_arrivals": {
        "canonical": CANONICAL_NEW_ARRIVALS,
        "aliases": [
            "New Arrivals",
            "New Arrival",
            "new-arrivals",
            "new-arrival",
            "New",
        ],
    },
    "bespoke": {
        "canonical": CANONICAL_BESPOKE,
        "aliases": [
            "Bespoke Collection",
            "Bespoke",
            "Custom Bespoke",
            "bespoke-collection",
            "bespoke",
        ],
    },
}


def slugify(text: str) -> str:
    """Normalize text into an alphanumeric hyphenated slug."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def resolve_canonical_category(category_name: str) -> str:
    """Return the display canonical category name for any input or alias."""
    if not category_name:
        return ""
    cat_clean = category_name.strip()
    cat_slug = slugify(cat_clean)

    for group in CATEGORY_GROUPS.values():
        if cat_clean.lower() == group["canonical"].lower():
            return group["canonical"]
        for alias in group["aliases"]:
            if cat_clean.lower() == alias.lower() or cat_slug == slugify(alias):
                return group["canonical"]

    return cat_clean


def get_equivalent_categories(category_name: str) -> Set[str]:
    """
    Given any category string, return all possible alias strings that could
    be stored in the database for matching products.
    """
    if not category_name:
        return set()

    cat_clean = category_name.strip()
    cat_slug = slugify(cat_clean)

    for group in CATEGORY_GROUPS.values():
        matches = False
        if cat_clean.lower() == group["canonical"].lower() or cat_slug == slugify(group["canonical"]):
            matches = True
        else:
            for alias in group["aliases"]:
                if cat_clean.lower() == alias.lower() or cat_slug == slugify(alias):
                    matches = True
                    break

        if matches:
            # Return canonical plus all aliases
            return set(group["aliases"] + [group["canonical"]])

    return {cat_clean}


def is_category_active(pill_cat: str, selected_cat: str) -> bool:
    """Check if a navigation pill corresponds to the currently selected category."""
    if not pill_cat or not selected_cat:
        return False

    c1 = resolve_canonical_category(pill_cat)
    c2 = resolve_canonical_category(selected_cat)
    if c1 and c2 and c1.lower() == c2.lower():
        return True

    return pill_cat.strip().lower() == selected_cat.strip().lower()


def filter_products_by_category(query, category_name: str, product_model=None):
    """
    Filters a Product query by category taking into account:
    - Primary category (Product.category)
    - Alternative category 1 (Product.category_2)
    - Alternative category 2 (Product.category_3)
    - Alternative category 3 (Product.category_4)
    - Best seller flag when Best Sellers category is requested
    - Normalized ProductCategory table relationship if present
    Avoids duplicate product records in the result set.
    """
    if not category_name:
        return query

    if product_model is None:
        from models.product import Product
        product_model = Product

    cat_clean = category_name.strip()
    canonical = resolve_canonical_category(cat_clean)
    equivalents = list(get_equivalent_categories(cat_clean))

    from sqlalchemy import or_

    filters = [
        product_model.category.in_(equivalents),
    ]

    # Check for category_2, category_3, category_4 columns
    if hasattr(product_model, "category_2"):
        filters.append(product_model.category_2.in_(equivalents))
    if hasattr(product_model, "category_3"):
        filters.append(product_model.category_3.in_(equivalents))
    if hasattr(product_model, "category_4"):
        filters.append(product_model.category_4.in_(equivalents))

    # Also handle Best Sellers flag
    if canonical == CANONICAL_BEST_SELLERS or any(slugify(e) in ["best-sellers", "bestseller", "bestsellers"] for e in equivalents):
        filters.append(product_model.best_seller == True)

    try:
        from models.product_category import ProductCategory
        filters.append(
            product_model.id.in_(
                product_model.query.session.query(ProductCategory.product_id).filter(
                    ProductCategory.category.in_(equivalents)
                )
            )
        )
    except Exception:
        pass

    return query.filter(or_(*filters)).distinct()
