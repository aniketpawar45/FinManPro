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
        "Extract expenses into JSON with an 'items' array containing: "
        "amount (number), item_name (string), date_str (string, optional), category_name (string). "
        "For category_name, dynamically generate the most logical, concise 1-to-2 word category "
        "(e.g., Electronics, Dining, Travel, Healthcare, Subscriptions). Be highly accurate."
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
        item = ext.item_name.title() if ext.item_name else "Unknown Item"
        ai_cat = ext.category_name.title() if ext.category_name else "Other"

        # Base date is strictly today's date in IST
        item_date = get_ist_now().date()

        if ext.date_str:
            p_date = dateparser.parse(ext.date_str, settings={'TIMEZONE': 'Asia/Kolkata'})
            if p_date:
                # Localize and extract just the date component
                item_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()

        results.append((amt, item, item_date, ai_cat))

    return results