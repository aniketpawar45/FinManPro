import datetime
import calendar
import dateparser
import re
from core.database import supabase
from core.utils import get_ist_now, IST_TZ


def parse_date_range(query: str) -> tuple:
    now = get_ist_now()
    q = query.lower().strip() if query else ""

    if q in ["today", "0"]:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "Today"
    elif q == "this week":
        start = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + datetime.timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "This Week"
    elif q in ["this month", "month", ""]:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
        return start, end, "This Month"
    elif q == "this year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        return start, end, str(now.year)

    parsed = dateparser.parse(q, settings={'RELATIVE_BASE': now, 'TIMEZONE': 'Asia/Kolkata',
                                           'RETURN_AS_TIMEZONE_AWARE': True})
    if not parsed: parsed = now
    if parsed.tzinfo is None: parsed = IST_TZ.localize(parsed)

    if re.fullmatch(r'\d{4}', q):
        start = parsed.replace(month=1, day=1, hour=0, minute=0, second=0)
        end = parsed.replace(month=12, day=31, hour=23, minute=59, second=59)
        return start, end, str(parsed.year)

    start = parsed.replace(hour=0, minute=0, second=0)
    end = parsed.replace(hour=23, minute=59, second=59)
    return start, end, parsed.strftime('%d %b %Y')


def get_report_data(user_id: str, start: datetime.datetime, end: datetime.datetime) -> list:
    res = supabase.table("transactions").select("*").eq("user_id", user_id) \
        .gte("transaction_date", start.date().isoformat()).lte("transaction_date", end.date().isoformat()) \
        .order("transaction_date", desc=True).execute()
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