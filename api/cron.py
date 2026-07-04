import os
import io
import csv
from fastapi import APIRouter, Header, HTTPException
from core.database import supabase
from core.utils import get_ist_now
from core.analytics import get_report_data, parse_date_range
from core.emailer import send_report_email

router = APIRouter()
CRON_SECRET = os.environ.get("CRON_SECRET")


@router.get("/cron")
async def process_scheduled_reports(authorization: str = Header(None)):
    if CRON_SECRET and authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized Cron Execution")

    ist_now = get_ist_now()
    try:
        schedules = supabase.table("report_schedules").select("*").eq("scheduled_hour", ist_now.hour).execute().data
    except:
        raise HTTPException(status_code=500, detail="DB error")

    dispatched = 0
    for sched in schedules:
        freq = sched['frequency']
        if freq == 'weekly' and ist_now.weekday() != 0: continue
        if freq == 'monthly' and ist_now.day != 1: continue

        start, end, label = parse_date_range(
            {'daily': 'yesterday', 'weekly': 'last week', 'monthly': 'last month'}.get(freq, 'yesterday'))
        data = get_report_data(sched['telegram_id'], start, end)
        if not data: continue

        mem_file = io.StringIO()
        writer = csv.writer(mem_file)
        writer.writerow(["Date", "Item Name", "Category", "Subcategory", "Amount (INR)", "Original Remarks"])

        total = 0.0
        for item in data:
            total += float(item['amount'])
            cat = item.get('category', 'Other')
            subcat = item.get('subcategory', 'General')
            writer.writerow(
                [item['transaction_date'], item['item_name'], cat, subcat, item['amount'], item.get('remarks', '')])

        mem_file.seek(0)
        csv_bytes = mem_file.getvalue().encode('utf-8')
        send_report_email([e.strip() for e in sched['emails'].split(",")], f"📊 Your {freq.capitalize()} Report",
                          f"Total Spent: ₹{total:,.2f}", f"Report_{label}.csv", csv_bytes)

        supabase.table("report_schedules").update({"last_sent_at": ist_now.isoformat()}).eq("id", sched['id']).execute()
        dispatched += 1

    return {"status": "success", "dispatched": dispatched}