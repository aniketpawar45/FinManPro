import os
import calendar
import dateparser
import re
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


def preprocess_financial_text(text: str) -> str:
    """Safely handles localized currency math before the LLM sees it, preventing truncation."""
    text = re.sub(r'([\d\.]+)\s*(?:lakhs?|l)\b', lambda m: str(int(round(float(m.group(1)) * 100000))), text,
                  flags=re.IGNORECASE)
    text = re.sub(r'([\d\.]+)\s*(?:k|thousands?)\b', lambda m: str(int(round(float(m.group(1)) * 1000))), text,
                  flags=re.IGNORECASE)
    return text


async def parse_expense_text(raw_text: str) -> list:
    if not client: raise FinanceManagerException("AI", "Groq API Key missing", "Set Env Var")
    current_date_str = get_ist_now().strftime("%B %d, %Y")
    current_year_str = get_ist_now().strftime("%Y")

    clean_text = preprocess_financial_text(raw_text)

    # THE FIX: One-Shot JSON Injection to eliminate all hallucinations.
    sys_prompt = (
        f"You are a strict financial extraction AI. TODAY'S DATE IS {current_date_str}. "
        "Extract the financial entries into JSON with an 'items' array. "
        "Each object must have: amount, item_name, date_str, category, subcategory, remarks, transaction_type, payment_method, frequency, end_date_str, adjust_weekends. "
        "CRITICAL RULES:\n"
        "1. ZERO HALLUCINATIONS: Do not invent amounts. If user says 'for 27', the amount is EXACTLY 27.\n"
        "2. TRANSACTION_TYPE: Classify strictly as 'Income' or 'Expense'.\n"
        "3. RECURRING DATES: You MUST output EXACTLY ONE JSON object for recurring entries. Set 'frequency' (daily, weekly, biweekly, monthly, quarterly, half-yearly, yearly).\n"
        "4. STRICT BOOLEAN ISOLATION: Set 'adjust_weekends' to true ONLY if 'business day', 'bank holiday', or 'weekend' is explicitly requested for that item.\n"
        f"5. HISTORICAL ANCHORING: Anchor dates without a month to January of the current year (e.g. 'Jan 25, {current_year_str}').\n"
        "6. NO CALENDAR MATH: Output exact calendar dates (e.g. Feb 28). The backend will handle weekend shifts.\n\n"
        "MANDATORY OUTPUT FORMAT EXAMPLE:\n"
        "User: \"Salary 2.51l on 25th shift to business day. Milk everyday for 27.\"\n"
        "Output: {\n"
        "  \"items\": [\n"
        f"    {{\"amount\": 251000, \"item_name\": \"Salary\", \"date_str\": \"Jan 25, {current_year_str}\", \"frequency\": \"monthly\", \"adjust_weekends\": true, \"transaction_type\": \"Income\", \"payment_method\": \"Bank\", \"category\": \"Income\", \"subcategory\": \"Salary\"}},\n"
        f"    {{\"amount\": 27, \"item_name\": \"Milk\", \"date_str\": \"Jan 1, {current_year_str}\", \"frequency\": \"daily\", \"adjust_weekends\": false, \"transaction_type\": \"Expense\", \"payment_method\": \"Cash/UPI\", \"category\": \"Groceries\", \"subcategory\": \"Dairy\"}}\n"
        "  ]\n"
        "}"
    )

    try:
        res = await client.chat.completions.create(
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": clean_text}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4000
        )
    except Exception as e:
        raise FinanceManagerException("AI Processing", f"Groq API Error: {str(e)}", "Wait 60 seconds and try again.")

    finish_reason = res.choices[0].finish_reason
    if finish_reason in ["length", "max_tokens"]:
        raise FinanceManagerException("AI Capacity Limit", "Input too massive. Truncated.", "  ROLLBACK INITIATED.")

    try:
        batch = ExpenseBatch.model_validate_json(res.choices[0].message.content)
    except Exception:
        raise FinanceManagerException("AI Parsing Fault", "Corrupted JSON.", "  ROLLBACK INITIATED.")

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

            # The backend calendar math execution (now protected by the 1-Shot boolean prompt)
            if ext.adjust_weekends:
                if actual_date.weekday() == 5:  # Saturday -> Friday
                    actual_date -= timedelta(days=1)
                elif actual_date.weekday() == 6:  # Sunday -> Friday
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