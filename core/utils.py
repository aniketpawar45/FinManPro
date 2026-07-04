import pytz
from datetime import datetime

IST_TZ = pytz.timezone('Asia/Kolkata')

def get_ist_now() -> datetime:
    return datetime.now(IST_TZ)

class FinanceManagerException(Exception):
    def __init__(self, step: str, message: str, action: str):
        self.step = step
        self.message = message
        self.action = action
        super().__init__(f"[{step}] - {message} (Action: {action})")