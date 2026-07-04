from fastapi import FastAPI
from api.webhook import router as webhook_router
from api.cron import router as cron_router

app = FastAPI(title="FinManPro API", docs_url=None, redoc_url=None)

app.include_router(webhook_router, prefix="/api")
app.include_router(cron_router, prefix="/api")

@app.get("/healthz")
async def health():
    return {"status": "Enterprise Systems Operational"}