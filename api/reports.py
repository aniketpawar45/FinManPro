import io
import csv
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from core.analytics import parse_date_range, get_report_data
from core.utils import IST_TZ


async def handle_report_command(bot: Bot, chat_id: int, command: str, uid: str):
    query = command.split(" ", 1)[1] if " " in command else "today"
    start, end, label = parse_date_range(query)
    data = get_report_data(uid, start, end)

    if not data: return await bot.send_message(chat_id, f"⚠️ No expenses found for *{label}*.", parse_mode="Markdown")

    total = sum(float(item['amount']) for item in data)
    msg = f"📄 *Financial Report: {label}*\n\n`{'Item':<13} | {'Amt':<6} | {'Cat'}`\n" + "-" * 30 + "\n"

    for item in data:
        amt, desc, cat = float(item['amount']), item['description'][:13], item['categories'][
            'category_name'] if item.get('categories') else "Other"
        msg += f"`{desc:<13} | {amt:<6.0f} |` {'🚨' if amt > (total * 0.3) else '  '} {cat}\n"

    msg += "-" * 30 + f"\n💰 *Total Spent: ₹{total:,.2f}*\n\n"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📥 Download CSV", callback_data=f"csv:{start.timestamp()}:{end.timestamp()}")]])
    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown", reply_markup=kb)


async def handle_csv_export(bot: Bot, chat_id: int, uid: str, start_ts: float, end_ts: float):
    start, end = datetime.fromtimestamp(start_ts, tz=IST_TZ), datetime.fromtimestamp(end_ts, tz=IST_TZ)
    data = get_report_data(uid, start, end)

    if not data: return await bot.send_message(chat_id, "⚠️ No data available.")

    mem_file = io.StringIO()
    writer = csv.writer(mem_file)
    writer.writerow(["Date", "Item Description", "Category", "Amount (INR)"])

    # Update the loop inside handle_csv_export
    for item in data:
        cat = item['categories']['category_name'] if item.get('categories') else "Other"
        # Since it's already returned as "YYYY-MM-DD" from Supabase, we can print it directly
        writer.writerow([item['transaction_date'], item['description'], cat, item['amount']])

    mem_file.seek(0)
    byte_stream = io.BytesIO(mem_file.getvalue().encode('utf-8'))
    byte_stream.name = f"Expense_Report_{start.strftime('%Y%m%d')}.csv"

    await bot.send_document(chat_id=chat_id, document=byte_stream, caption="📊 Your requested report.")