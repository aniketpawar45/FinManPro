import os
import logging
from datetime import timedelta
from supabase import create_client, Client
from core.models import TransactionRecord
from core.utils import get_ist_now, FinanceManagerException

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

_CATEGORY_CACHE = [
    {"id": 1, "category_name": "Groceries"}, {"id": 2, "category_name": "Transport"},
    {"id": 3, "category_name": "Utilities"}, {"id": 4, "category_name": "Dining"},
    {"id": 5, "category_name": "Shopping"}, {"id": 6, "category_name": "Rent"},
    {"id": 7, "category_name": "Entertainment"}, {"id": 8, "category_name": "Medical"},
    {"id": 9, "category_name": "Other"}
]

def get_all_categories() -> list:
    return _CATEGORY_CACHE

def get_last_category(description: str) -> int | None:
    try:
        res = supabase.table("transactions").select("category_id").eq("description", description.title()).order("created_at", desc=True).limit(1).execute()
        return res.data[0]['category_id'] if res.data else None
    except:
        return None

def check_duplicate(user_id: str, amount: float, description: str) -> bool:
    try:
        ten_sec_ago = (get_ist_now() - timedelta(seconds=10)).isoformat()
        res = supabase.table("transactions").select("id").eq("user_id", user_id).eq("amount", amount).eq("description", description.title()).gt("created_at", ten_sec_ago).execute()
        return len(res.data) > 0
    except:
        return False

def save_transaction(record: TransactionRecord) -> bool:
    try:
        data = {
            "user_id": record.user_id,
            "amount": record.amount,
            "category_id": record.category_id,
            "description": record.description.title(),
            "transaction_date": record.transaction_date.isoformat(),
            "remarks": record.remarks
        }
        supabase.table("transactions").insert(data).execute()
        return True
    except Exception as e:
        raise FinanceManagerException("Database", f"Commit failed: {str(e)}", "Check Supabase.")

def get_user_stats(user_id: str) -> str:
    try:
        res = supabase.rpc("get_user_statistics", {"p_user_id": user_id}).execute()
        data = res.data
        if not data: return "No expenses logged."
        total = sum(float(row['total_spent']) for row in data)
        msg = f"💰 **Total Spent: ₹{total:,.2f}**\n\n**Breakdown:**\n"
        for row in data:
            msg += f"{row.get('category_name', 'Other')}: ₹{float(row.get('total_spent', 0)):,.2f}\n"
        return msg
    except:
        return "Failed to fetch stats."