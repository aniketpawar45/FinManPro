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

    # CRITICAL FIXES: Added Indian number formats, isolated the weekend flag, and expanded frequencies.
    sys_prompt = (
        f"You are a strict financial extraction AI. TODAY'S DATE IS {current_date_str}. "
        "Extract the financial entries into JSON with an 'items' array. "
        "Each object must have: amount, item_name, date_str, category, subcategory, remarks, transaction_type, payment_method, frequency, end_date_str, adjust_weekends. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: Do not invent items.\n"
        "2. AMOUNT PARSING: '1.5l' or '1.5 lakh' = 150000. 'l' or 'lakh' = 100000. 'k' = 1000.\n"
        "3. TRANSACTION_TYPE: Classify strictly as 'Income' or 'Expense'.\n"
        "4. PAYMENT_METHOD: Deduce if mentioned. Default to 'Cash/UPI'.\n"
        "5. RECURRING DATES: If recurring, output EXACTLY ONE item. Set 'frequency' strictly to: 'daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'half-yearly', or 'yearly'. "
        f"Set 'date_str' to start date (default to Jan 1st of {current_year_str} if only a day is given).\n"
        "6. ADJUST WEEKENDS: Set 'adjust_weekends' to true ONLY for the specific individual item where the user requested it. Do NOT apply it globally to other items."
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
        raise FinanceManagerException("AI Capacity Limit", "Input too massive. Truncated.", "🛑 ROLLBACK INITIATED.")

    try:
        batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)
    except Exception:
        raise FinanceManagerException("AI Parsing Fault", "Corrupted JSON.", "🛑 ROLLBACK INITIATED.")

    results = []

    # Helper for complex month math
    def add_months(curr_date, months_to_add):
        m = (curr_date.month + months_to_add - 1) % 12 + 1
        y = curr_date.year + ((curr_date.month + months_to_add - 1) // 12)
        d = min(curr_date.day, calendar.monthrange(y, m)[1])
        return date(y, m, d)

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

        valid_freqs = ['daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'half-yearly', 'yearly']

        if freq in valid_freqs:
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
            if ext.adjust_weekends:
                if actual_date.weekday() == 5:  # Saturday
                    actual_date -= timedelta(days=1)
                elif actual_date.weekday() == 6:  # Sunday
                    actual_date -= timedelta(days=2)

            results.append((amt, item, actual_date, cat, subcat, remarks, t_type, p_method))

            # ================= EXPANDED FREQUENCY ENGINE =================
            if freq == 'daily':
                current_date += timedelta(days=1)
            elif freq == 'weekly':
                current_date += timedelta(days=7)
            elif freq == 'biweekly':
                current_date += timedelta(days=14)
            elif freq == 'monthly':
                current_date = add_months(current_date, 1)
            elif freq == 'quarterly':
                current_date = add_months(current_date, 3)
            elif freq == 'half-yearly':
                current_date = add_months(current_date, 6)
            elif freq == 'yearly':
                current_date = add_months(current_date, 12)
            else:
                break

            loops += 1

    return results