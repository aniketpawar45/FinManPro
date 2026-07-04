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
    """Helper to transcribe audio using Whisper."""
    if not client:
        raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")
    try:
        res = await client.audio.transcriptions.create(
            file=("voice.ogg", audio_bytes, "audio/ogg"),
            model="whisper-large-v3"
        )
        return res.text.strip()
    except Exception as e:
        raise FinanceManagerException("Voice AI", f"Transcription Failed: {str(e)}", "Please type your entry instead.")
async def parse_expense_text(text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")

    current_date_str = get_ist_now().strftime("%B %d, %Y")

    # AI Prompt: Strict Indian Numbering (Lakhs) and explicit shift mandate
    sys_prompt = (
        f"You are a strict financial extraction AI. TODAY IS {current_date_str}. "
        "1. AMOUNT: 'l' or 'lakh' = 100,000. '1.5l' = 150000. '2.51l' = 251000. "
        "2. DATES: Populate 'date_str' with the full calculated date (e.g., 'Jan 25, 2026'). "
        "3. WEEKENDS: Set 'adjust_weekends' to true if the item involves a 'business day' shift."
    )

    res = await client.chat.completions.create(
        messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
        model="llama-3.1-8b-instant",
        response_format={"type": "json_object"},
        temperature=0.0
    )
    batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)

    results = []
    today = get_ist_now().date()

    for ext in batch.items:
        # Pre-process dates
        start = dateparser.parse(ext.date_str).date() if ext.date_str else today
        freq = ext.frequency.lower()
        end = min(dateparser.parse(ext.end_date_str).date(), today) if ext.end_date_str else today

        curr = start
        while curr <= end:
            # SHIFT WEEKENDS FIRST (The Fix)
            actual = curr
            if ext.adjust_weekends:
                while actual.weekday() >= 5:  # If Sat(5) or Sun(6)
                    actual -= timedelta(days=1)

            results.append(
                (ext.amount, ext.item_name, actual, ext.category, ext.subcategory, ext.remarks, ext.transaction_type,
                 ext.payment_method))

            # Frequency logic
            if freq == 'daily':
                curr += timedelta(days=1)
            elif freq == 'monthly':
                curr = (curr.replace(day=1) + timedelta(days=32)).replace(day=curr.day)
            elif freq == 'yearly':
                curr = curr.replace(year=curr.year + 1)
            else:
                break

    return results