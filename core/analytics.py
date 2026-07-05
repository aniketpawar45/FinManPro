import datetime
import calendar
import dateparser
import re
from core.database import supabase
from core.utils import get_ist_now, IST_TZ


def parse_date_range(query: str) -> tuple:
    now = get_ist_now()
    q = query.lower().strip()

    if q in ["today", "0"]:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "Today"
    elif q in ["yesterday", "-1"]:
        start = (now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "Yesterday"
    elif q == "this week":
        start = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + datetime.timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "This Week"
    elif q == "last week":
        start = (now - datetime.timedelta(days=now.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + datetime.timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "Last Week"
    elif q in ["this month", "month", ""]:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "This Month"
    elif q == "last month":
        first_day_this_month = now.replace(day=1)
        last_day_last_month = first_day_this_month - datetime.timedelta(days=1)
        start = last_day_last_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = last_day_last_month.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "Last Month"
    elif q == "this year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        return start, end, str(now.year)

    # Fallback to dateparser for specific months/years/dates
    parsed = dateparser.parse(q, settings={'RELATIVE_BASE': now, 'TIMEZONE': 'Asia/Kolkata',
                                           'RETURN_AS_TIMEZONE_AWARE': True})
    if not parsed:
        parsed = now
    if parsed.tzinfo is None:
        parsed = IST_TZ.localize(parsed)

    if re.fullmatch(r'\d{4}', q):
        start = parsed.replace(month=1, day=1, hour=0, minute=0, second=0)
        end = parsed.replace(month=12, day=31, hour=23, minute=59, second=59)
        return start, end, str(parsed.year)

    day_match = re.search(r'\b(3[01]|[12][0-9]|[1-9])(st|nd|rd|th)?\b', q)
    if not day_match and re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', q):
        start = parsed.replace(day=1, hour=0, minute=0, second=0)
        last_day = calendar.monthrange(parsed.year, parsed.month)[1]
        end = parsed.replace(day=last_day, hour=23, minute=59, second=59)
        return start, end, parsed.strftime('%B %Y')

    start = parsed.replace(hour=0, minute=0, second=0)
    end = parsed.replace(hour=23, minute=59, second=59)
    return start, end, parsed.strftime('%d %b %Y')


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