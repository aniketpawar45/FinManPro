import io
import csv
import re
import calendar
import logging
import dateparser
import matplotlib

matplotlib.use('Agg')  # Ensures Vercel doesn't crash trying to open a GUI window
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import date, datetime
from telegram import Bot, InputFile

from core.database import supabase
from core.utils import get_ist_now, FinanceManagerException

logger = logging.getLogger(__name__)


def parse_timeframe(query: str):
    """
    Intelligently deduces if the user meant a Day, a Month, or a Year based on natural language.
    """
    now = get_ist_now().date()
    if not query or query.strip().lower() == "/report":
        return now, now, "Today"

    query = query.replace("/report", "").strip()

    # 1. Check for whole Year (e.g., "2026")
    if re.fullmatch(r'\d{4}', query):
        y = int(query)
        return date(y, 1, 1), date(y, 12, 31), f"Year {y}"

    # Parse the date using dateparser
    parsed = dateparser.parse(query, settings={'TIMEZONE': 'Asia/Kolkata', 'PREFER_DAY_OF_MONTH': 'first'})
    if not parsed:
        raise FinanceManagerException("Report Engine", "I couldn't understand that date format.",
                                      "Try 'July 2026', '2026', or '1st July'.")

    d = parsed.date()

    # 2. Check for Month-only (e.g., "July", "July 2026", "07/2026")
    # If the user didn't mention a specific day number, we assume the whole month.
    day_match = re.search(r'\b(3[01]|[12][0-9]|[1-9])(st|nd|rd|th)?\b', query.lower())
    if not day_match and re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', query.lower()):
        last_day = calendar.monthrange(d.year, d.month)[1]
        return date(d.year, d.month, 1), date(d.year, d.month, last_day), d.strftime("%B %Y")

    if re.fullmatch(r'\d{1,2}[/-]\d{4}', query):
        last_day = calendar.monthrange(d.year, d.month)[1]
        return date(d.year, d.month, 1), date(d.year, d.month, last_day), d.strftime("%B %Y")

    # 3. Default to specific Day
    return d, d, d.strftime("%d %b %Y")


async def generate_visual_dashboard(total_income: float, total_expense: float, expenses_by_cat: dict,
                                    period_name: str) -> io.BytesIO:
    """
    Generates a stunning, multi-colored, high-resolution infographic.
    """
    # Set premium aesthetic
    sns.set_theme(style="whitegrid")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor('#f8f9fa')  # Off-white premium background

    # --- CHART 1: The Expense Donut ---
    if expenses_by_cat:
        labels = list(expenses_by_cat.keys())
        sizes = list(expenses_by_cat.values())
        colors = sns.color_palette("husl", len(labels))  # Vibrant, distinct colors

        ax1.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140,
                wedgeprops=dict(width=0.4, edgecolor='w', linewidth=2), textprops={'fontsize': 11})
        ax1.set_title(f"Where Your Money Went", fontsize=16, fontweight='bold', color='#2c3e50', pad=20)
    else:
        ax1.text(0.5, 0.5, "No Expenses\nLogged", ha='center', va='center', fontsize=16, color='#7f8c8d',
                 fontweight='bold')
        ax1.axis('off')

    # --- CHART 2: Cash Flow Bar Chart ---
    bars = ax2.bar(['Income', 'Expense'], [total_income, total_expense], color=['#2ecc71', '#e74c3c'], width=0.6)
    ax2.set_title("Cash Flow Overview", fontsize=16, fontweight='bold', color='#2c3e50', pad=20)
    ax2.set_ylabel("Amount (₹)", fontsize=12, color='#34495e')
    ax2.grid(axis='y', linestyle='--', alpha=0.7)

    # Add floating text labels on top of bars
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2., height + (max(total_income, total_expense) * 0.02),
                 f'₹{height:,.0f}', ha='center', va='bottom', fontsize=12, fontweight='bold', color='#2c3e50')

    plt.suptitle(f"FinManPro Dashboard | {period_name}", fontsize=20, fontweight='bold', color='#1a252f', y=1.05)
    plt.tight_layout()

    # Save to memory buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    return buf


async def handle_report_command(bot: Bot, chat_id: int, text: str, uid: str):
    await bot.send_chat_action(chat_id=chat_id, action='typing')

    # 1. Parse Date Range
    start_date, end_date, period_name = parse_timeframe(text)

    # 2. Query Database
    res = supabase.table("transactions").select("*").eq("user_id", uid).gte("transaction_date",
                                                                            start_date.isoformat()).lte(
        "transaction_date", end_date.isoformat()).order("transaction_date", desc=True).execute()
    data = res.data

    if not data:
        await bot.send_message(chat_id, f"📭 **No data found for {period_name}.**", parse_mode="Markdown")
        return

    # 3. Crunch the Numbers
    total_income = 0.0
    total_expense = 0.0
    expenses_by_cat = {}

    for row in data:
        amt = float(row.get('amount', 0))
        t_type = row.get('transaction_type', 'Expense').title()
        cat = row.get('category', 'Misc').title()

        if t_type == 'Income':
            total_income += amt
        else:
            total_expense += amt
            expenses_by_cat[cat] = expenses_by_cat.get(cat, 0) + amt

    net_balance = total_income - total_expense

    # 4. Generate Visual Image (High-Def UI)
    await bot.send_chat_action(chat_id=chat_id, action='upload_photo')
    chart_buffer = await generate_visual_dashboard(total_income, total_expense, expenses_by_cat, period_name)

    # 5. Generate User-Understandable CSV Format
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["Date", "Type", "Category", "Subcategory", "Item", "Amount (₹)", "Payment Method", "Remarks"])

    for row in data:
        writer.writerow([
            row.get('transaction_date', ''),
            row.get('transaction_type', 'Expense'),
            row.get('category', 'Misc'),
            row.get('subcategory', 'Unknown'),
            row.get('item_name', ''),
            f"{float(row.get('amount', 0)):.2f}",
            row.get('payment_method', 'Cash/UPI'),
            row.get('remarks', '')
        ])

    csv_bytes = io.BytesIO(csv_buf.getvalue().encode('utf-8'))
    csv_filename = f"FinManPro_Report_{period_name.replace(' ', '_')}.csv"

    # 6. Construct Clear Markdown Text UI
    emoji_balance = "🟢" if net_balance >= 0 else "🔴"

    msg = f"📊 **FINANCIAL REPORT: {period_name.upper()}**\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💵 **Total Income:** ₹{total_income:,.2f}\n"
    msg += f"💸 **Total Expenses:** ₹{total_expense:,.2f}\n"
    msg += f"{emoji_balance} **Net Balance:** ₹{net_balance:,.2f}\n\n"

    if expenses_by_cat:
        msg += f"🏆 **Top Expense Categories:**\n"
        # Sort categories by amount descending and take top 3
        top_cats = sorted(expenses_by_cat.items(), key=lambda x: x[1], reverse=True)[:3]
        medals = ["1️⃣", "2️⃣", "3️⃣"]
        for i, (cat, amt) in enumerate(top_cats):
            msg += f"{medals[i]} {cat}: ₹{amt:,.2f}\n"

    msg += f"\n*Visual dashboard and raw data file attached below! 👇*"

    # 7. Deliver the Payload (Text + Photo + CSV)
    # Send Photo with the summary text as the caption
    await bot.send_photo(chat_id=chat_id, photo=InputFile(chart_buffer, filename="dashboard.png"), caption=msg,
                         parse_mode="Markdown")

    # Send CSV File
    await bot.send_document(chat_id=chat_id, document=InputFile(csv_bytes, filename=csv_filename))