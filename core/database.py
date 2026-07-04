import os
import logging
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
        res = supabase.table("transactions").select("amount, item_name").eq("user_id", user_id).gt("created_at",
                                                                                                   sixty_sec_ago).execute()

        existing_records = {(float(r['amount']), r['item_name'].title()) for r in res.data}
        unique_data = []
        dup_count = 0

        for data in extracted_data:
            amt, item_name = float(data[0]), data[1].title()
            if (amt, item_name) in existing_records:
                dup_count += 1
            else:
                unique_data.append(data)
                existing_records.add((amt, item_name))

        return unique_data, dup_count
    except Exception as e:
        logger.error(f"Bulk duplicate filter failed: {str(e)}")
        return extracted_data, 0


def save_transaction(record: TransactionRecord) -> bool:
    try:
        # CRITICAL FIX: Ensuring Supabase receives the new Credit/Debit data
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

        msg = f"💰 **Total Spent: ₹{total:,.2f}**\n\n**Breakdown:**\n"
        for c, a in sorted(cat_map.items(), key=lambda x: x[1], reverse=True): msg += f"{c}: ₹{a:,.2f}\n"
        return msg
    except:
        return "Failed to fetch stats."