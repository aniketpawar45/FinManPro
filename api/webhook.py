import os
import httpx
from fastapi import APIRouter, Request, Header, HTTPException
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime

from core.database import save_transaction, get_all_categories, check_duplicate, get_user_stats, get_last_category, \
    supabase
from core.engine import parse_expense_text, transcribe_audio
from core.models import TransactionRecord
from core.utils import get_ist_now, FinanceManagerException, IST_TZ
from api.reports import handle_report_command, handle_csv_export
from api.stats import handle_statistics_command
from api.chart import handle_chart_command

router = APIRouter()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN")
bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None


@router.post("/webhook")
async def handle_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if WEBHOOK_SECRET_TOKEN and x_telegram_bot_api_secret_token != WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not bot: return {"status": "error"}
    update = await request.json()

    try:
        if "callback_query" in update:
            q = update["callback_query"]
            chat_id, uid, msg_id, data = q["message"]["chat"]["id"], str(q["from"]["id"]), q["message"]["message_id"], \
            q["data"]

            if data.startswith("csv:"):
                _, start_ts, end_ts = data.split(":")
                await handle_csv_export(bot, chat_id, uid, float(start_ts), float(end_ts))

            elif data.startswith("cat:"):
                parts = data.split(":")
                cat_id, amt, desc, d_ts = int(parts[1]), float(parts[2]), parts[3], float(parts[4])
                save_transaction(TransactionRecord(user_id=uid, amount=amt, category_id=cat_id, description=desc,
                                                   transaction_date=datetime.fromtimestamp(d_ts, tz=IST_TZ)))
                cat_name = next((c['category_name'] for c in get_all_categories() if c['id'] == cat_id), "Other")
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                            text=f"✅ Saved: {desc} - ₹{amt} ({cat_name})")

            elif data == "cancel":
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🚫 Entry cancelled.")

        elif "message" in update:
            msg = update["message"]
            chat_id, uid = msg["chat"]["id"], str(msg["from"]["id"])
            text = None

            if "text" in msg:
                text = msg["text"].strip()
            elif "voice" in msg:
                await bot.send_chat_action(chat_id=chat_id, action='typing')
                async with httpx.AsyncClient() as c:
                    f_info = (await c.get(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={msg['voice']['file_id']}")).json()
                    audio = (await c.get(
                        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{f_info['result']['file_path']}")).content
                text = await transcribe_audio(audio)
                await bot.send_message(chat_id, f"🎙️ Heard: {text}")

            if text:
                if text.startswith("/start"):
                    await bot.send_message(chat_id, "Welcome to FinManPro! Send expenses or voice notes.")
                elif text.startswith("/chart"):
                    await handle_chart_command(bot, chat_id, text, uid)
                elif text.startswith("/statistics"):
                    await handle_statistics_command(bot, chat_id, text, uid)
                elif text.startswith("/report"):
                    await handle_report_command(bot, chat_id, text, uid)
                elif text.startswith("/subscribe"):
                    try:
                        freq, emails = text.split()[1].lower(), text.split()[2]
                        supabase.table("report_schedules").insert(
                            {"telegram_id": uid, "frequency": freq, "emails": emails, "scheduled_hour": 9}).execute()
                        await bot.send_message(chat_id, f"✅ Subscribed: {freq.capitalize()} to {emails}")
                    except:
                        await bot.send_message(chat_id, "❌ Format: /subscribe <daily|weekly|monthly> <email>")
                elif text.startswith("/"):
                    await bot.send_message(chat_id, "Unknown command.")
                else:
                    await bot.send_chat_action(chat_id=chat_id, action='typing')
                    categories = get_all_categories()
                    for amt, desc, date, ai_cat in await parse_expense_text(text,
                                                                            [c['category_name'] for c in categories]):
                        if amt <= 0: continue
                        if check_duplicate(uid, amt, desc):
                            await bot.send_message(chat_id, f"🛡️ Duplicate prevented: {desc} - ₹{amt}")
                            continue

                        cat_id = get_last_category(desc) or next(
                            (c['id'] for c in categories if c['category_name'].lower() == ai_cat.lower()), None)
                        if cat_id:
                            save_transaction(
                                TransactionRecord(user_id=uid, amount=amt, category_id=cat_id, description=desc,
                                                  transaction_date=date))
                            cat_name = next(c['category_name'] for c in categories if c['id'] == cat_id)
                            await bot.send_message(chat_id, f"🤖 Auto-Saved: {desc} - ₹{amt} ({cat_name})")
                        else:
                            buttons = [[InlineKeyboardButton(c['category_name'],
                                                             callback_data=f"cat:{c['id']}:{amt}:{desc[:10]}:{date.timestamp()}")]
                                       for c in categories] + [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
                            await bot.send_message(chat_id, f"Select category for '{desc}' (₹{amt}):",
                                                   reply_markup=InlineKeyboardMarkup(buttons))

    except FinanceManagerException as e:
        if "chat_id" in locals(): await bot.send_message(chat_id, f"❌ **Error:** {e.message}")
    return {"status": "ok"}