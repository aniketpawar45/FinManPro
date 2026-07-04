import os
import dateparser
from datetime import timedelta
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

    sys_prompt = (
        "You are a strict financial data extraction AI. Extract the financial entries into JSON with an 'items' array. "
        "Each object must have: amount, item_name, date_str, category, subcategory, remarks, transaction_type, payment_method, frequency, end_date_str. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: Do not invent items.\n"
        "2. GIBBERISH REJECTION: If text is random/invalid, return an EMPTY array: {\"items\": []}.\n"
        "3. TRANSACTION_TYPE: Classify strictly as 'Income' or 'Expense'.\n"
        "4. PAYMENT_METHOD: Deduce if mentioned (e.g., 'Credit Card', 'UPI', 'Cash'). Default to 'Cash/UPI'.\n"
        "5. CATEGORY & SUBCATEGORY: High-Level bucket and logical 1-2 word deduction. NEVER use 'Unknown'.\n"
        "6. RECURRING DATES (CRITICAL): If the user says 'everyday from [date1] to [date2]' or 'till date', output ONE single item, but set 'frequency' to 'daily', 'date_str' to the start date, and 'end_date_str' to the end date (use 'today' for till date)."
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

        # ================= TEMPORAL EXPANSION ENGINE =================
        start_date = get_ist_now().date()
        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date: start_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        end_date = start_date
        if ext.frequency and ext.frequency.lower() == 'daily' and ext.end_date_str:
            p_end = dateparser.parse(ext.end_date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_end: end_date = (IST_TZ.localize(p_end) if p_end.tzinfo is None else p_end).date()

        if end_date < start_date:
            end_date = start_date  # Failsafe against backwards time travel

        current_date = start_date
        loop_cap = 365  # Hard limit: Max 1 year of daily entries per command to prevent memory overflow
        loops = 0

        while current_date <= end_date and loops < loop_cap:
            results.append((amt, item, current_date, cat, subcat, remarks, t_type, p_method))
            current_date += timedelta(days=1)
            loops += 1
            if not (ext.frequency and ext.frequency.lower() == 'daily'):
                break  # Break immediately if it's not a recurring 'daily' command

    return results