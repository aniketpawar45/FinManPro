from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class ExpenseExtraction(BaseModel):
    amount: float = Field(default=0.0)
    item_name: str = Field(default="")
    date_str: Optional[str] = Field(default=None)
    category: str = Field(default="Other")
    subcategory: str = Field(default="General")
    remarks: str = Field(default="")

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