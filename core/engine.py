import os
import calendar
import dateparser
from datetime import timedelta, date
from groq import AsyncGroq
from core.models import ExpenseBatch
from core.utils import get_ist_now, FinanceManagerException, IST_TZ

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


async def transcribe_audio(audio_bytes: bytes) -> str:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")
    try:
        res = await client.audio.transcriptions.create(file=("voice.ogg", audio_bytes, "audio/ogg"),
                                                       model="whisper-large-v3")
        return res.text.strip()
    except Exception as e:
        raise FinanceManagerException("Voice AI", f"Transcription Failed: {str(e)}", "Please type your entry instead.")


async def parse_expense_text(text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")
    current_date_str = get_ist_now().strftime("%B %d, %Y")
    current_year_str = get_ist_now().strftime("%Y")

    # CRITICAL FIX: Hardened AI Prompt for Currency Math, Historical Anchoring, and Calendar Math Sandboxing.
    sys_prompt = (
        f"You are a strict financial extraction AI. TODAY'S DATE IS {current_date_str}. "
        "Extract the financial entries into JSON with an 'items' array. "
        "Each object must have: amount, item_name, date_str, category, subcategory, remarks, transaction_type, payment_method, frequency, end_date_str, adjust_weekends. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: Do not invent items.\n"
        "2. GIBBERISH REJECTION: If text is random/invalid, return an EMPTY array: {\"items\": []}.\n"
        "3. TRANSACTION_TYPE: Classify strictly as 'Income' or 'Expense'.\n"
        "4. PAYMENT_METHOD: Deduce if mentioned (e.g., 'Credit Card', 'UPI', 'SBI', 'Bank'). Default to 'Cash/UPI'.\n"
        "5. CATEGORY & SUBCATEGORY: Logical 1-2 word deduction. NEVER use 'Unknown'.\n"
        f"6. RECURRING DATES (CRITICAL): If recurring, you MUST output EXACTLY ONE item. "
        f"Set 'frequency' (Choose ONLY from: 'daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'half-yearly', 'yearly', 'none').\n"
        "7. ADJUST WEEKENDS: Set 'adjust_weekends' to true ONLY if user mentions moving dates for holidays or business days.\n"
        "8. CURRENCY FORMATS (STRICT): 'l' or 'lakh' means EXACTLY multiply by 100,000 (e.g. '1.5l' = 150000, '2.51l' = 251000). Leave standard numbers untouched (e.g. '200' = 200).\n"
        "9. HISTORICAL START DATES: If the user says 'Every month on 25th' without a start month, NEVER use a future date. You MUST set 'date_str' to the FIRST occurrence in the current year (e.g. Jan 25, {current_year_str}).\n"
        "10. NO CALENDAR MATH: Do NOT attempt to calculate 'last business day'. Set the date to the EXACT calendar end (e.g. Feb 28, Jun 30) and set adjust_weekends=true. The backend will shift it."
    )

    try:
        res = await client.chat.completions.create(
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4000
        )
    except Exception as e:
        raise FinanceManagerException("AI Processing", f"Groq API Error: {str(e)}", "Wait 60 seconds and try again.")

    finish_reason = res.choices[0].finish_reason
    if finish_reason in ["length", "max_tokens"]:
        raise FinanceManagerException("AI Capacity Limit", "Input too massive. Truncated.", "  ROLLBACK INITIATED.")

    try:
        batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)
    except Exception:
        raise FinanceManagerException("AI Parsing Fault", "Corrupted JSON.", "  ROLLBACK INITIATED.")

    results = []
    for ext in batch.items:
        amt = ext.amount if ext.amount else 0.0
        item = str(ext.item_name).title().strip() if ext.item_name else "Unknown Item"
        if item in [str(amt), str(int(amt)), "", "Unknown Item"]: item = "Unknown Item"
        cat = ext.category.title().strip() if ext.category else "Misc"
        subcat = ext.subcategory.title().strip() if ext.subcategory else "General"
        if subcat.lower() == "unknown": subcat = "General"
        remarks = ext.remarks.strip() if ext.remarks else item
        t_type = ext.transaction_type.title().strip()
        p_method = ext.payment_method.title().strip()

        today_date = get_ist_now().date()
        start_date = today_date

        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date: start_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        end_date = start_date
        freq = ext.frequency.lower().strip() if ext.frequency else 'none'

        valid_frequencies = ['daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'half-yearly', 'yearly']

        if freq in valid_frequencies:
            if ext.end_date_str:
                p_end = dateparser.parse(ext.end_date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
                if p_end: end_date = (IST_TZ.localize(p_end) if p_end.tzinfo is None else p_end).date()
            else:
                end_date = today_date

            if end_date > today_date:
                end_date = today_date

        if end_date < start_date: end_date = start_date

        current_date = start_date
        loop_cap = 365
        loops = 0

        while current_date <= end_date and loops < loop_cap:
            actual_date = current_date

            # Business day adjust logic
            if ext.adjust_weekends:
                if actual_date.weekday() == 5:  # Saturday -> Friday
                    actual_date -= timedelta(days=1)
                elif actual_date.weekday() == 6:  # Sunday -> Friday
                    actual_date -= timedelta(days=2)

            results.append((amt, item, actual_date, cat, subcat, remarks, t_type, p_method))

            # Engine Update: Complex Date-Math
            if freq == 'daily':
                current_date += timedelta(days=1)
            elif freq == 'weekly':
                current_date += timedelta(weeks=1)
            elif freq == 'biweekly':
                current_date += timedelta(weeks=2)
            elif freq == 'monthly':
                m = current_date.month % 12 + 1
                y = current_date.year + (current_date.month // 12)
                d = min(current_date.day, calendar.monthrange(y, m)[1])
                current_date = date(y, m, d)
            elif freq == 'quarterly':
                m = (current_date.month + 2) % 12 + 1
                y = current_date.year + ((current_date.month + 2) // 12)
                d = min(current_date.day, calendar.monthrange(y, m)[1])
                current_date = date(y, m, d)
            elif freq == 'half-yearly':
                m = (current_date.month + 5) % 12 + 1
                y = current_date.year + ((current_date.month + 5) // 12)
                d = min(current_date.day, calendar.monthrange(y, m)[1])
                current_date = date(y, m, d)
            elif freq == 'yearly':
                try:
                    current_date = date(current_date.year + 1, current_date.month, current_date.day)
                except ValueError:
                    current_date = date(current_date.year + 1, current_date.month, current_date.day - 1)
            else:
                break

            loops += 1

    return results