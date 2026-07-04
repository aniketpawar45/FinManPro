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

    # ADVANCED FEW-SHOT: Forces High-Level Categories, specific Subcategories, and Bulk List Processing
    sys_prompt = (
        "You are an elite, lightning-fast financial extraction AI. Extract expenses into JSON with an 'items' array containing: "
        "amount (number), item_name (string), date_str (string, optional), category (string), subcategory (string). "
        "RULES:\n"
        "1. Extract exact item name. If ONLY a number is provided without a name, leave item_name blank.\n"
        "2. 'category' MUST be a high-level bucket (e.g., Food, Transport, Utilities, Shopping, Health, Housing, Entertainment, Other).\n"
        "3. 'subcategory' is a specific 1-2 word description (e.g., Groceries, Cab, Electricity, Movie).\n"
        "EXAMPLES:\n"
        "User: 'Milk 40, Cab 500, 1500'\n"
        "Output: {\"items\": [\n"
        "  {\"amount\": 40, \"item_name\": \"Milk\", \"category\": \"Food\", \"subcategory\": \"Groceries\"},\n"
        "  {\"amount\": 500, \"item_name\": \"Cab\", \"category\": \"Transport\", \"subcategory\": \"Taxi\"},\n"
        "  {\"amount\": 1500, \"item_name\": \"\", \"category\": \"Other\", \"subcategory\": \"Unknown\"}\n"
        "]}"
    )

    res = await client.chat.completions.create(
        messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
        model="llama-3.1-8b-instant",
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

        cat = ext.category.title().strip() if ext.category else "Other"
        subcat = ext.subcategory.title().strip() if ext.subcategory else "General"

        item_date = get_ist_now().date()
        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date:
                item_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        results.append((amt, item, item_date, cat, subcat))

    return results