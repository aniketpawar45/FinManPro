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

    # CRITICAL FIX: Trained AI to handle Monthly/Yearly triggers and auto-fill missing dates
    sys_prompt = (
        "You are a strict financial data extraction AI. Extract the financial entries into JSON with an 'items' array. "
        "Each object must have: amount, item_name, date_str, category, subcategory, remarks, transaction_type, payment_method, frequency, end_date_str. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: Do not invent items.\n"
        "2. GIBBERISH REJECTION: If text is random/invalid, return an EMPTY array: {\"items\": []}.\n"
        "3. TRANSACTION_TYPE: Classify strictly as 'Income' or 'Expense'.\n"
        "4. PAYMENT_METHOD: Deduce if mentioned (e.g., 'Credit Card', 'UPI', 'Cash', 'Bank', 'SBI'). Default to 'Cash/UPI'.\n"
        "5. CATEGORY & SUBCATEGORY: High-Level bucket and logical 1-2 word deduction. NEVER use 'Unknown'.\n"
        "6. RECURRING DATES (CRITICAL): If text contains 'every month', 'monthly', 'everyday', or 'yearly', output ONE item. "
        "Set 'frequency' to 'daily', 'monthly', or 'yearly'. "
        "Set 'date_str' to the start date (if missing, default to Jan 1st of current year, preserving the requested day if mentioned, e.g., '25th' -> '25th Jan'). "
        "Set 'end_date_str' to the end date (if missing or 'till date', default to 'today')."
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
        raise FinanceManagerException("AI Capacity Limit", "Input too massive. Truncated.",
                                      "🛑 ROLLBACK INITIATED: Split into two messages.")

    try:
        batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)
    except Exception:
        raise FinanceManagerException("AI Parsing Fault", "Corrupted JSON.", "🛑 ROLLBACK INITIATED.")

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

        # ================= TEMPORAL EXPANSION ENGINE V2 (Months & Years) =================
        start_date = get_ist_now().date()
        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date: start_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        end_date = start_date
        freq = ext.frequency.lower().strip() if ext.frequency else 'none'

        if freq in ['daily', 'monthly', 'yearly'] and ext.end_date_str:
            p_end = dateparser.parse(ext.end_date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_end: end_date = (IST_TZ.localize(p_end) if p_end.tzinfo is None else p_end).date()

        if end_date < start_date:
            end_date = start_date  # Failsafe against backwards time travel

        current_date = start_date
        loop_cap = 365  # Hard limit to prevent infinite loops
        loops = 0

        while current_date <= end_date and loops < loop_cap:
            results.append((amt, item, current_date, cat, subcat, remarks, t_type, p_method))

            # Smart Calendar Increment
            if freq == 'daily':
                current_date += timedelta(days=1)
            elif freq == 'monthly':
                m = current_date.month % 12 + 1
                y = current_date.year + (current_date.month // 12)
                # Ensure we don't land on Feb 30th
                d = min(current_date.day, calendar.monthrange(y, m)[1])
                current_date = date(y, m, d)
            elif freq == 'yearly':
                current_date = date(current_date.year + 1, current_date.month, current_date.day)
            else:
                break

            loops += 1

    return results