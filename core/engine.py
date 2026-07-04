import os
import dateparser
from groq import AsyncGroq
from core.models import ExpenseBatch
from core.utils import get_ist_now, FinanceManagerException, IST_TZ

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


async def transcribe_audio(audio_bytes: bytes) -> str:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")
    res = await client.audio.transcriptions.create(file=("voice.ogg", audio_bytes, "audio/ogg"),
                                                   model="whisper-large-v3")
    return res.text.strip()


async def parse_expense_text(text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")

    sys_prompt = (
        "You are an elite financial AI. Extract ALL expenses from the text into JSON with an 'items' array. "
        "Each object must have: amount (number), item_name (string), date_str (string, optional), category (string), subcategory (string), remarks (string). "
        "RULES:\n"
        "1. 'item_name' MUST be the pure item name ONLY (e.g., 'Toor Dal', 'Rice'). DO NOT include quantities or weights here.\n"
        "2. 'remarks' MUST contain the full original string including quantities (e.g., 'Toor Dal - 2 kg').\n"
        "3. 'category' MUST be a High-Level bucket ONLY: Food, Household, Transport, Health, Housing, Entertainment, Shopping, Utilities, Misc.\n"
        "4. 'subcategory' is a specific 1-2 word description (e.g., Groceries, Pulses, Meat, Cleaning).\n"
        "EXAMPLES:\n"
        "User: 'Toor Dal - 2 kg - 360'\n"
        "Output: {\"items\": [{\"amount\": 360, \"item_name\": \"Toor Dal\", \"category\": \"Food\", \"subcategory\": \"Pulses\", \"remarks\": \"Toor Dal - 2 kg - 360\"}]}"
    )

    res = await client.chat.completions.create(
        messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"},
        temperature=0.0
    )

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