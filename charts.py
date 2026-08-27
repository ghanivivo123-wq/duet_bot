import io
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

import matplotlib
# Headless backend for VPS/server
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

logger = logging.getLogger(__name__)

# Set aesthetic styling
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial", "sans-serif"]
plt.rcParams["axes.edgecolor"] = "#E0E0E0"
plt.rcParams["axes.linewidth"] = 0.8


def format_rupiah(value: float | int) -> str:
    """Format number to Indonesian Rupiah currency string (e.g. Rp 150.000)."""
    try:
        val = float(value)
        formatted = f"{val:,.0f}".replace(",", ".")
        return f"Rp {formatted}"
    except (ValueError, TypeError):
        return f"Rp {value}"


def _rupiah_axis_formatter(x, pos):
    """Format axis ticks to concise Rupiah format."""
    if x >= 1_000_000:
        return f"Rp{x * 1e-6:.1f}M".replace(".0M", "M").replace(".", ",")
    elif x >= 1_000:
        return f"Rp{x * 1e-3:.0f}K"
    else:
        return f"Rp{x:.0f}"


def generate_bar_chart(expenses: List[Dict[str, Any]], period_label: str = "Bulan Ini") -> Optional[io.BytesIO]:
    """
    Generate daily expense bar chart.
    Returns io.BytesIO buffer positioned at start, or None if no data.
    """
    if not expenses:
        return None

    # Aggregate by date (YYYY-MM-DD)
    daily_totals: Dict[str, float] = defaultdict(float)
    for exp in expenses:
        tgl = exp.get("tanggal", "Unknown")
        nominal = float(exp.get("nominal", 0))
        daily_totals[tgl] += nominal

    if not daily_totals:
        return None

    # Sort dates chronologically
    sorted_dates = sorted(daily_totals.keys())
    # Format labels to "DD/MM" or "DD" for cleaner view
    labels = []
    for d in sorted_dates:
        parts = d.split("-")
        if len(parts) == 3:
            labels.append(f"{parts[2]}/{parts[1]}")
        else:
            labels.append(d)

    values = [daily_totals[d] for d in sorted_dates]

    # Calculate dimensions dynamically based on number of days
    fig_width = max(8.0, len(sorted_dates) * 0.45)
    fig, ax = plt.subplots(figsize=(fig_width, 5.0), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FAFAFA")

    # Bar chart with sleek gradient-like color
    bar_color = "#3B82F6"  # Tailwind Blue 500
    bars = ax.bar(labels, values, color=bar_color, width=0.6, edgecolor="#2563EB", linewidth=0.8, zorder=3)

    # Gridlines
    ax.yaxis.grid(True, linestyle="--", alpha=0.6, color="#CBD5E1", zorder=0)
    ax.xaxis.grid(False)

    # Format Y Axis to Rupiah
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(_rupiah_axis_formatter))

    # X Axis formatting
    plt.xticks(rotation=45 if len(sorted_dates) > 10 else 0, ha="right" if len(sorted_dates) > 10 else "center", fontsize=9)
    plt.yticks(fontsize=9)

    # Titles and labels
    ax.set_title(f"Grafik Pengeluaran Harian ({period_label})", fontsize=13, fontweight="bold", pad=15, color="#1E293B")
    ax.set_xlabel("Tanggal", fontsize=10, labelpad=8, color="#475569")
    ax.set_ylabel("Total Pengeluaran", fontsize=10, labelpad=8, color="#475569")

    # Add data labels on top of bars
    max_val = max(values) if values else 1
    ax.set_ylim(0, max_val * 1.18)  # Leave room for top text

    for bar in bars:
        height = bar.get_height()
        if height > 0:
            label_text = f"{height/1000:.0f}k" if height >= 1000 else f"{height:.0f}"
            ax.annotate(
                label_text,
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
                fontweight="medium",
                color="#1E293B",
            )

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_pie_chart(expenses: List[Dict[str, Any]], period_label: str = "Bulan Ini") -> Optional[io.BytesIO]:
    """
    Generate category expense donut / pie chart.
    Returns io.BytesIO buffer positioned at start, or None if no data.
    """
    if not expenses:
        return None

    # Aggregate by category
    category_totals: Dict[str, float] = defaultdict(float)
    total_all = 0.0
    for exp in expenses:
        cat = exp.get("kategori", "").strip() or "Lain-lain"
        nominal = float(exp.get("nominal", 0))
        category_totals[cat] += nominal
        total_all += nominal

    if not category_totals or total_all <= 0:
        return None

    # Sort categories by total descending
    sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    
    # If more than 7 categories, group smaller ones into "Lainnya"
    if len(sorted_cats) > 7:
        top_cats = sorted_cats[:6]
        other_sum = sum(val for _, val in sorted_cats[6:])
        top_cats.append(("Kategori Lainnya", other_sum))
        sorted_cats = top_cats

    labels = [cat for cat, _ in sorted_cats]
    values = [val for _, val in sorted_cats]

    # Clean modern color palette
    colors = [
        "#3B82F6",  # Blue
        "#10B981",  # Emerald
        "#F59E0B",  # Amber
        "#EF4444",  # Red
        "#8B5CF6",  # Purple
        "#EC4899",  # Pink
        "#64748B",  # Slate
    ]

    fig, ax = plt.subplots(figsize=(7.5, 5.5), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")

    # Donut chart
    wedges, texts, autotexts = ax.pie(
        values,
        labels=None,  # Labels handled by legend for cleaner look
        autopct="%1.1f%%",
        pctdistance=0.75,
        startangle=140,
        colors=colors[:len(values)],
        wedgeprops=dict(width=0.45, edgecolor="#FFFFFF", linewidth=2),
    )

    # Style percentage text
    for autotext in autotexts:
        autotext.set_color("#FFFFFF")
        autotext.set_fontsize(8.5)
        autotext.set_fontweight("bold")

    # Center text showing Grand Total
    ax.text(
        0, 0,
        f"Total\n{format_rupiah(total_all)}",
        ha="center",
        va="center",
        fontsize=10,
        fontweight="bold",
        color="#1E293B",
    )

    # Legend with detailed nominals
    legend_labels = [
        f"{cat} ({format_rupiah(val)} - {val/total_all*100:.1f}%)"
        for cat, val in sorted_cats
    ]
    ax.legend(
        wedges,
        legend_labels,
        title="Kategori Pengeluaran",
        loc="center left",
        bbox_to_anchor=(1, 0, 0.5, 1),
        fontsize=8.5,
        title_fontsize=9.5,
        frameon=False,
    )

    ax.set_title(f"Proporsi Pengeluaran per Kategori\n({period_label})", fontsize=12, fontweight="bold", pad=10, color="#1E293B")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
