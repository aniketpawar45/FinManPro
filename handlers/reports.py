from telegram import Update, InputFile
from telegram.ext import ContextTypes
from core.visualizer import generate_spending_pie_chart


async def handle_expense_chart_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Send the attractive rendering status message
    msg = await update.message.reply_text("🎨 Rendering dynamic financial chart...")

    try:
        # 2. Fetch or calculate category totals from Supabase (Mocked data for example)
        sample_category_data = {
            "Groceries": 15200.00,
            "Household": 2550.00,
            "Dairy": 3070.00,
            "Shopping": 1675.00,
            "Beverages": 480.00
        }

        # Generate chart bytes in memory
        chart_buffer = generate_spending_pie_chart(sample_category_data)

        # 3. Automatically delete the rendering status message
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id
        )

        # 4. Send the rendered image straight to Telegram
        await update.message.reply_photo(
            photo=InputFile(chart_buffer, filename="expense_breakdown.png"),
            caption="📈 **Here is your live dynamic expense visualization!**"
        )

    except Exception as e:
        # Cleanup status message on failure
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id
        )
        await update.message.reply_text(f"🚨 **Chart Rendering Failed**\nDetails: {str(e)}")