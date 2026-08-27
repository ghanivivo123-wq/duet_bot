import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import charts
import config
import sheets

logger = logging.getLogger(__name__)


@config.restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - onboarding guide."""
    user = update.effective_user
    first_name = user.first_name if user else "teman"

    welcome_text = (
        f"👋 *Halo {first_name}! Selamat datang di Bot Pencatat Pengeluaran.*\n\n"
        f"Bot ini siap membantu kamu mencatat pengeluaran otomatis via OCR Gemini dari struk QRIS atau nota fisik.\n\n"
        f"📌 *Cara Mencatat Transaksi:*\n"
        f"1. Kirim foto struk QRIS atau nota belanja langsung ke sini.\n"
        f"2. Sertakan caption keterangan belanja (misal: `Beli kopi susu`), atau bot akan menanyakannya jika kosong.\n"
        f"3. Bot akan mengekstrak nominal, merchant, tanggal, & kategori otomatis.\n"
        f"4. Cek hasil ekstraksi, lalu tekan *✅ Simpan*.\n\n"
        f"📊 *Menu Perintah Laporan & Pengaturan:*\n"
        f"• `/laporan` — Laporan & grafik harian bulan ini\n"
        f"• `/laporan 7hari` — Laporan & grafik 7 hari terakhir\n"
        f"• `/laporan YYYY-MM` — Laporan bulan tertentu (misal: `/laporan 2026-08`)\n"
        f"• `/kategori` — Grafik pie & rincian pengeluaran per kategori bulan ini\n"
        f"• `/edit [id]` — Edit data pengeluaran (misal: `/edit 5`)\n"
        f"• `/hapus_terakhir` — Hapus baris transaksi terakhir di Spreadsheet\n\n"
        f"💡 _Semua data tersimpan rapi di Google Sheets pribadimu._"
    )

    await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


@config.restricted
async def laporan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /laporan [periode]
    Periods: 'bulan-ini' (default), '7hari', or 'YYYY-MM'
    """
    message = update.effective_message
    args = context.args or []

    period = "bulan-ini"
    period_label = "Bulan Ini"

    if args:
        raw_arg = args[0].strip().lower()
        if raw_arg in ["7hari", "7-hari", "mingguan", "week"]:
            period = "7hari"
            period_label = "7 Hari Terakhir"
        elif len(raw_arg) == 7 and raw_arg[4] == "-":
            period = raw_arg
            period_label = f"Bulan {raw_arg}"
        elif raw_arg in ["semua", "all"]:
            period = "all"
            period_label = "Semua Waktu"
        else:
            await message.reply_text(
                "⚠️ Format periode tidak dikenali.\nGunakan:\n• `/laporan` (bulan ini)\n• `/laporan 7hari`\n• `/laporan YYYY-MM` (contoh: `/laporan 2026-08`)",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    status_msg = await message.reply_text("⏳ _Mengambil data dan menyusun laporan..._", parse_mode=ParseMode.MARKDOWN)

    try:
        expenses = sheets.get_expenses_by_period(period)

        if not expenses:
            await status_msg.edit_text(
                f"ℹ️ Tidak ditemukan catatan pengeluaran untuk periode *{period_label}*.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Calculate statistics
        total_pengeluaran = sum(float(e.get("nominal", 0)) for e in expenses)
        total_transaksi = len(expenses)

        # Unique active days
        unique_dates = {e.get("tanggal") for e in expenses if e.get("tanggal")}
        num_days = max(1, len(unique_dates))
        rata_rata_harian = total_pengeluaran / num_days

        # Category aggregation
        category_totals: Dict[str, float] = defaultdict(float)
        for e in expenses:
            cat = e.get("kategori", "Lain-lain") or "Lain-lain"
            category_totals[cat] += float(e.get("nominal", 0))

        top_category, top_category_amount = "", 0.0
        if category_totals:
            top_category, top_category_amount = max(category_totals.items(), key=lambda x: x[1])

        top_cat_pct = (top_category_amount / total_pengeluaran * 100) if total_pengeluaran > 0 else 0

        # Generate Bar Chart
        chart_buffer = charts.generate_bar_chart(expenses, period_label)

        # Caption text
        caption_lines = [
            f"📊 *Laporan Pengeluaran ({period_label})*",
            f"━━━━━━━━━━━━━━━━━━",
            f"💰 *Total Pengeluaran* : `{charts.format_rupiah(total_pengeluaran)}`",
            f"🧾 *Total Transaksi*   : `{total_transaksi}` transaksi",
            f"📅 *Rata-rata Harian*  : `{charts.format_rupiah(rata_rata_harian)}` / hari ({len(unique_dates)} hari aktif)",
            f"🏆 *Kategori Terbesar* : *{top_category}* (`{charts.format_rupiah(top_category_amount)}` / {top_cat_pct:.1f}%)",
            f"━━━━━━━━━━━━━━━━━━",
        ]
        caption = "\n".join(caption_lines)

        await status_msg.delete()

        if chart_buffer:
            await message.reply_photo(
                photo=chart_buffer,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)

    except Exception as exc:
        logger.error("Error generating /laporan: %s", exc, exc_info=True)
        await status_msg.edit_text(f"❌ Gagal memuat laporan: `{exc}`", parse_mode=ParseMode.MARKDOWN)


@config.restricted
async def kategori_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /kategori
    Generates pie chart and detailed breakdown of expenses by category for current month.
    """
    message = update.effective_message
    current_month_str = datetime.now().strftime("%Y-%m")
    period_label = f"Bulan {current_month_str}"

    status_msg = await message.reply_text("⏳ _Menghitung rincian kategori pengeluaran..._", parse_mode=ParseMode.MARKDOWN)

    try:
        expenses = sheets.get_expenses_by_period("bulan-ini")

        if not expenses:
            await status_msg.edit_text(
                f"ℹ️ Belum ada catatan pengeluaran di {period_label}.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        total_pengeluaran = sum(float(e.get("nominal", 0)) for e in expenses)

        # Aggregate by category
        category_totals: Dict[str, float] = defaultdict(float)
        category_counts: Dict[str, int] = defaultdict(int)

        for e in expenses:
            cat = e.get("kategori", "Lain-lain") or "Lain-lain"
            nom = float(e.get("nominal", 0))
            category_totals[cat] += nom
            category_counts[cat] += 1

        sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

        # Generate Pie Chart
        chart_buffer = charts.generate_pie_chart(expenses, period_label)

        # Build detailed breakdown caption
        breakdown_lines = [
            f"🥧 *Proporsi Kategori ({period_label})*",
            f"💰 *Total:* `{charts.format_rupiah(total_pengeluaran)}`\n",
            f"━━━━━━━━━━━━━━━━━━",
        ]

        for idx, (cat, amount) in enumerate(sorted_cats, start=1):
            pct = (amount / total_pengeluaran * 100) if total_pengeluaran > 0 else 0
            cnt = category_counts[cat]
            breakdown_lines.append(
                f"{idx}. *{cat}*: `{charts.format_rupiah(amount)}` ({pct:.1f}%) — _{cnt}x_"
            )
        breakdown_lines.append(f"━━━━━━━━━━━━━━━━━━")

        caption = "\n".join(breakdown_lines)

        await status_msg.delete()

        if chart_buffer:
            await message.reply_photo(
                photo=chart_buffer,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)

    except Exception as exc:
        logger.error("Error generating /kategori: %s", exc, exc_info=True)
        await status_msg.edit_text(f"❌ Gagal memuat grafik kategori: `{exc}`", parse_mode=ParseMode.MARKDOWN)
