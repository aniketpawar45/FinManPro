import os
import dateparser
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
        "Each object must have: amount, item_name, date_str, category, subcategory, remarks, transaction_type, payment_method. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: Do not invent items.\n"
        "2. GIBBERISH REJECTION: If text is random/invalid, return an EMPTY array: {\"items\": []}.\n"
        "3. TRANSACTION_TYPE: Classify as 'Income' (e.g., Salary, refund, received money) or 'Expense' (e.g., bought, paid, standard items).\n"
        "4. PAYMENT_METHOD: Deduce if mentioned (e.g., 'Credit Card', 'Debit Card', 'UPI', 'Cash'). Default to 'Cash/UPI' if unknown.\n"
        "5. 'item_name' is the pure name. 'remarks' contains the full original string.\n"
        "6. Categories must be High-Level (Food, Transport, Utilities, Income, Shopping, etc.)."
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
        subcat = ext.subcategory.title().strip() if ext.subcategory else "Unknown"
        remarks = ext.remarks.strip() if ext.remarks else item

        t_type = ext.transaction_type.title().strip()
        p_method = ext.payment_method.title().strip()

        item_date = get_ist_now().date()
        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date: item_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        # Passing 8 variables now to match the UI updates needed later
        results.append((amt, item, item_date, cat, subcat, remarks, t_type, p_method))

    return results