import json
import urllib.parse
import logging
from core.analytics import parse_date_range, get_statistics_data

logger = logging.getLogger(__name__)


async def handle_chart_command(bot, chat_id, command, uid):
    # Default fallback values
    chart_type = "pie"
    query = "month"
    valid_chart_types = ['pie', 'bar', 'line', 'doughnut', 'radar', 'polararea']

    parts = command.split(maxsplit=1)
    if len(parts) > 1:
        # Check if the first word after /chart is a chart type
        sub_parts = parts[1].strip().split(maxsplit=1)
        potential_type = sub_parts[0].lower()

        if potential_type in valid_chart_types:
            chart_type = potential_type
            query = sub_parts[1] if len(sub_parts) > 1 else "month"
        else:
            # If no chart type is specified, use the whole string as the date query
            query = parts[1]

    # Map polararea back to proper Chart.js camelCase syntax
    if chart_type == 'polararea':
        chart_type = 'polarArea'

    # Safely query the upgraded analytics engine
    start, end, label = parse_date_range(query)
    stats = get_statistics_data(uid, start, end)

    if not stats or not stats.get('categories'):
        await bot.send_message(chat_id, f"⚠️ No data found for `{label}`.", parse_mode="Markdown")
        return

    labels = list(stats['categories'].keys())
    data = list(stats['categories'].values())

    # Extended neon color palette
    colors = ["#00B0FF", "#FFAB00", "#00E676", "#AA00FF", "#FF3D00", "#00E5FF", "#F50057", "#E040FB", "#F4FF81",
              "#18FFFF"]
    bg_colors = colors[:len(labels)]

    # Dynamic Chart.js configuration
    chart_config = {
        "type": chart_type,
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "Expenses (INR)",
                "data": data,
                "backgroundColor": bg_colors,
                "borderColor": "#121212" if chart_type in ['pie', 'doughnut', 'polarArea'] else bg_colors,
                "borderWidth": 2,
                "fill": False if chart_type == 'line' else True
            }]
        },
        "options": {
            "title": {
                "display": True,
                "text": f"EXPENDITURE: {label.upper()}",
                "fontColor": "#FFFFFF",
                "fontSize": 16
            },
            "legend": {
                "display": True if chart_type in ['pie', 'doughnut', 'polarArea'] else False,
                "position": "bottom",
                "labels": {"fontColor": "#B0BEC5"}
            },
            "scales": {}
        }
    }

    # Inject X/Y axes rendering specifically for bar and line charts
    if chart_type in ['bar', 'line']:
        chart_config["options"]["scales"] = {
            "yAxes": [{"ticks": {"beginAtZero": True, "fontColor": "#B0BEC5"}, "gridLines": {"color": "#333333"}}],
            "xAxes": [{"ticks": {"fontColor": "#B0BEC5"}, "gridLines": {"color": "#333333"}}]
        }

    # Encode payload and request image buffer
    chart_url = f"https://quickchart.io/chart?c={urllib.parse.quote(json.dumps(chart_config))}&bkg=0A0A0A"

    try:
        await bot.send_photo(
            chat_id,
            photo=chart_url,
            caption=f"📊 **Visual Report: {label}**\n📈 **Format:** {chart_type.capitalize()}\n💰 **Total: ₹{stats['total']:,.2f}**",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send chart: {e}")
        await bot.send_message(chat_id, "❌ Failed to generate the chart. The data might be too large or invalid.")