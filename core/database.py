import os
import logging
import calendar
from datetime import timedelta, date
from supabase import create_client, Client
from core.models import TransactionRecord
from core.utils import get_ist_now, FinanceManagerException

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None


def get_last_category(item_name: str):
    try:
        res = supabase.table("transactions").select("category, subcategory").eq("item_name", item_name.title()).order(
            "created_at", desc=True).limit(1).execute()
        if res.data: return res.data[0].get('category', 'Other'), res.data[0].get('subcategory', 'General')
        return None, None
    except:
        return None, None


def check_duplicate(user_id: str, amount: float, item_name: str, transaction_date: date) -> bool:
    try:
        ten_sec_ago = (get_ist_now() - timedelta(seconds=10)).isoformat()
        res = supabase.table("transactions").select("id").eq("user_id", user_id).eq("amount", amount).eq("item_name",
                                                                                                         item_name.title()).eq(
            "transaction_date", transaction_date.isoformat()).gt("created_at", ten_sec_ago).execute()
        return len(res.data) > 0
    except:
        return False


def filter_bulk_duplicates(user_id: str, extracted_data: list) -> tuple:
    try:
        sixty_sec_ago = (get_ist_now() - timedelta(seconds=60)).isoformat()
        res = supabase.table("transactions").select("amount, item_name, transaction_date").eq("user_id", user_id).gt(
            "created_at", sixty_sec_ago).execute()

        existing_records = {(float(r['amount']), r['item_name'].title(), r['transaction_date']) for r in res.data}

        unique_data = []
        dup_count = 0
        for data in extracted_data:
            amt, item_name, item_date = float(data[0]), data[1].title(), data[2]
            date_str = item_date.isoformat()

            if (amt, item_name, date_str) in existing_records:
                dup_count += 1
            else:
                unique_data.append(data)
                existing_records.add((amt, item_name, date_str))

        return unique_data, dup_count
    except Exception as e:
        logger.error(f"Bulk duplicate filter failed: {str(e)}")
        return extracted_data, 0


def save_transaction(record: TransactionRecord) -> bool:
    try:
        data = {
            "user_id": record.user_id,
            "amount": record.amount,
            "category": record.category,
            "subcategory": record.subcategory,
            "item_name": record.item_name.title(),
            "transaction_date": record.transaction_date.isoformat(),
            "remarks": record.remarks,
            "transaction_type": record.transaction_type,
            "payment_method": record.payment_method
        }
        supabase.table("transactions").insert(data).execute()
        return True
    except Exception as e:
        raise FinanceManagerException("Database", f"Commit failed: {str(e)}", "Check Supabase.")


def save_transactions_bulk(records: list[TransactionRecord]) -> bool:
    try:
        if not records: return True
        data = [{
            "user_id": r.user_id,
            "amount": r.amount,
            "category": r.category,
            "subcategory": r.subcategory,
            "item_name": r.item_name.title(),
            "transaction_date": r.transaction_date.isoformat(),
            "remarks": r.remarks,
            "transaction_type": r.transaction_type,
            "payment_method": r.payment_method
        } for r in records]
        supabase.table("transactions").insert(data).execute()
        return True
    except Exception as e:
        raise FinanceManagerException("Database", f"Bulk Commit failed: {str(e)}", "Check Supabase.")


def get_user_stats(user_id: str) -> str:
    try:
        res = supabase.table("transactions").select("category, amount").eq("user_id", user_id).execute()
        if not res.data: return "No expenses logged."
        cat_map = {}
        total = 0.0
        for row in res.data:
            c = row.get('category', 'Other')
            a = float(row.get('amount', 0))
            cat_map[c] = cat_map.get(c, 0) + a
            total += a
        msg = f"  **Total Spent:  {total:,.2f}**\n\n**Breakdown:**\n"
        for c, a in sorted(cat_map.items(), key=lambda x: x[1], reverse=True): msg += f"{c}:  {a:,.2f}\n"
        return msg
    except:
        return "Failed to fetch stats."


def get_recent_transactions(user_id: str, limit: int = 5, offset: int = 0, keyword: str = None) -> tuple[list, int]:
    """Fetches paginated transactions for the delete UI context, with intelligent month parsing."""
    try:
        query = supabase.table("transactions").select("id, item_name, amount, transaction_date", count="exact").eq(
            "user_id", user_id)

        if keyword:
            kw_lower = keyword.strip().lower()

            # Month lookup map to cover short names, full names, and numbers
            month_map = {
                'jan': 1, 'january': 1, '1': 1, '01': 1,
                'feb': 2, 'february': 2, '2': 2, '02': 2,
                'mar': 3, 'march': 3, '3': 3, '03': 3,
                'apr': 4, 'april': 4, '4': 4, '04': 4,
                'may': 5, '5': 5, '05': 5,
                'jun': 6, 'june': 6, '6': 6, '06': 6,
                'jul': 7, 'july': 7, '7': 7, '07': 7,
                'aug': 8, 'august': 8, '8': 8, '08': 8,
                'sep': 9, 'september': 9, '9': 9, '09': 9,
                'oct': 10, 'october': 10, '10': 10,
                'nov': 11, 'november': 11, '11': 11,
                'dec': 12, 'december': 12, '12': 12
            }

            # If keyword is a recognized month, filter by date range instead of item name
            if kw_lower in month_map:
                target_month = month_map[kw_lower]
                current_year = get_ist_now().year

                start_date = date(current_year, target_month, 1)
                end_date = date(current_year, target_month, calendar.monthrange(current_year, target_month)[1])

                query = query.gte("transaction_date", start_date.isoformat()).lte("transaction_date",
                                                                                  end_date.isoformat())
            else:
                # Fallback to standard item_name search
                query = query.ilike("item_name", f"%{keyword}%")

        res = query.order("transaction_date", desc=True).range(offset, offset + limit - 1).execute()
        return res.data, res.count
    except Exception as e:
        logger.error(f"Failed to fetch paginated transactions: {str(e)}")
        return [], 0


def delete_transactions(user_id: str, transaction_ids: list[int]) -> bool:
    """Executes a hard delete. The Supabase Trigger will handle the audit log."""
    try:
        if not transaction_ids: return True
        supabase.table("transactions").delete().eq("user_id", user_id).in_("id", transaction_ids).execute()
        return True
    except Exception as e:
        raise FinanceManagerException("Database", f"Delete failed: {str(e)}", "Check Supabase.")