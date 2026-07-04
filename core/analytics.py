import datetime
import calendar
import dateparser
from core.database import supabase
from core.utils import get_ist_now, IST_TZ


def parse_date_range(query: str) -> tuple:
    now = get_ist_now()
    query = query.lower().strip()

    if query in ["", "today", "month"]:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = now.replace(day=last_day, hour=23, minute=59, second=59)
        return start, end, "This Month"

    parsed = dateparser.parse(query, settings={'RELATIVE_BASE': now, 'TIMEZONE': 'Asia/Kolkata',
                                               'RETURN_AS_TIMEZONE_AWARE': True})
    if not parsed: parsed = now
    if parsed.tzinfo is None: parsed = IST_TZ.localize(parsed)

    start = parsed.replace(hour=0, minute=0, second=0)
    end = parsed.replace(hour=23, minute=59, second=59)
    return start, end, start.strftime('%d %b %Y')


def get_report_data(user_id: str, start: datetime.datetime, end: datetime.datetime) -> list:
    start_date = start.date().isoformat()
    end_date = end.date().isoformat()

    res = supabase.table("transactions") \
        .select("amount, item_name, transaction_date, category, subcategory, remarks") \
        .eq("user_id", user_id) \
        .gte("transaction_date", start_date) \
        .lte("transaction_date", end_date) \
        .order("transaction_date", desc=True) \
        .execute()
    return res.data


def get_statistics_data(user_id: str, start: datetime.datetime, end: datetime.datetime):
    data = get_report_data(user_id, start, end)
    if not data: return None

    cat_map = {}
    total = 0
    for item in data:
        amt = float(item['amount'])
        cat = item.get('category', 'Other')
        cat_map[cat] = cat_map.get(cat, 0) + amt
        total += amt

    return {"total": total, "categories": cat_map}