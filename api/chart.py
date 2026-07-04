import json
import urllib.parse
from core.analytics import parse_date_range, get_statistics_data


async def handle_chart_command(bot, chat_id, command, uid):
    parts = command.split(maxsplit=1)
    query = parts[1] if len(parts) > 1 else "month"
    start, end, label = parse_date_range(query)
    stats = get_statistics_data(uid, start, end)

    if not stats or not stats.get('categories'):
        await bot.send_message(chat_id, f"⚠️ No data found for `{label}`.", parse_mode="Markdown")
        return

    labels, data = list(stats['categories'].keys()), list(stats['categories'].values())
    colors = ["#00B0FF", "#FFAB00", "#00E676", "#AA00FF", "#FF3D00", "#00E5FF", "#F50057", "#E040FB"]

    chart_config = {
        "type": "pie",
        "data": {"labels": labels, "datasets": [
            {"data": data, "backgroundColor": colors[:len(labels)], "borderColor": "#121212", "borderWidth": 2}]},
        "options": {
            "title": {"display": True, "text": f"EXPENDITURE: {label.upper()}", "fontColor": "#FFFFFF", "fontSize": 16},
            "legend": {"position": "bottom", "labels": {"fontColor": "#B0BEC5"}}}
    }

    chart_url = f"https://quickchart.io/chart?c={urllib.parse.quote(json.dumps(chart_config))}&bkg=0A0A0A"
    await bot.send_photo(chat_id, photo=chart_url,
                         caption=f"📊 **Visual Report: {label}**\n💰 **Total: ₹{stats['total']:,.2f}**",
                         parse_mode="Markdown")