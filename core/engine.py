import os
import asyncio
import calendar
import dateparser
import re
from datetime import timedelta, date

from groq import AsyncGroq, APIStatusError
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


def preprocess_financial_text(text: str) -> str:
    """Safely handles localized currency math before the LLM sees it, preventing truncation."""
    text = re.sub(r'([\d\.]+)\s*(?:lakhs?|l)\b', lambda m: str(int(round(float(m.group(1)) * 100000))), text,
                  flags=re.IGNORECASE)
    text = re.sub(r'([\d\.]+)\s*(?:k|thousands?)\b', lambda m: str(int(round(float(m.group(1)) * 1000))), text,
                  flags=re.IGNORECASE)
    return text


async def _process_chunk(chunk_text: str, sys_prompt: str) -> list:
    """Helper method to process individual chunks with optimized token limits."""
    try:
        res = await client.chat.completions.create(
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": chunk_text}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=800  # CRITICAL FIX: Drastically lowered to avoid hitting the 6000 TPM Free Tier Limit
        )
    except APIStatusError as e:
        if e.status_code == 429:
            raise FinanceManagerException("AI Rate Limit", "Groq Free Tier TPM Limit reached due to massive list.",
                                          "Please upload half the list now, and the other half in 60 seconds.")
        raise FinanceManagerException("AI Processing", f"API Error: {str(e)}", "Check Groq integration.")
    except Exception as e:
        raise FinanceManagerException("AI Processing", f"Unknown Error: {str(e)}", "Wait 60 seconds and try again.")

    finish_reason = res.choices[0].finish_reason
    if finish_reason in ["length", "max_tokens"]:
        raise FinanceManagerException("AI Capacity", "Chunk truncated.", "List density too high.")

    try:
        batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)
        return batch.items
    except Exception:
        raise FinanceManagerException("AI Parsing Fault", "Corrupted JSON output.", "Please retry.")


async def parse_expense_text(raw_text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")

    current_date_str = get_ist_now().strftime("%B %d, %Y")
    current_year_str = get_ist_now().strftime("%Y")
    clean_text = preprocess_financial_text(raw_text)

    # CRITICAL FIX: Ultra-minified system prompt to save thousands of input tokens per minute
    sys_prompt = (
        f"Extract financial data into JSON: {{\"items\": [{{amount:float, item_name:str, date_str:str, category:str, subcategory:str, remarks:str, transaction_type:\"Income\"|\"Expense\", payment_method:str, frequency:str, adjust_weekends:bool}}]}}. "
        f"TODAY: {current_date_str}, YEAR: {current_year_str}. "
        "RULES: Exact amounts only. Output precise calendar dates. Anchor missing dates to current year."
    )

    lines = [line.strip() for line in clean_text.split('\n') if line.strip() and re.search(r'\d', line)]

    # Bundle into chunks of 25 items to minimize parallel thread count
    CHUNK_SIZE = 25
    chunks = []
    for i in range(0, len(lines), CHUNK_SIZE):
        chunks.append("\n".join(lines[i:i + CHUNK_SIZE]))

    if not chunks:
        chunks = [clean_text]

    # Execute all chunks against the Groq API concurrently
    tasks = [_process_chunk(chunk, sys_prompt) for chunk in chunks]
    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_extracted_items = []
    for res in chunk_results:
        if isinstance(res, Exception):
            raise res  # Stop the entire transaction and alert user if rate limit is hit
        all_extracted_items.extend(res)

    results = []

    for ext in all_extracted_items:
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
        freq = ext.frequency.lower().strip() if ext.frequency else 'none'

        if ext.date_str:
            p_date = dateparser.parse(ext.date_str,
                                      settings={'TIMEZONE': 'Asia/Kolkata', 'RELATIVE_BASE': get_ist_now()})
            if p_date:
                start_date = (IST_TZ.localize(p_date) if p_date.tzinfo is None else p_date).date()
                if start_date.year < today_date.year:
                    try:
                        start_date = start_date.replace(year=today_date.year)
                    except ValueError:
                        start_date = start_date.replace(year=today_date.year, day=28)
                if start_date > today_date:
                    if freq in ['monthly', 'quarterly', 'half-yearly', 'yearly']:
                        try:
                            start_date = start_date.replace(month=1)
                        except ValueError:
                            start_date = start_date.replace(month=1, day=28)
                    elif freq in ['weekly', 'biweekly']:
                        while start_date.month > 1 and start_date.year == today_date.year:
                            start_date -= timedelta(weeks=1)

        end_date = start_date
        valid_frequencies = ['daily', 'weekly', 'biweekly', 'monthly', 'quarterly', 'half-yearly', 'yearly']

        if freq in valid_frequencies:
            if ext.end_date_str:
                p_end = dateparser.parse(ext.end_date_str,
                                         settings={'TIMEZONE': 'Asia/Kolkata', 'RELATIVE_BASE': get_ist_now()})
                if p_end:
                    end_date = (IST_TZ.localize(p_end) if p_end.tzinfo is None else p_end).date()
                    if end_date.year < today_date.year:
                        try:
                            end_date = end_date.replace(year=today_date.year)
                        except ValueError:
                            pass
            else:
                end_date = today_date
            if end_date > today_date:
                end_date = today_date

        if end_date < start_date: end_date = start_date

        current_date = start_date
        loop_cap = 1000
        loops = 0

        while current_date <= end_date and loops < loop_cap:
            actual_date = current_date
            if ext.adjust_weekends:
                if actual_date.weekday() == 5:
                    actual_date -= timedelta(days=1)
                elif actual_date.weekday() == 6:
                    actual_date -= timedelta(days=2)

            results.append((amt, item, actual_date, cat, subcat, remarks, t_type, p_method))

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