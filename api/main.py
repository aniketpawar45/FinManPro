import os
from fastapi import FastAPI, HTTPException
from telegram import Bot, BotCommand
from api.webhook import router as webhook_router
from api.cron import router as cron_router

app = FastAPI(title="FinManPro API", docs_url=None, redoc_url=None)
app.include_router(webhook_router, prefix="/api")
app.include_router(cron_router, prefix="/api")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN")


@app.get("/healthz")
async def health():
    return {"status": "Enterprise Systems Operational"}


@app.get("/api/setup")
async def setup_bot():
    """One-Click Script to configure the Telegram UI Menu and lock the Webhook."""
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Missing Bot Token")

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Define the Native Telegram UI Menu (Chart functionality removed)
    commands = [
        BotCommand("start", "Welcome & Instructions"),
        BotCommand("report", "Generate Visual Dashboard & CSV Data"),
        BotCommand("statistics", "View Text-Based Expenditure Stats"),
        BotCommand("subscribe", "Automate Reports (daily/weekly/monthly)")
    ]

    try:
        # Push the menu commands directly to the Telegram servers
        await bot.set_my_commands(commands)

        # Verify and lock Webhook routing for security
        webhook_url = "https://fin-man-pro.vercel.app/api/webhook"
        await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET_TOKEN)

        return {
            "status": "Success",
            "message": "Telegram UI Menu and Webhook have been securely locked into production.",
            "menu_installed": [c.command for c in commands]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))