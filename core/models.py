from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date


class ExpenseExtraction(BaseModel):
    amount: float = Field(default=0.0)
    item_name: str = Field(default="")
    date_str: Optional[str] = Field(default=None)
    end_date_str: Optional[str] = Field(default=None)
    frequency: str = Field(default="none")

    # CRITICAL FIX: Added switch for Business Day logic
    adjust_weekends: bool = Field(default=False)

    category: str = Field(default="Misc")
    subcategory: str = Field(default="Unknown")
    remarks: str = Field(default="")
    transaction_type: str = Field(default="Expense")
    payment_method: str = Field(default="Cash/UPI")


class ExpenseBatch(BaseModel):
    items: List[ExpenseExtraction] = Field(default_factory=list)


class TransactionRecord(BaseModel):
    user_id: str
    amount: float
    category: str
    subcategory: str
    item_name: str
    transaction_date: date
    remarks: str = ""
    transaction_type: str = "Expense"
    payment_method: str = "Cash/UPI"