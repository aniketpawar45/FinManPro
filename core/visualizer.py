import io
import matplotlib
matplotlib.use('Agg') # Essential for headless serverless environments
import matplotlib.pyplot as plt
import seaborn as sns

def generate_spending_pie_chart(category_totals: dict) -> io.BytesIO:
    """
    Generates a sleek, high-DPI dynamic pie chart of expenses by category
    and returns it as an in-memory byte buffer.
    """
    # Set professional styling
    sns.set_theme(style="whitegrid")
    fig, ax = plt.subplots(figsize=(8, 6), dpi=300)

    categories = list(category_totals.keys())
    amounts = list(category_totals.values())

    # Custom vibrant color palette
    colors = sns.color_palette("muted", len(categories))

    wedges, texts, autotexts = ax.pie(
        amounts,
        labels=categories,
        autopct='%1.1f%%',
        startangle=140,
        colors=colors,
        wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2) # Donut chart style
    )

    # Styling text elements for Telegram readability
    plt.setp(autotexts, size=10, weight="bold", color="black")
    plt.setp(texts, size=11, weight="semibold", color="#333333")

    ax.set_title("📊 Expense Breakdown by Category", fontsize=14, weight="bold", pad=20)

    # Save to memory buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)

    return buf