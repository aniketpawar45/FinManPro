from core.analytics import parse_date_range, get_statistics_data

EMOJIS = {"groceries": "🛒", "transport": "🚗", "utilities": "⚡", "dining": "🍽️", "shopping": "🛍️", "rent": "🏠",
          "entertainment": "🎬", "medical": "💊", "other": "📌"}


async def handle_statistics_command(bot, chat_id, command, uid):
    query = command.split(" ", 1)[1] if " " in command else "month"
    start, end, label = parse_date_range(query)
    stats = get_statistics_data(uid, start, end)

    if not stats: return await bot.send_message(chat_id, f"⚠️ No data found for {label}.")

    msg = f"🔥 *ANALYTICS: {label}*\n\n"
    max_val = max(stats['categories'].values()) if stats['categories'] else 1

    for cat, amt in sorted(stats['categories'].items(), key=lambda x: x[1], reverse=True):
        emoji = EMOJIS.get(cat.lower().strip(), "📌")
        ratio = amt / max_val
        block = "🟥" if ratio > 0.7 else "🟨" if ratio > 0.35 else "🟩"
        filled = max(1, int(ratio * 5))
        bar = (block * filled) + ("⬜" * (5 - filled))
        msg += f"{emoji} *{cat.upper()}*\n {bar}   `₹{amt:,.2f}`\n\n"

    msg += f"💰 *TOTAL: ₹{stats['total']:,.2f}*\n"
    await bot.send_message(chat_id, msg, parse_mode="Markdown")