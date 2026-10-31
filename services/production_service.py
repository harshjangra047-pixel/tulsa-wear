"""Tulsa Wears Production Management, Smart Manufacturing Queue & Business Intelligence Service.

Handles:
1. Consolidated garment-wise production aggregation across multi-garment orders.
2. Date-wise order groupings in Asia/Kolkata timezone.
3. Smart production priority queue calculations & deadline risk alerts.
4. Batch creation, size-wise completion tracking, material readiness & QC gates.
5. Workload, preparation time, and daily capacity utilization management.
6. Product-level sales analytics, comparative growth, category breakdown, and AI business recommendations.
"""
import os
import json
import logging
from datetime import datetime, date, timedelta
from collections import defaultdict

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from datetime import timezone
    ZoneInfo = lambda name: timezone(timedelta(hours=5, minutes=30))

from sqlalchemy import or_, and_, desc, asc

from models.database import db
from models.order import Order
from models.product import Product
from models.production_batch import ProductionBatch
from models.production_allocation import ProductionAllocation
from models.production_setting import ProductionSetting

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


# ==========================================================
# 1. DATE RANGE RESOLUTION & TIMEZONE HELPERS
# ==========================================================

def get_kolkata_now():
    """Return current localized datetime in Asia/Kolkata."""
    return datetime.now(KOLKATA_TZ)


def resolve_date_range(range_preset="all", custom_start=None, custom_end=None):
    """
    Compute start and end datetimes in Asia/Kolkata for filtering,
    along with equivalent prior period start/end for comparative analytics.
    Returns:
        (start_dt, end_dt, prior_start_dt, prior_end_dt, display_label)
    """
    now = get_kolkata_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    preset = (range_preset or "all").lower().strip()

    if preset == "today":
        start = today_start
        end = today_end
        prior_start = start - timedelta(days=1)
        prior_end = start - timedelta(microseconds=1)
        label = "Today"

    elif preset == "yesterday":
        start = today_start - timedelta(days=1)
        end = today_start - timedelta(microseconds=1)
        prior_start = start - timedelta(days=1)
        prior_end = start - timedelta(microseconds=1)
        label = "Yesterday"

    elif preset in ("2days", "last_2_days", "2d"):
        start = today_start - timedelta(days=1)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 2 Days"

    elif preset in ("7days", "last_7_days", "7d"):
        start = today_start - timedelta(days=6)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 7 Days"

    elif preset in ("14days", "last_14_days", "14d"):
        start = today_start - timedelta(days=13)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 14 Days"

    elif preset in ("30days", "last_30_days", "30d"):
        start = today_start - timedelta(days=29)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 30 Days"

    elif preset in ("7weeks", "last_7_weeks", "7w"):
        start = today_start - timedelta(days=48)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 7 Weeks"

    elif preset in ("this_month", "month"):
        start = today_start.replace(day=1)
        end = today_end
        # Prior month equivalent
        first_of_this_month = start
        last_day_of_prior_month = first_of_this_month - timedelta(days=1)
        prior_start = last_day_of_prior_month.replace(day=1)
        prior_end = last_day_of_prior_month.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = "This Month"

    elif preset in ("prev_month", "previous_month"):
        first_of_this_month = today_start.replace(day=1)
        end = first_of_this_month - timedelta(microseconds=1)
        start = (first_of_this_month - timedelta(days=1)).replace(day=1)
        # Prior prior month
        prior_end = start - timedelta(microseconds=1)
        prior_start = (start - timedelta(days=1)).replace(day=1)
        label = "Previous Month"

    elif preset in ("90days", "last_90_days"):
        start = today_start - timedelta(days=89)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 90 Days"

    elif preset in ("6months", "last_6_months"):
        start = today_start - timedelta(days=179)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 6 Months"

    elif preset in ("1year", "last_1_year"):
        start = today_start - timedelta(days=364)
        end = today_end
        duration = end - start
        prior_end = start - timedelta(microseconds=1)
        prior_start = prior_end - duration
        label = "Last 1 Year"

    elif preset == "custom" and custom_start and custom_end:
        try:
            start_parts = [int(p) for p in str(custom_start).split("-")]
            end_parts = [int(p) for p in str(custom_end).split("-")]
            start = datetime(start_parts[0], start_parts[1], start_parts[2], 0, 0, 0, tzinfo=KOLKATA_TZ)
            end = datetime(end_parts[0], end_parts[1], end_parts[2], 23, 59, 59, 999999, tzinfo=KOLKATA_TZ)
            if start > end:
                start, end = end, start
            duration = end - start
            prior_end = start - timedelta(microseconds=1)
            prior_start = prior_end - duration
            label = f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
        except Exception:
            start = None
            end = None
            prior_start = None
            prior_end = None
            label = "All Time"
    else:
        # All Time
        start = None
        end = None
        prior_start = None
        prior_end = None
        label = "All Time"

    return start, end, prior_start, prior_end, label


def order_placed_in_range(order_created_at, start_dt, end_dt):
    """Check if order creation timestamp falls within localized window."""
    if not order_created_at:
        return True
    if start_dt is None or end_dt is None:
        return True

    # Normalize created_at to timezone-aware Kolkata
    if order_created_at.tzinfo is None:
        dt = order_created_at.replace(tzinfo=KOLKATA_TZ)
    else:
        dt = order_created_at.astimezone(KOLKATA_TZ)

    return start_dt <= dt <= end_dt


# ==========================================================
# 2. DATE-WISE ORDER MANAGEMENT ENGINE
# ==========================================================

def get_date_wise_orders(orders=None, date_filter="all", start_date=None, end_date=None, search_query=None):
    """
    Organizes orders grouped strictly by actual customer placement date in Asia/Kolkata.
    Returns:
        list of date blocks, each with date_str, formatted date label, orders_count,
        total_garments, total_revenue, and the list of orders.
    """
    start_dt, end_dt, _, _, _ = resolve_date_range(date_filter, start_date, end_date)

    if orders is None:
        query = Order.query
        if search_query:
            sq = f"%{search_query.strip()}%"
            query = query.filter(
                or_(
                    Order.id.cast(db.String).ilike(sq),
                    Order.customer_name.ilike(sq),
                    Order.phone.ilike(sq),
                    Order.email.ilike(sq),
                    Order.product_name.ilike(sq),
                    Order.upi_utr.ilike(sq),
                    Order.tracking_id.ilike(sq),
                )
            )
        orders = query.order_by(desc(Order.created_at)).all()

    # Filter by date range
    filtered = [o for o in orders if order_placed_in_range(o.created_at, start_dt, end_dt)]

    date_groups = defaultdict(list)
    for o in filtered:
        if o.created_at:
            if o.created_at.tzinfo is None:
                local_dt = o.created_at.replace(tzinfo=KOLKATA_TZ)
            else:
                local_dt = o.created_at.astimezone(KOLKATA_TZ)
            d_key = local_dt.strftime("%Y-%m-%d")
            d_label = local_dt.strftime("%d %B %Y").upper()
        else:
            d_key = "UNKNOWN"
            d_label = "DATE NOT RECORDED"
        date_groups[(d_key, d_label)].append(o)

    # Sort dates descending (newest first)
    sorted_groups = sorted(date_groups.items(), key=lambda x: x[0][0], reverse=True)

    result = []
    for (d_key, d_label), day_orders in sorted_groups:
        total_garments = 0
        day_revenue = 0.0
        for o in day_orders:
            items = o.get_items()
            total_garments += sum(int(it.get("quantity") or 1) for it in items)
            if (o.status or "").lower() != "cancelled":
                day_revenue += float(o.price or 0.0)

        result.append({
            "date_key": d_key,
            "date_label": d_label,
            "orders_count": len(day_orders),
            "total_garments": total_garments,
            "total_revenue": day_revenue,
            "orders": day_orders
        })

    return result


# ==========================================================
# 3. GARMENT-WISE CONSOLIDATED PRODUCTION PLANNING ENGINE
# ==========================================================

def calculate_priority_score(order, total_garment_qty=1):
    """
    Computes priority based on delivery deadline, order age, piece volume, and production status.
    Returns:
        (priority_level, priority_reason_text)
    """
    now = get_kolkata_now()
    reasons = []
    level = "Medium"

    # Deadline factor (7-15 days delivery window)
    deadline_days_left = None
    if order.delivery_window_end:
        try:
            # Format e.g. "15 Nov 2026"
            deadline_dt = datetime.strptime(order.delivery_window_end.strip(), "%d %b %Y").replace(tzinfo=KOLKATA_TZ)
            diff = (deadline_dt.date() - now.date()).days
            deadline_days_left = diff
        except Exception:
            pass

    if deadline_days_left is not None:
        if deadline_days_left <= 2:
            level = "Critical"
            reasons.append(f"Imminent deadline: {deadline_days_left} day(s) left until delivery window ends")
        elif deadline_days_left <= 4:
            if level != "Critical":
                level = "High"
            reasons.append(f"Approaching deadline: {deadline_days_left} days left")
        else:
            reasons.append(f"Delivery window end: {order.delivery_window_end} ({deadline_days_left} days left)")

    # Volume factor (higher batch efficiency)
    if total_garment_qty >= 10:
        if level not in ("Critical", "High"):
            level = "High"
        reasons.append(f"High-volume batch ({total_garment_qty} pieces accumulated)")
    elif total_garment_qty >= 5:
        reasons.append(f"Medium batch size ({total_garment_qty} pieces)")

    # Age factor
    if order.created_at:
        age_days = (now.date() - order.created_at.date()).days
        if age_days >= 5 and level != "Critical":
            level = "High"
            reasons.append(f"Order pending for {age_days} days")

    reason_str = " • ".join(reasons) if reasons else "Standard production sequence"
    return level, reason_str


def get_consolidated_production_queue(status_filter=None, search_query=None):
    """
    Gathers all active orders and consolidates ordered items strictly by canonical garment identity.
    Combines identical dresses ordered by multiple customers on different days.
    Provides:
        - Total quantity required
        - Total completed
        - Total remaining
        - Size-wise breakdown table
        - Date-wise arrivals timeline
        - Linked orders list
        - Smart production priority score & reason
        - Estimated work hours
    """
    # Active orders = non-cancelled, non-delivered orders awaiting production/dispatch
    query = Order.query.filter(
        ~Order.status.ilike("%cancel%"),
        ~Order.status.ilike("%deliver%")
    )

    if search_query:
        sq = f"%{search_query.strip()}%"
        query = query.filter(
            or_(
                Order.customer_name.ilike(sq),
                Order.product_name.ilike(sq),
                Order.id.cast(db.String).ilike(sq)
            )
        )

    orders = query.order_by(asc(Order.created_at)).all()

    # Pre-load products catalog for canonical data & image lookup
    products_by_id = {p.id: p for p in Product.query.all()}
    products_by_name = {p.name.strip().lower(): p for p in products_by_id.values()}
    settings = ProductionSetting.get_settings()

    # Grouping key: (canonical_product_id, canonical_product_name)
    grouped = {}

    for order in orders:
        items = order.get_items()
        for item in items:
            p_id = item.get("product_id") or order.product_id
            p_name = (item.get("name") or order.product_name or "Garment").strip()
            qty = int(item.get("quantity") or 1)
            size = (item.get("size") or order.size or "M").strip().upper()
            color = item.get("color") or getattr(order, "color", None) or "Standard"

            # Match canonical Product record
            matched_product = products_by_id.get(p_id) or products_by_name.get(p_name.lower())
            canonical_id = matched_product.id if matched_product else (p_id or 0)
            canonical_name = matched_product.name if matched_product else p_name
            sku = matched_product.effective_sku if matched_product else f"TW-PROD-{canonical_id:04d}"
            image_url = matched_product.primary_photo_url if matched_product else (item.get("image") or "product-1.jpg")
            category = matched_product.category if matched_product else "Haute Couture"

            group_key = (canonical_id, canonical_name)
            if group_key not in grouped:
                grouped[group_key] = {
                    "product_id": canonical_id,
                    "product_name": canonical_name,
                    "sku": sku,
                    "image": image_url,
                    "category": category,
                    "total_ordered": 0,
                    "completed_quantity": 0,
                    "remaining_quantity": 0,
                    "size_breakdown": defaultdict(int),
                    "size_completed": defaultdict(int),
                    "color_breakdown": defaultdict(lambda: defaultdict(int)),
                    "date_arrivals": defaultdict(lambda: {"quantity": 0, "order_ids": []}),
                    "linked_orders": [],
                    "earliest_order_date": order.created_at,
                    "earliest_delivery_deadline": order.delivery_window_end,
                    "orders_set": set(),
                    "priority": "Medium",
                    "priority_reason": "",
                    "estimated_minutes_per_piece": 180,
                    "total_estimated_hours": 0.0,
                    "production_status": "Pending",
                    "batch_id": None,
                }

            entry = grouped[group_key]
            entry["total_ordered"] += qty
            entry["size_breakdown"][size] += qty
            entry["color_breakdown"][color][size] += qty

            # Date of arrival tracking
            if order.created_at:
                if order.created_at.tzinfo is None:
                    local_dt = order.created_at.replace(tzinfo=KOLKATA_TZ)
                else:
                    local_dt = order.created_at.astimezone(KOLKATA_TZ)
                date_str = local_dt.strftime("%d %b %Y")
            else:
                date_str = "Recent"

            entry["date_arrivals"][date_str]["quantity"] += qty
            if order.id not in entry["date_arrivals"][date_str]["order_ids"]:
                entry["date_arrivals"][date_str]["order_ids"].append(order.id)

            # Linked orders tracking
            if order.id not in entry["orders_set"]:
                entry["orders_set"].add(order.id)
                entry["linked_orders"].append({
                    "order_id": order.id,
                    "customer_name": order.customer_name,
                    "phone": order.phone,
                    "size": size,
                    "quantity": qty,
                    "price": order.price,
                    "created_at": order.created_at.strftime("%d %b %Y") if order.created_at else "-",
                    "status": order.status,
                    "production_status": getattr(order, "production_status", "Pending") or "Pending",
                    "delivery_window": f"{order.delivery_window_start} – {order.delivery_window_end}" if order.delivery_window_start else "7–15 Days",
                })

            # Check if order item has completed production
            if getattr(order, "production_status", "") in ("Completed", "Ready for Dispatch", "Dispatched"):
                entry["completed_quantity"] += qty
                entry["size_completed"][size] += qty

    # Check for active ProductionBatches to pull live batch progress
    active_batches = ProductionBatch.query.filter(
        ProductionBatch.status.notin_(["Dispatched", "Cancelled"])
    ).all()
    batch_map = {}
    for b in active_batches:
        key = (b.product_id or 0, b.product_name)
        batch_map[key] = b

    # Finalize calculations for each consolidated product
    consolidated_list = []
    for (c_id, c_name), data in grouped.items():
        data["remaining_quantity"] = max(0, data["total_ordered"] - data["completed_quantity"])

        # Check existing batch
        matched_batch = batch_map.get((c_id, c_name))
        if matched_batch:
            data["batch_id"] = matched_batch.id
            data["batch_number"] = matched_batch.batch_number
            data["production_status"] = matched_batch.status
            data["material_status"] = matched_batch.material_status
            data["completed_quantity"] = matched_batch.completed_quantity
            data["remaining_quantity"] = matched_batch.get_remaining_quantity()
            # Overlay size completed
            data["size_completed"] = matched_batch.get_completed_sizes()
        else:
            if data["completed_quantity"] >= data["total_ordered"] and data["total_ordered"] > 0:
                data["production_status"] = "Completed"
            elif data["completed_quantity"] > 0:
                data["production_status"] = "Partially Completed"
            else:
                data["production_status"] = "Pending"

        # Prep time based on category
        cat_lower = (data["category"] or "").lower()
        if "kurti" in cat_lower or "casual" in cat_lower:
            mins_per_piece = settings.kurti_prep_minutes
        elif "palazzo" in cat_lower or "salwar" in cat_lower:
            mins_per_piece = settings.palazzo_prep_minutes
        elif "party" in cat_lower or "wedding" in cat_lower or "regalia" in cat_lower:
            mins_per_piece = settings.partywear_prep_minutes
        elif "embroider" in cat_lower or "anarkali" in cat_lower:
            mins_per_piece = settings.embroidered_prep_minutes
        else:
            mins_per_piece = 180

        data["estimated_minutes_per_piece"] = mins_per_piece
        total_mins = (mins_per_piece * data["remaining_quantity"]) + settings.batch_setup_minutes
        data["total_estimated_hours"] = round(total_mins / 60.0, 1)

        # Priority calculation
        sample_order = db.session.get(Order, list(data["orders_set"])[0]) if data["orders_set"] else None
        if sample_order:
            priority, reason = calculate_priority_score(sample_order, data["total_ordered"])
            data["priority"] = priority
            data["priority_reason"] = reason

        # Format date arrivals list sorted by date
        data["date_arrivals_list"] = [
            {"date": d, "quantity": info["quantity"], "orders": info["order_ids"]}
            for d, info in data["date_arrivals"].items()
        ]

        # Convert defaultdicts to regular dicts for clean template access
        data["size_breakdown"] = dict(data["size_breakdown"])
        data["size_completed"] = dict(data["size_completed"])

        consolidated_list.append(data)

    # Sort queue by priority weight (Critical > High > Medium > Low), then total remaining qty desc
    priority_order = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
    consolidated_list.sort(
        key=lambda x: (
            priority_order.get(x["priority"], 0),
            x["remaining_quantity"],
            x["total_ordered"]
        ),
        reverse=True
    )

    return consolidated_list


# ==========================================================
# 4. PRODUCTION OVERVIEW KPIS & DASHBOARD SUMMARY
# ==========================================================

def get_production_overview_kpis():
    """Calculates all key production ERP performance metrics directly from the database."""
    now = get_kolkata_now()

    all_active_orders = Order.query.filter(
        ~Order.status.ilike("%cancel%"),
        ~Order.status.ilike("%deliver%")
    ).all()

    total_active_orders = len(all_active_orders)
    total_garments_ordered = 0
    unique_designs_set = set()
    awaiting_count = 0
    in_production_count = 0
    ready_for_dispatch_count = 0
    at_risk_count = 0
    delayed_count = 0

    for o in all_active_orders:
        items = o.get_items()
        total_garments_ordered += sum(int(it.get("quantity") or 1) for it in items)
        for it in items:
            unique_designs_set.add(it.get("product_id") or it.get("name"))

        prod_st = (getattr(o, "production_status", "") or "Pending").lower()
        if prod_st in ("completed", "ready for dispatch"):
            ready_for_dispatch_count += 1
        elif prod_st in ("in production", "partially completed", "in tailoring"):
            in_production_count += 1
        else:
            awaiting_count += 1

        # Deadline evaluation
        if o.delivery_window_end:
            try:
                deadline_dt = datetime.strptime(o.delivery_window_end.strip(), "%d %b %Y").date()
                diff_days = (deadline_dt - now.date()).days
                if diff_days < 0 and prod_st not in ("completed", "ready for dispatch"):
                    delayed_count += 1
                elif diff_days <= 3 and prod_st not in ("completed", "ready for dispatch"):
                    at_risk_count += 1
            except Exception:
                pass

    # Batch-level pieces calculation
    all_batches = ProductionBatch.query.filter(
        ProductionBatch.status.notin_(["Dispatched", "Cancelled"])
    ).all()

    batch_pieces_completed = sum(b.completed_quantity for b in all_batches)
    queue = get_consolidated_production_queue()
    total_pieces_to_prepare = sum(item["remaining_quantity"] for item in queue)
    total_pieces_completed = sum(item["completed_quantity"] for item in queue)

    settings = ProductionSetting.get_settings()
    total_workload_hours = sum(item["total_estimated_hours"] for item in queue)
    daily_capacity = settings.daily_capacity_hours or 32.0
    estimated_work_days = round(total_workload_hours / max(1.0, daily_capacity), 1)

    return {
        "total_active_orders": total_active_orders,
        "total_garments_ordered": total_garments_ordered,
        "unique_designs": len(unique_designs_set),
        "total_pieces_to_prepare": total_pieces_to_prepare,
        "pieces_completed": total_pieces_completed,
        "pieces_remaining": total_pieces_to_prepare,
        "orders_awaiting_production": awaiting_count,
        "orders_in_production": in_production_count,
        "orders_ready_for_dispatch": ready_for_dispatch_count,
        "orders_at_risk": at_risk_count,
        "orders_delayed": delayed_count,
        "total_workload_hours": round(total_workload_hours, 1),
        "daily_capacity_hours": daily_capacity,
        "estimated_work_days": estimated_work_days,
        "capacity_utilization_pct": min(100, int((total_workload_hours / max(1.0, daily_capacity * 5)) * 100))
    }


def get_daily_work_schedule(days_ahead=7):
    """
    Computes daily production workload vs atelier capacity for the upcoming days.
    Identifies overload days where scheduled production hours or pieces exceed daily capacity.
    """
    now = get_kolkata_now()
    batches = ProductionBatch.query.filter(
        ProductionBatch.status.notin_(["Completed", "Dispatched", "Cancelled"])
    ).all()
    settings = ProductionSetting.get_settings()
    daily_cap_hours = settings.daily_capacity_hours or 32.0
    daily_cap_pieces = settings.daily_capacity_pieces or 16

    schedule_days = []
    for i in range(days_ahead):
        target_d = now.date() + timedelta(days=i)
        day_batches = [b for b in batches if b.target_completion_date == target_d or b.planned_start_date == target_d]
        day_hours = sum(b.estimated_hours for b in day_batches)
        day_pieces = sum(b.remaining_quantity for b in day_batches)
        is_overloaded = (day_hours > daily_cap_hours) or (day_pieces > daily_cap_pieces)
        schedule_days.append({
            "date": target_d,
            "label": "Today" if i == 0 else ("Tomorrow" if i == 1 else target_d.strftime("%a, %d %b")),
            "batches": day_batches,
            "scheduled_pieces": day_pieces,
            "capacity_pieces": daily_cap_pieces,
            "total_hours": round(day_hours, 1),
            "capacity_hours": daily_cap_hours,
            "is_overloaded": is_overloaded,
            "load_percentage": min(300, round((day_pieces / max(1, daily_cap_pieces)) * 100, 1)),
            "utilization_pct": min(100, int((day_hours / max(1.0, daily_cap_hours)) * 100))
        })
    return schedule_days



# ==========================================================
# 5. DISPATCH QUEUE MANAGEMENT
# ==========================================================

def get_dispatch_queue(status_filter="all", search_query=None):
    """
    Retrieves orders ready for packing, packed, awaiting courier dispatch, or recently dispatched.
    """
    query = Order.query.filter(~Order.status.ilike("%cancel%"))

    if status_filter == "ready_for_packing":
        query = query.filter(Order.production_status == "Completed", Order.dispatch_status == "Awaiting Production")
    elif status_filter == "packed":
        query = query.filter(Order.dispatch_status == "Packed")
    elif status_filter == "awaiting_dispatch":
        query = query.filter(Order.dispatch_status == "Ready for Dispatch")
    elif status_filter == "dispatched":
        query = query.filter(or_(Order.dispatch_status == "Dispatched", Order.status.ilike("%ship%")))
    else:
        # All orders in dispatch pipeline
        query = query.filter(
            or_(
                Order.production_status.in_(["Completed", "Quality Check", "Ready for Packing"]),
                Order.dispatch_status.in_(["Packed", "Ready for Dispatch", "Dispatched"]),
                Order.status.ilike("%ship%")
            )
        )

    if search_query:
        sq = f"%{search_query.strip()}%"
        query = query.filter(
            or_(
                Order.id.cast(db.String).ilike(sq),
                Order.customer_name.ilike(sq),
                Order.phone.ilike(sq),
                Order.tracking_id.ilike(sq),
                Order.dispatched_courier.ilike(sq)
            )
        )

    return query.order_by(desc(Order.created_at)).all()


# ==========================================================
# 6. PRODUCT-WISE SALES ANALYTICS & BUSINESS INTELLIGENCE
# ==========================================================

def calculate_product_analytics(date_filter="all", start_date=None, end_date=None, category_filter="all", search_query=None):
    """
    Calculates granular product-level sales analytics with period-over-period comparative growth.
    Distinguishes:
        - Gross Sales
        - Discounts (Product + Coupon deductions)
        - Net Revenue
        - Average Selling Price (ASP)
        - Size-wise demand distributions
        - Demand trend velocity (Rising, Stable, Declining, Insufficient Data)
        - Best sellers, revenue leaders, fast movers, and slow-moving inventory.
    """
    start_dt, end_dt, prior_start_dt, prior_end_dt, period_label = resolve_date_range(date_filter, start_date, end_date)

    all_orders = Order.query.filter(~Order.status.ilike("%cancel%")).all()
    all_products = Product.query.all()
    products_by_id = {p.id: p for p in all_products}
    products_by_name = {p.name.strip().lower(): p for p in all_products}

    # Data structures for current and prior period
    curr_data = defaultdict(lambda: {
        "units": 0,
        "orders_count": 0,
        "gross_sales": 0.0,
        "discounts": 0.0,
        "net_revenue": 0.0,
        "sizes": defaultdict(int),
        "customer_phones": set(),
        "order_ids": [],
    })

    prior_data = defaultdict(lambda: {"units": 0, "net_revenue": 0.0})

    for o in all_orders:
        in_curr = order_placed_in_range(o.created_at, start_dt, end_dt)
        in_prior = order_placed_in_range(o.created_at, prior_start_dt, prior_end_dt) if prior_start_dt else False

        if not (in_curr or in_prior):
            continue

        items = o.get_items()
        order_total_items = sum(int(it.get("quantity") or 1) for it in items) or 1
        order_discount = float(o.discount_amount or 0.0)

        for it in items:
            p_id = it.get("product_id") or o.product_id
            p_name = (it.get("name") or o.product_name or "Garment").strip()
            qty = int(it.get("quantity") or 1)
            item_price = float(it.get("price") or (o.price / max(1, order_total_items)))
            size = (it.get("size") or o.size or "M").strip().upper()

            # Attribute proportional coupon discount to line item
            item_discount = (order_discount / order_total_items) * qty
            if not o.order_items_data and order_discount > 0:
                gross = (item_price + item_discount) * qty
                net = max(0.0, item_price * qty)
            else:
                gross = item_price * qty
                net = max(0.0, gross - item_discount)

            matched = products_by_id.get(p_id) or products_by_name.get(p_name.lower())
            canonical_id = matched.id if matched else (p_id or 0)

            if in_curr:
                entry = curr_data[canonical_id]
                entry["units"] += qty
                entry["orders_count"] += 1
                entry["gross_sales"] += gross
                entry["discounts"] += item_discount
                entry["net_revenue"] += net
                entry["sizes"][size] += qty
                if o.phone:
                    entry["customer_phones"].add(o.phone.strip())
                entry["order_ids"].append(o.id)

            if in_prior:
                prior_entry = prior_data[canonical_id]
                prior_entry["units"] += qty
                prior_entry["net_revenue"] += net

    # Compile analytics per product
    product_analytics_list = []
    category_summary = defaultdict(lambda: {"units": 0, "net_revenue": 0.0, "product_count": 0, "orders_count": 0})
    global_size_demand = defaultdict(int)

    for p in all_products:
        c_data = curr_data.get(p.id, {
            "units": 0, "orders_count": 0, "gross_sales": 0.0, "discounts": 0.0,
            "net_revenue": 0.0, "sizes": {}, "customer_phones": set(), "order_ids": []
        })
        p_data = prior_data.get(p.id, {"units": 0, "net_revenue": 0.0})

        units_curr = c_data["units"]
        units_prior = p_data["units"]
        net_rev = c_data["net_revenue"]
        gross_sales = c_data["gross_sales"]
        asp = round(net_rev / max(1, units_curr), 2) if units_curr > 0 else p.price

        # Demand growth calculation
        if units_prior > 0:
            growth_pct = round(((units_curr - units_prior) / units_prior) * 100, 1)
        elif units_curr > 0:
            growth_pct = 100.0
        else:
            growth_pct = 0.0

        # Demand trend determination
        if units_curr >= 5 and growth_pct >= 20.0:
            trend = "Rising Demand"
            trend_class = "trend-up"
        elif units_curr >= 3 and abs(growth_pct) < 20.0:
            trend = "Stable Demand"
            trend_class = "trend-stable"
        elif units_prior >= 3 and growth_pct <= -20.0:
            trend = "Declining Demand"
            trend_class = "trend-down"
        else:
            trend = "Insufficient Data"
            trend_class = "trend-neutral"

        # Repeat order rate
        unique_customers = len(c_data["customer_phones"])
        repeat_rate = round(((c_data["orders_count"] - unique_customers) / max(1, c_data["orders_count"])) * 100, 1) if c_data["orders_count"] > 1 else 0.0

        item_row = {
            "id": p.id,
            "name": p.name,
            "sku": p.effective_sku,
            "category": p.category or "Collection",
            "image": p.primary_photo_url,
            "price": p.price,
            "cost_price": getattr(p, "cost_price", 0.0) or 0.0,
            "stock": p.stock or 0,
            "units_sold": units_curr,
            "prior_units_sold": units_prior,
            "growth_pct": growth_pct,
            "trend": trend,
            "trend_class": trend_class,
            "orders_count": c_data["orders_count"],
            "gross_sales": round(gross_sales, 2),
            "discounts": round(c_data["discounts"], 2),
            "net_revenue": round(net_rev, 2),
            "asp": asp,
            "size_breakdown": dict(c_data["sizes"]),
            "repeat_rate": repeat_rate,
        }

        # Category rollup (using primary category to avoid double-counting)
        cat_key = p.category or "Other"
        category_summary[cat_key]["units"] += units_curr
        category_summary[cat_key]["net_revenue"] += net_rev
        category_summary[cat_key]["product_count"] += 1
        category_summary[cat_key]["orders_count"] += c_data["orders_count"]

        for sz, sz_qty in c_data["sizes"].items():
            global_size_demand[sz] += sz_qty

        # Filters
        if category_filter and category_filter.lower() != "all":
            if category_filter.lower() not in [c.lower() for c in p.all_categories]:
                continue

        if search_query:
            sq = search_query.lower().strip()
            if sq not in p.name.lower() and sq not in p.effective_sku.lower():
                continue

        product_analytics_list.append(item_row)

    # Global KPI rollups
    total_net_revenue = sum(row["net_revenue"] for row in product_analytics_list)
    total_units_sold = sum(row["units_sold"] for row in product_analytics_list)
    total_gross_sales = sum(row["gross_sales"] for row in product_analytics_list)
    total_discounts = sum(row["discounts"] for row in product_analytics_list)

    # Ranked sections
    bestsellers = sorted([r for r in product_analytics_list if r["units_sold"] > 0], key=lambda x: x["units_sold"], reverse=True)[:10]
    revenue_leaders = sorted([r for r in product_analytics_list if r["net_revenue"] > 0], key=lambda x: x["net_revenue"], reverse=True)[:10]
    fastest_growing = sorted([r for r in product_analytics_list if r["units_sold"] >= 2 and r["growth_pct"] > 0], key=lambda x: x["growth_pct"], reverse=True)[:5]
    declining = sorted([r for r in product_analytics_list if r["growth_pct"] < 0 and r["prior_units_sold"] >= 2], key=lambda x: x["growth_pct"])[:5]
    slow_moving = sorted([r for r in product_analytics_list if r["units_sold"] == 0 and r["stock"] > 5], key=lambda x: x["stock"], reverse=True)[:5]

    # Generate Smart Business Recommendations
    recommendations = generate_business_recommendations(
        bestsellers, revenue_leaders, fastest_growing, declining, slow_moving, global_size_demand, period_label
    )

    return {
        "products": product_analytics_list,
        "period_label": period_label,
        "total_net_revenue": total_net_revenue,
        "total_units_sold": total_units_sold,
        "total_gross_sales": total_gross_sales,
        "total_discounts": total_discounts,
        "bestsellers": bestsellers,
        "revenue_leaders": revenue_leaders,
        "fastest_growing": fastest_growing,
        "declining": declining,
        "slow_moving": slow_moving,
        "category_summary": dict(category_summary),
        "global_size_demand": dict(global_size_demand),
        "recommendations": recommendations,
    }


def generate_business_recommendations(bestsellers, revenue_leaders, fastest_growing, declining, slow_moving, size_demand, period_label):
    """Generates concrete, data-backed operational decision recommendations."""
    recs = []

    # 1. High Demand / Batching Recommendation
    if bestsellers:
        top = bestsellers[0]
        recs.append({
            "category": "Production Planning",
            "title": f"Consolidate Batch Manufacturing for '{top['name']}'",
            "observation": f"'{top['name']}' is your top-ordered garment with {top['units_sold']} pieces sold during {period_label}.",
            "action": f"Schedule a consolidated production run for this design to minimize machine reconfiguration and fabric cutting overhead.",
            "impact": "High Efficiency",
            "confidence": "High (Confirmed Sales Data)"
        })

    # 2. Sizing Pre-Cut Recommendation
    if size_demand:
        sorted_sizes = sorted(size_demand.items(), key=lambda x: x[1], reverse=True)
        top_size, top_size_qty = sorted_sizes[0]
        total_sizes_qty = sum(size_demand.values())
        size_pct = round((top_size_qty / max(1, total_sizes_qty)) * 100, 1)
        if size_pct >= 30:
            recs.append({
                "category": "Material & Cutting",
                "title": f"Pre-cut Size '{top_size}' Linings and Patterns",
                "observation": f"Size '{top_size}' represents {size_pct}% ({top_size_qty} pieces) of all customer size selections.",
                "action": f"Instruct the master cutter to prepare standardized size '{top_size}' foundation fabrics ahead of queue peaks.",
                "impact": "Reduces Lead Time by 18-24%",
                "confidence": "High (Aggregated Sizing Ratio)"
            })

    # 3. Trending Demand Acceleration
    if fastest_growing:
        mover = fastest_growing[0]
        recs.append({
            "category": "Inventory & Merchandising",
            "title": f"Increase Atelier Stock for Trending Design '{mover['name']}'",
            "observation": f"Demand grew by +{mover['growth_pct']}% compared to the prior period ({mover['units_sold']} units vs {mover['prior_units_sold']} prior).",
            "action": f"Ensure sufficient raw silk/georgette fabric is stocked to prevent material starvation bottlenecks.",
            "impact": "Prevents Fulfilment Delays",
            "confidence": "Medium-High (Velocity Spike)"
        })

    # 4. Slow-Moving / Dead Inventory Alert
    if slow_moving:
        stagnant = slow_moving[0]
        recs.append({
            "category": "Commercial Promotion",
            "title": f"Review Merchandising for Stagnant Inventory '{stagnant['name']}'",
            "observation": f"0 pieces sold during {period_label} while holding {stagnant['stock']} ready units in warehouse.",
            "action": f"Consider featuring in a promotional email campaign, discounting, or updating its primary hero image in the visual studio.",
            "impact": "Unlocks Idle Working Capital",
            "confidence": "Medium (Stock Velocity)"
        })

    return recs


# ==========================================================
# 7. INDIVIDUAL GARMENT ANALYTICS ENGINE
# ==========================================================

def get_individual_garment_analytics(product_id, date_filter="all", start_date=None, end_date=None):
    """
    Computes comprehensive individual business performance for a single garment:
    - Lifetime metrics vs period metrics
    - Chronological order log
    - Size demand distribution
    - Growth trends
    - Lifecycle timeline milestones
    """
    product = Product.query.get_or_404(product_id)
    start_dt, end_dt, prior_start_dt, prior_end_dt, period_label = resolve_date_range(date_filter, start_date, end_date)

    all_orders = Order.query.filter(~Order.status.ilike("%cancel%")).order_by(asc(Order.created_at)).all()

    lifetime_units = 0
    lifetime_gross = 0.0
    lifetime_discounts = 0.0
    lifetime_net = 0.0
    lifetime_orders_count = 0

    period_units = 0
    period_gross = 0.0
    period_discounts = 0.0
    period_net = 0.0
    period_orders_count = 0

    prior_units = 0

    size_distribution = defaultdict(int)
    order_history_log = []

    for o in all_orders:
        items = o.get_items()
        matching_items = [it for it in items if (it.get("product_id") == product.id or (it.get("name") or "").strip().lower() == product.name.lower())]

        if not matching_items:
            continue

        order_total_items = sum(int(it.get("quantity") or 1) for it in items) or 1
        order_discount = float(o.discount_amount or 0.0)

        for it in matching_items:
            qty = int(it.get("quantity") or 1)
            price = float(it.get("price") or (o.price / order_total_items))
            sz = (it.get("size") or o.size or "M").strip().upper()
            disc = (order_discount / order_total_items) * qty
            if not o.order_items_data and order_discount > 0:
                gross = (price + disc) * qty
                net = max(0.0, price * qty)
            else:
                gross = price * qty
                net = max(0.0, gross - disc)

            # Lifetime accumulators
            lifetime_units += qty
            lifetime_gross += gross
            lifetime_discounts += disc
            lifetime_net += net
            lifetime_orders_count += 1

            in_curr = order_placed_in_range(o.created_at, start_dt, end_dt)
            in_prior = order_placed_in_range(o.created_at, prior_start_dt, prior_end_dt) if prior_start_dt else False

            if in_curr:
                period_units += qty
                period_gross += gross
                period_discounts += disc
                period_net += net
                period_orders_count += 1
                size_distribution[sz] += qty

                order_history_log.append({
                    "order_id": o.id,
                    "customer_name": o.customer_name,
                    "phone": o.phone,
                    "date": o.created_at.strftime("%d %b %Y, %I:%M %p") if o.created_at else "-",
                    "size": sz,
                    "quantity": qty,
                    "price": gross,
                    "status": o.status,
                    "production_status": getattr(o, "production_status", "Pending") or "Pending",
                    "payment_method": o.payment_method or "UPI / Online"
                })

            if in_prior:
                prior_units += qty

    # Reverse order log to newest first
    order_history_log.reverse()

    # Growth calculation
    if prior_units > 0:
        growth_pct = round(((period_units - prior_units) / prior_units) * 100, 1)
    elif period_units > 0:
        growth_pct = 100.0
    else:
        growth_pct = 0.0

    # Trend
    if period_units >= 5 and growth_pct >= 20.0:
        trend = "Rising Demand"
        trend_class = "trend-up"
    elif period_units >= 3 and abs(growth_pct) < 20.0:
        trend = "Stable Demand"
        trend_class = "trend-stable"
    elif prior_units >= 3 and growth_pct <= -20.0:
        trend = "Declining Demand"
        trend_class = "trend-down"
    else:
        trend = "Insufficient Data"
        trend_class = "trend-neutral"

    # Lifecycle Milestones Timeline
    milestones = []
    if product.created_at:
        milestones.append({
            "date": product.created_at.strftime("%d %b %Y"),
            "event": "Garment Added to Atelier Catalog",
            "type": "create"
        })
    if all_orders and order_history_log:
        first_order = order_history_log[-1]  # Oldest
        milestones.append({
            "date": first_order["date"].split(",")[0],
            "event": f"First Customer Order Received (Order #{first_order['order_id']})",
            "type": "order"
        })
        if lifetime_units >= 10:
            milestones.append({
                "date": "Milestone",
                "event": f"Celebrated 10+ Garments Ordered (Current: {lifetime_units} pcs)",
                "type": "milestone"
            })

    return {
        "product": product,
        "period_label": period_label,
        "lifetime": {
            "units_sold": lifetime_units,
            "gross_sales": round(lifetime_gross, 2),
            "net_revenue": round(lifetime_net, 2),
            "orders_count": lifetime_orders_count,
        },
        "period": {
            "units_sold": period_units,
            "gross_sales": round(period_gross, 2),
            "discounts": round(period_discounts, 2),
            "net_revenue": round(period_net, 2),
            "orders_count": period_orders_count,
        },
        "lifetime_units": lifetime_units,
        "lifetime_gross": round(lifetime_gross, 2),
        "lifetime_net": round(lifetime_net, 2),
        "lifetime_orders_count": lifetime_orders_count,
        "period_units": period_units,
        "period_gross": round(period_gross, 2),
        "period_discounts": round(period_discounts, 2),
        "period_net": round(period_net, 2),
        "period_orders_count": period_orders_count,
        "prior_units": prior_units,
        "growth_pct": growth_pct,
        "trend": trend,
        "trend_class": trend_class,
        "asp": round(period_net / max(1, period_units), 2) if period_units > 0 else product.price,
        "size_distribution": dict(size_distribution),
        "order_history_log": order_history_log,
        "milestones": milestones,
    }
