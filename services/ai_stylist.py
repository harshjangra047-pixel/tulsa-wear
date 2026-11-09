import os
import re
import json
from models.product import Product

def get_catalog_context():
    """Retrieve all available database products in a structured format."""
    products = Product.query.filter(Product.stock > 0).all()
    catalog = []
    for p in products:
        catalog.append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "category": p.category,
            "fabric": p.fabric or "Handmade fabric",
            "color": p.color or "Artisanal dye",
            "description": p.description or "",
            "image": p.image or "",
            "stock": p.stock,
            "best_seller": p.best_seller
        })
    return catalog

def ask_ai_stylist(user_query):
    """
    Main entry point for AI Fashion Concierge.
    Uses Gemini API when key is configured, otherwise uses local catalog matcher.
    """
    catalog = get_catalog_context()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if api_key and api_key != "your_gemini_api_key_here":
        try:
            from google import genai
            client = genai.Client(api_key=api_key)

            system_instruction = (
                "You are the senior fashion director and personal stylist for 'Atelier', a luxury handmade fashion house. "
                "Your tone is sophisticated, poetic, warm, and deeply knowledgeable about textiles, craftsmanship, silhouette, and styling. "
                "CRITICAL INSTRUCTION: You must strictly recommend ONLY products from the provided Atelier catalog below. Never invent products that do not exist. "
                "At the very end of your response, output a single JSON array with the matching product IDs like this: [RECOMMENDED_IDS: [1, 2]]."
            )

            prompt = f"Customer Query: {user_query}\n\nAvailable Atelier Catalog:\n{json.dumps(catalog, indent=2)}"

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{system_instruction}\n\n{prompt}"
            )

            raw_text = response.text or ""
            # Extract recommended product IDs if present
            id_match = re.search(r"\[RECOMMENDED_IDS:\s*(\[[0-9,\s]*\])\]", raw_text)
            rec_ids = []
            clean_message = raw_text

            if id_match:
                try:
                    rec_ids = json.loads(id_match.group(1))
                    clean_message = raw_text.replace(id_match.group(0), "").strip()
                except Exception:
                    rec_ids = []

            # Find matching products from catalog
            recommended_products = [p for p in catalog if p["id"] in rec_ids]

            # If Gemini didn't format IDs or found none, fallback to matching by product names mentioned in text
            if not recommended_products:
                for p in catalog:
                    if p["name"].lower() in clean_message.lower():
                        if p not in recommended_products:
                            recommended_products.append(p)

            if not recommended_products:
                # Fallback to local matcher for products to ensure visual cards are always provided
                recommended_products = local_catalog_matcher(user_query, catalog)

            return {
                "message": clean_message,
                "products": recommended_products[:3]
            }

        except Exception as e:
            # If Gemini API call errors (e.g. quota or network), fall back smoothly
            pass

    # Local Intelligent Stylist Engine (when API key is absent or pending)
    matched_products = local_catalog_matcher(user_query, catalog)
    editorial_message = generate_editorial_advice(user_query, matched_products)

    return {
        "message": editorial_message,
        "products": matched_products[:3]
    }

def local_catalog_matcher(query, catalog):
    """Grounded matching engine based on occasion, budget, fabric, and color."""
    q = query.lower()
    scores = {}

    # Detect budget limits
    budget_match = re.search(r"(?:under|below|less than|within)\s*(?:₹|rs\.?|inr)?\s*([0-9,]+)", q)
    max_budget = None
    if budget_match:
        try:
            max_budget = float(budget_match.group(1).replace(",", ""))
        except ValueError:
            pass

    for p in catalog:
        score = 0
        p_name = p["name"].lower()
        p_cat = p["category"].lower()
        p_fab = (p["fabric"] or "").lower()
        p_col = (p["color"] or "").lower()
        p_desc = (p["description"] or "").lower()

        # Budget constraint
        if max_budget is not None and p["price"] > max_budget:
            continue

        # Occasion & Category checks
        if "wedding" in q and "wedding" in p_cat:
            score += 10
        if "party" in q and "party" in p_cat:
            score += 10
        if ("everyday" in q or "daily" in q or "casual" in q) and "plazo" in p_cat:
            score += 8
        if "salwar" in q and "salwar" in p_cat:
            score += 8
        if "kurta" in q and "kurta" in p_name:
            score += 8

        # Fabric checks
        if "cotton" in q and "cotton" in p_fab:
            score += 6
        if "silk" in q and "silk" in p_fab:
            score += 6
        if "mulmul" in q and "mulmul" in p_fab:
            score += 6
        if "linen" in q and "linen" in p_fab:
            score += 6

        # Color checks
        if p_col and p_col in q:
            score += 5

        # Best sellers preference
        if "best" in q and p["best_seller"]:
            score += 7

        # General keyword matching
        words = [w for w in q.split() if len(w) > 3]
        for w in words:
            if w in p_name or w in p_desc:
                score += 3

        if score > 0:
            scores[p["id"]] = score

    # Sort catalog items by score
    sorted_items = sorted(catalog, key=lambda p: scores.get(p["id"], 0), reverse=True)
    results = [p for p in sorted_items if scores.get(p["id"], 0) > 0]

    # If no strict match found, return curated best sellers within budget if specified
    if not results:
        results = [p for p in catalog if max_budget is None or p["price"] <= max_budget]

    return results

def generate_editorial_advice(query, matched_products):
    """Generate evocative, luxury stylist guidance matching the Atelier brand."""
    q = query.lower()

    if not matched_products:
        return (
            "We could not find an exact piece matching all criteria in our current atelier collection. "
            "However, every garment can be tailored or customized to your specific measurements and fabric preferences."
        )

    top_piece = matched_products[0]

    if "wedding" in q:
        return (
            f"For a celebration of this scale, richness in texture and artisanal handwork are paramount. "
            f"We recommend our {top_piece['name']} (₹{top_piece['price']:,.0f}), handcrafted in luxurious {top_piece['fabric']}. "
            f"Its {top_piece['color'].lower()} hue and delicate embroidery catch natural light gracefully, creating a timeless ceremonial silhouette."
        )
    elif "party" in q:
        return (
            f"For evening gatherings and celebrations, elegance lies in subtle drama and refined craftsmanship. "
            f"Our {top_piece['name']} in {top_piece['fabric']} pairs sculptural tailoring with fine hand-applied details. "
            f"It moves with effortless ease while making a quiet, commanding impression."
        )
    elif "cotton" in q or "everyday" in q or "summer" in q:
        return (
            f"Slow craftsmanship excels in everyday pieces that touch the skin. "
            f"The {top_piece['name']} is cut from pure {top_piece['fabric']}, allowing maximum breathability and effortless drape. "
            f"Finished with meticulous hand-stitching, it offers quiet luxury for daily living."
        )
    elif "under" in q or "budget" in q:
        return (
            f"True luxury is found in intentional design and human handiwork, regardless of scale. "
            f"Within your desired range, our {top_piece['name']} (₹{top_piece['price']:,.0f}) represents exceptional artisanal value, "
            f"tailored in {top_piece['fabric']} with hand-finished hems."
        )
    else:
        return (
            f"Based on your aesthetic preference, we recommend the {top_piece['name']} (₹{top_piece['price']:,.0f}). "
            f"Created in {top_piece['fabric']} with artisanal finishing, this piece embodies the studio's slow-fashion philosophy."
        )

def ask_ai_about_product(product, question):
    """Specific Q&A for a single product detail page."""
    q = question.lower()
    
    if "fabric" in q or "material" in q:
        return f"{product.name} is handcrafted using authentic {product.fabric or 'hand-selected natural fibres'}, chosen for its soft drape, breathability, and enduring quality."
    elif "occasion" in q or "wear" in q:
        return f"This garment belongs to our {product.category} atelier collection. It is designed for occasions requiring thoughtful elegance and effortless sophistication."
    elif "custom" in q or "fit" in q or "measurement" in q:
        return "Yes! As an artisanal studio, we welcome custom sizing and subtle sleeve or length adjustments. Reach out through our made-to-order service."
    elif "care" in q or "wash" in q:
        return "Because each piece features hand-worked details, we recommend gentle dry cleaning or mild hand-washing in cold water with eco-friendly detergent to preserve the fibers."
    elif "handmade" in q or "craft" in q:
        return "Every single stitch and embroidered accent on this piece is executed by master handcraft artisans in our slow-fashion studio."
    else:
        return f"{product.name} is available for ₹{product.price:,.0f}. {product.description or 'A signature piece from our atelier.'}"

def answer_customer_support(query: str, current_customer=None):
    """
    Unified AI Customer Support Concierge answering questions using verified
    catalog, size charts, store policies, and customer order records.
    """
    q = (query or "").lower().strip()
    show_human_handoff = False
    products = []

    # 1. Size and Fit Assistance
    if any(k in q for k in ["size", "sizing", "measurement", "fit", "chart", "bust", "waist"]):
        msg = (
            "✦ Tulsa Size & Fit Guide ✦\n\n"
            "Our garments follow authentic Indian artisanal sizing across 9 sizes (XXS to 4XL):\n"
            "• XXS: Bust 30\" | Waist 26\" | Hip 34\" | Kurti Length 28\"\n"
            "• XS: Bust 32\" | Waist 28\" | Hip 36\" | Kurti Length 28\"\n"
            "• S: Bust 34\" | Waist 30\" | Hip 38\" | Kurti Length 28\"\n"
            "• M: Bust 36\" | Waist 32\" | Hip 40\" | Kurti Length 28\"\n"
            "• L: Bust 38\" | Waist 34\" | Hip 42\" | Kurti Length 30\"\n"
            "• XL: Bust 40\" | Waist 36\" | Hip 44\" | Kurti Length 30\"\n"
            "• XXL: Bust 42\" | Waist 38\" | Hip 46\" | Kurti Length 30\"\n"
            "• 3XL: Bust 44\" | Waist 40\" | Hip 48\" | Kurti Length 30\"\n"
            "• 4XL: Bust 48\" | Waist 45\" | Hip 52\" | Kurti Length 30\"\n\n"
            "Bottom Pants have a standard length of 40\". If you wish to customize the length or sleeve fit, you can DM our Hansi studio on WhatsApp for complimentary alterations."
        )

    # 2. Order Status
    elif any(k in q for k in ["order", "track", "delivery status", "where is my", "dispatch"]):
        if current_customer:
            from models.order import Order
            recent_orders = Order.query.filter_by(customer_id=current_customer.id).order_by(Order.created_at.desc()).limit(3).all()
            if recent_orders:
                lines = [f"Namaste {current_customer.name}, here are your recent order coordinates:"]
                for o in recent_orders:
                    status_line = f"• Order #{o.id}: {o.product_name} (₹{o.price:,.0f}) — Status: {o.status} ({o.payment_status})"
                    if o.tracking_id:
                        status_line += f" | Tracking: {o.tracking_id}"
                    lines.append(status_line)
                lines.append("\nYou can track live milestones on your Account Orders hub or message our studio desk.")
                msg = "\n".join(lines)
            else:
                msg = f"Namaste {current_customer.name}, we do not see any active orders registered under your account yet. You can explore our collection in the shop!"
        else:
            msg = (
                "To check your active order status, please sign in to your Tulsa account, or provide your Order Number and registered phone number. "
                "You can also use our self-service order lookup portal at /track-order."
            )

    # 3. Shipping & Delivery Information
    elif any(k in q for k in ["ship", "delivery", "dispatch time", "courier", "how long"]):
        msg = (
            "✦ Shipping & Delivery Policy ✦\n\n"
            "Every Tulsa ensemble is tailored thoughtfully by hand in our Hansi, Haryana atelier.\n"
            "• Standard Slow-Fashion Delivery: 7 to 10 business days across India.\n"
            "• Complimentary insured shipping on all bespoke and bridal pre-orders.\n"
            "• Real-time courier tracking updates sent via SMS & WhatsApp upon dispatch."
        )

    # 4. Payment & Checkout Assistance
    elif any(k in q for k in ["payment", "pay", "upi", "google pay", "razorpay", "card", "cod"]):
        msg = (
            "✦ Payment & Security ✦\n\n"
            "We accept all secure digital payment methods powered by 256-bit SSL encrypted Razorpay:\n"
            "• Instant UPI (Google Pay, PhonePe, Paytm, BHIM)\n"
            "• Credit & Debit Cards (Visa, Mastercard, RuPay, Amex)\n"
            "• Netbanking across all major Indian banks\n"
            "• For bespoke bridal regalia, partial advance payment is supported via direct atelier UPI."
        )

    # 5. Return & Exchange Policy
    elif any(k in q for k in ["return", "exchange", "refund", "cancel"]):
        msg = (
            "✦ Return & Alteration Policy ✦\n\n"
            "Because each garment is handcrafted specifically for you in our slow-fashion atelier, we do not mass-produce inventory.\n"
            "• Size Alterations: We provide complimentary bespoke alteration support if the fit requires subtle adjustments.\n"
            "• Exchange Window: Eligible within 7 days of delivery for unworn pieces with artisanal tags intact.\n"
            "• To initiate an alteration or exchange, connect with our client care team on WhatsApp."
        )
        show_human_handoff = True

    # 6. Human Support Escalation
    elif any(k in q for k in ["human", "talk to", "agent", "call", "whatsapp", "phone", "contact", "person"]):
        msg = (
            "Our master artisans and client care team in Hansi are available Monday through Saturday (10:00 AM – 7:00 PM IST). "
            "You can continue this conversation directly on WhatsApp or call our studio hotline below."
        )
        show_human_handoff = True

    # 7. Default: Product recommendation & Style Studio
    else:
        stylist_res = ask_ai_stylist(query)
        msg = stylist_res.get("message", "Here are curated pieces from our slow-fashion repertory:")
        products = stylist_res.get("products", [])

    return {
        "message": msg,
        "products": products,
        "show_human_handoff": show_human_handoff
    }
