import os
import httpx
import logging
import traceback
from fastapi import APIRouter, Request, Header, HTTPException
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import date

from core.database import save_transaction, save_transactions_bulk, check_duplicate, filter_bulk_duplicates, \
    get_last_category
from core.engine import parse_expense_text, transcribe_audio
from core.models import TransactionRecord
from core.utils import get_ist_now, FinanceManagerException
from api.reports import handle_report_command, handle_csv_export
from api.stats import handle_statistics_command
from api.chart import handle_chart_command

logger = logging.getLogger(__name__)
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
        # ================= PHASE A: CALLBACK HANDLING =================
        if "callback_query" in update:
            q = update["callback_query"]
            chat_id, uid, msg_id, data = q["message"]["chat"]["id"], str(q["from"]["id"]), q["message"]["message_id"], \
            q["data"]

            if data.startswith("csv:"):
                _, start_ts, end_ts = data.split(":")
                await handle_csv_export(bot, chat_id, uid, float(start_ts), float(end_ts))
            elif data == "cancel":
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🚫 Entry cancelled.")
            elif data.startswith("unk:"):
                parts = data.split(":")
                amt, date_iso = float(parts[1]), parts[2]
                save_transaction(TransactionRecord(user_id=uid, amount=amt, category="Misc", subcategory="Unknown",
                                                   item_name="Unknown Item",
                                                   transaction_date=date.fromisoformat(date_iso),
                                                   remarks="Unknown Item"))
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                            text=f"✅ Saved: Unknown Item - ₹{amt} (Misc - Unknown)")
            elif data.startswith("fut:"):
                parts = data.split(":")
                amt, desc_snippet, date_iso, ai_cat, ai_subcat = float(parts[1]), parts[2], parts[3], parts[4], parts[5]
                save_transaction(TransactionRecord(user_id=uid, amount=amt, category=ai_cat, subcategory=ai_subcat,
                                                   item_name=desc_snippet,
                                                   transaction_date=date.fromisoformat(date_iso), remarks=desc_snippet))
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                            text=f"✅ Saved Future Entry: {desc_snippet} - ₹{amt} ({ai_cat})")

        # ================= PHASE B: MESSAGE HANDLING =================
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
                        from core.database import supabase
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
                    extracted_data = await parse_expense_text(text)

                    # CRITICAL FIX: Intercept Empty/Gibberish Returns
                    if not extracted_data:
                        await bot.send_message(chat_id,
                                               "⚠️ **Invalid Entry:** I couldn't recognize a valid expense. Please provide a clear item and amount (e.g., 'Milk 40').")
                        return {"status": "ok"}

                    is_bulk = len(extracted_data) > 1
                    dup_count = 0

                    if is_bulk:
                        extracted_data, dup_count = filter_bulk_duplicates(uid, extracted_data)

                    bulk_records_to_save = []
                    total_amt = 0
                    saved_details = []

                    for amt, item_name, item_date, ai_cat, ai_subcat, remarks in extracted_data:
                        if amt <= 0: continue

                        if not is_bulk and check_duplicate(uid, amt, item_name, item_date):
                            await bot.send_message(chat_id, f"🛡️ Duplicate prevented: {item_name} - ₹{amt}")
                            continue

                        if not is_bulk and item_name == "Unknown Item":
                            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Yes, save it",
                                                                             callback_data=f"unk:{amt}:{item_date.isoformat()}")],
                                                       [InlineKeyboardButton("No, cancel", callback_data="cancel")]])
                            await bot.send_message(chat_id,
                                                   f"⚠️ I found an amount (₹{amt}) but no item name.\nDo you want to save this anyway?",
                                                   reply_markup=kb)
                            continue

                        if not is_bulk and item_date > get_ist_now().date():
                            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Yes, save it",
                                                                             callback_data=f"fut:{amt}:{item_name[:10]}:{item_date.isoformat()}:{ai_cat[:10]}:{ai_subcat[:10]}")],
                                                       [InlineKeyboardButton("No, cancel", callback_data="cancel")]])
                            await bot.send_message(chat_id,
                                                   f"📅 Future date detected for '{item_name}': {item_date.strftime('%Y-%m-%d')}. Are you sure?",
                                                   reply_markup=kb)
                            continue

                        mem_cat, mem_subcat = get_last_category(item_name)
                        final_cat = mem_cat if (mem_cat and mem_cat.lower() not in ['other', 'misc']) else ai_cat
                        final_subcat = mem_subcat if (
                                    mem_subcat and mem_subcat.lower() not in ['general', 'unknown']) else ai_subcat

                        record = TransactionRecord(user_id=uid, amount=amt, category=final_cat,
                                                   subcategory=final_subcat, item_name=item_name,
                                                   transaction_date=item_date, remarks=remarks)

                        if is_bulk:
                            bulk_records_to_save.append(record)
                            total_amt += amt
                            saved_details.append(f"• {item_name}: ₹{amt} ({final_cat}/{final_subcat})")
                        else:
                            save_transaction(record)
                            await bot.send_message(chat_id,
                                                   f"🤖 Auto-Saved: {item_name} - ₹{amt} ({final_cat} - {final_subcat})\n📝 {remarks}")

                    if is_bulk and bulk_records_to_save:
                        save_transactions_bulk(bulk_records_to_save)
                        msg = f"✅ **Bulk Upload Successful!**\n💾 Saved: {len(bulk_records_to_save)} items\n💰 Total Amount: ₹{total_amt:,.2f}\n"
                        if dup_count > 0: msg += f"🛡️ Ignored {dup_count} duplicate retries.\n"

                        msg += f"\n*Preview:*\n" + "\n".join(saved_details[:15])
                        if len(saved_details) > 15: msg += f"\n... and {len(saved_details) - 15} more items."
                        await bot.send_message(chat_id, msg, parse_mode="Markdown")

                    elif is_bulk and dup_count > 0 and not bulk_records_to_save:
                        await bot.send_message(chat_id,
                                               f"🛡️ Ignored bulk list. All {dup_count} items were already saved recently.")

    # ================= ENTERPRISE TRIAGE ENGINE =================

    except FinanceManagerException as e:
        fault_type = "APPLICATION FAULT"
        if "Database" in e.step:
            fault_type = "DATABASE FAULT"
        elif "AI" in e.step or "Voice" in e.step:
            fault_type = "AI/VENDOR FAULT"

        error_msg = f"❌ **[{fault_type}]**\n**Node:** `{e.step}`\n**Details:** `{e.message}`\n**Action:** {e.action}"
        if "chat_id" in locals():
            try:
                await bot.send_message(chat_id, error_msg, parse_mode="Markdown")
            except:
                pass

    except httpx.RequestError as e:
        error_msg = f"🌐 **[NETWORK FAULT]**\n**Node:** `External API Routing`\n**Details:** `{str(e)}`\n**Action:** Verify outbound Vercel connections. Route to DevOps."
        if "chat_id" in locals():
            try:
                await bot.send_message(chat_id, error_msg, parse_mode="Markdown")
            except:
                pass

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"CRITICAL SYSTEM ERROR: {tb_str}")

        error_msg = f"🔥 **[APPLICATION FAULT]**\n**Node:** `Vercel Serverless Runtime ({e.__class__.__name__})`\n**Details:** `{str(e)}`\n**Action:** Assign to Backend Engineering Team."
        if "chat_id" in locals():
            try:
                await bot.send_message(chat_id, error_msg, parse_mode="Markdown")
            except:
                pass

    return {"status": "ok"}