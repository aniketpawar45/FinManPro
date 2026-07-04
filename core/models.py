from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ExpenseExtraction(BaseModel):
    amount: float = Field(default=0.0)
    item_name: str = Field(default="")
    date_str: Optional[str] = Field(default=None)
    category_name: str = Field(default="Other")

class ExpenseBatch(BaseModel):
    items: List[ExpenseExtraction] = Field(default_factory=list)

class TransactionRecord(BaseModel):
    user_id: str
    amount: float
    category_id: int
    description: str
    transaction_date: datetime
    remarks: str = ""