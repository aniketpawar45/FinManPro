from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class ExpenseExtraction(BaseModel):
    amount: float = Field(default=0.0, description="Extracted final amount")
    item_name: str = Field(default="", description="Name of the item or expense")
    date_str: Optional[str] = Field(default=None, description="Date string if mentioned")
    end_date_str: Optional[str] = Field(default=None, description="End date string if recurring")
    frequency: str = Field(default="none", description="Frequency: daily, weekly, monthly, etc.")
    adjust_weekends: bool = Field(default=False, description="Whether to adjust weekends")
    category: str = Field(default="Other", description="Must be one of: Groceries, Transport, Utilities, Dining, Shopping, Rent, Entertainment, Medical, Other")
    subcategory: str = Field(default="General", description="Subcategory description")
    remarks: str = Field(default="", description="Additional remarks or notes")
    transaction_type: str = Field(default="Expense", description="Income or Expense")
    payment_method: str = Field(default="Cash/UPI", description="Payment method used")

class ExpenseBatch(BaseModel):
    items: List[ExpenseExtraction] = Field(default_factory=list, description="List of extracted expense items")