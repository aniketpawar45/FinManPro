import os
import asyncio
import calendar
import dateparser
import re
import json
from datetime import timedelta, date

from groq import AsyncGroq, APIStatusError
from core.models import ExpenseBatch
from core.utils import get_ist_now, FinanceManagerException, IST_TZ

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Throttle concurrency to prevent overwhelming the connection pool
api_semaphore = asyncio.Semaphore(4)


async def transcribe_audio(audio_bytes: bytes) -> str:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")
    try:
        res = await client.audio.transcriptions.create(file=("voice.ogg", audio_bytes, "audio/ogg"),
                                                       model="whisper-large-v3")
        return res.text.strip()
    except Exception as e:
        raise FinanceManagerException("Voice AI", f"Transcription Failed: {str(e)}", "Please type your entry instead.")


def preprocess_financial_text(text: str) -> str:
    text = re.sub(r'([\d\.]+)\s*(?:lakhs?|l)\b', lambda m: str(int(round(float(m.group(1)) * 100000))), text,
                  flags=re.IGNORECASE)
    text = re.sub(r'([\d\.]+)\s*(?:k|thousands?)\b', lambda m: str(int(round(float(m.group(1)) * 1000))), text,
                  flags=re.IGNORECASE)
    return text


async def _process_chunk(chunk_text: str, sys_prompt: str) -> list:
    async with api_semaphore:
        try:
            res = await client.chat.completions.create(
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": chunk_text}],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=500  # Tuned strictly to prevent JSON 400 errors while avoiding 429 TPM limits
            )
        except APIStatusError as e:
            if e.status_code == 429:
                raise FinanceManagerException("AI Rate Limit", "API Free Tier Limit hit.", "Please wait 60 seconds.")
            raise FinanceManagerException("AI Processing", f"API Error: {str(e)}", "Check Groq integration.")
        except Exception as e:
            raise FinanceManagerException("AI Processing", f"Unknown Error: {str(e)}", "Wait 60 seconds and try again.")

        finish_reason = res.choices[0].finish_reason
        if finish_reason in ["length", "max_tokens"]:
            raise FinanceManagerException("AI Capacity", "Chunk truncated.", "List density too high.")

        raw_json = res.choices[0].message.content
        sanitized_json = re.sub(r',\s*([\]}])', r'\1', raw_json)

        try:
            data = json.loads(sanitized_json)
            return data.get("items", [])
        except json.JSONDecodeError as e:
            snippet = raw_json.strip()[:100].replace('\n', ' ')
            raise FinanceManagerException("AI Parsing Fault", f"Invalid JSON syntax: {str(e)}",
                                          f"Output snippet: {snippet}...")


async def parse_expense_text(raw_text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")

    current_date_str = get_ist_now().strftime("%B %d, %Y")
    current_year_str = get_ist_now().strftime("%Y")
    clean_text = preprocess_financial_text(raw_text)

    sys_prompt = (
        "Extract financial data into a compressed JSON array of arrays EXACTLY matching this format: "
        "{\"items\": [[amount(float), \"item_name\", \"date_str\" or \"\", \"category\", \"subcategory\", \"remarks\", \"Income\"|\"Expense\", \"payment_method\", \"frequency\", adjust_weekends(bool)]]}. "
        f"TODAY: {current_date_str}, YEAR: {current_year_str}. "
        "RULES: Exact amounts only. DO NOT output JSON keys inside the arrays. NO TRAILING COMMAS allowed."
    )

    lines = [line.strip() for line in clean_text.split('\n') if line.strip() and re.search(r'\d', line)]

    CHUNK_SIZE = 12
    chunks = []
    for i in range(0, len(lines), CHUNK_SIZE):
        chunks.append("\n".join(lines[i:i + CHUNK_SIZE]))

    if not chunks:
        chunks = [clean_text]

    # THE HARD CUTOFF: Vercel + Free Tier LLM Protection
    # 8 chunks * 500 max_tokens = 4000 output tokens + ~1000 input tokens = 5000 TPM (Safe).
    # Anything higher than 8 chunks risks hitting the 6000 TPM limit and crashing.
    if len(chunks) > 8:
        raise FinanceManagerException(
            "List Too Massive",
            "Your list exceeds the 6,000 Tokens-Per-Minute limit of our Free AI tier.",
            "Please split your message in half and send them 60 seconds apart."
        )

    tasks = [_process_chunk(chunk, sys_prompt) for chunk in chunks]
    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_extracted_arrays = []
    for res in chunk_results:
        if isinstance(res, Exception):
            raise res
        all_extracted_arrays.extend(res)

    results = []

    for ext in all_extracted_arrays:
        while len(ext) < 10:
            ext.append(False if len(ext) == 9 else "")

        try:
            amt = float(ext[0]) if ext[0] else 0.0
        except (ValueError, TypeError):
            amt = 0.0

        item = str(ext[1]).title().strip() if ext[1] else "Unknown Item"
        if item in [str(amt), str(int(amt)), "", "Unknown Item"]: item = "Unknown Item"

        date_str = str(ext[2]).strip() if ext[2] else None
        cat = str(ext[3]).title().strip() if ext[3] else "Misc"
        subcat = str(ext[4]).title().strip() if ext[4] else "General"
        if subcat.lower() == "unknown": subcat = "General"
        remarks = str(ext[5]).strip() if ext[5] else item
        t_type = str(ext[6]).title().strip() if ext[6] else "Expense"
        if t_type not in ["Income", "Expense"]: t_type = "Expense"
        p_method = str(ext[7]).title().strip() if ext[7] else "Cash/Upi"
        freq = str(ext[8]).lower().strip() if ext[8] else "none"
        adjust_weekends = bool(ext[9])

        today_date = get_ist_now().date()
        start_date = today_date

        if date_str:
            p_date = dateparser.parse(date_str, settings={'TIMEZONE': 'Asia/Kolkata', 'RELATIVE_BASE': get_ist_now()})
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
            end_date = today_date
        if end_date < start_date: end_date = start_date

        current_date = start_date
        loop_cap = 1000
        loops = 0

        while current_date <= end_date and loops < loop_cap:
            actual_date = current_date
            if adjust_weekends:
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