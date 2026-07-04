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
        raise FinanceManagerException("Voice AI", f"Transcription Failed: {str(e)}",
                                      "Please type your expense instead.")


async def parse_expense_text(text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")

    # CRITICAL FIX: Hardened Anti-Hallucination rules and squished text parsing.
    sys_prompt = (
        "You are a strict financial data extraction AI. Extract ONLY the expenses explicitly mentioned in the user text into JSON with an 'items' array. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: You MUST NOT invent, add, or assume any items that are not explicitly in the user's text. If the user writes 1 item, return exactly 1 item.\n"
        "2. INTELLIGENT PARSING: Safely separate squished text (e.g., 'Milkyesterday34' means item_name: 'Milk', date_str: 'yesterday', amount: 34).\n"
        "3. 'item_name' MUST be the pure item name ONLY.\n"
        "4. 'remarks' MUST contain the original text string.\n"
        "5. 'category' MUST be a High-Level bucket ONLY: Food, Household, Transport, Health, Housing, Entertainment, Shopping, Utilities, Misc.\n"
        "6. 'subcategory' is a specific 1-2 word description."
    )

    try:
        res = await client.chat.completions.create(
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.0,  # Zero temperature ensures it stays highly deterministic and literal
            max_tokens=2500
        )
    except Exception as e:
        raise FinanceManagerException("AI Processing", f"Groq API Error: {str(e)}", "Wait 60 seconds and try again.")

    batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)
    results = []

    for ext in batch.items:
        amt = ext.amount if ext.amount else 0.0

        item = str(ext.item_name).title().strip() if ext.item_name else "Unknown Item"
        if item == str(amt) or item == str(int(amt)) or item == "" or item.lower() == "unknown item":
            item = "Unknown Item"

        cat = ext.category.title().strip() if ext.category else "Misc"
        subcat = ext.subcategory.title().strip() if ext.subcategory else "Unknown"
        remarks = ext.remarks.strip() if ext.remarks else item

        item_date = get_ist_now().date()
        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date:
                item_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        results.append((amt, item, item_date, cat, subcat, remarks))

    return results