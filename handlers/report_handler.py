import html
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
    first_name = html.escape(user.first_name) if user and user.first_name else "teman"

    welcome_text = (
        f"👋 <b>Halo {first_name}! Selamat datang di Bot Pencatat Pengeluaran.</b>\n\n"
        f"Bot ini siap membantu kamu mencatat pengeluaran otomatis via OCR Gemini dari struk QRIS atau nota fisik.\n\n"
        f"📌 <b>Cara Mencatat Transaksi:</b>\n"
        f"1. Kirim foto struk QRIS atau nota belanja langsung ke sini.\n"
        f"2. Sertakan caption keterangan belanja (misal: <code>Beli kopi susu</code>), atau bot akan menanyakannya jika kosong.\n"
        f"3. Bot akan mengekstrak nominal, merchant, tanggal, & kategori otomatis.\n"
        f"4. Cek hasil ekstraksi, lalu tekan <b>✅ Simpan</b>.\n\n"
        f"📊 <b>Menu Perintah Laporan & Pengaturan:</b>\n"
        f"• <code>/laporan</code> — Laporan & grafik harian bulan ini\n"
        f"• <code>/laporan 7hari</code> — Laporan & grafik 7 hari terakhir\n"
        f"• <code>/laporan YYYY-MM</code> — Laporan bulan tertentu (misal: <code>/laporan 2026-08</code>)\n"
        f"• <code>/kategori</code> — Grafik pie & rincian pengeluaran per kategori bulan ini\n"
        f"• <code>/edit [id]</code> — Edit data pengeluaran (misal: <code>/edit 5</code>)\n"
        f"• <code>/hapus_terakhir</code> — Hapus baris transaksi terakhir di Spreadsheet\n\n"
        f"💡 <i>Semua data tersimpan rapi di Google Sheets pribadimu.</i>"
    )

    await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


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
                "⚠️ <b>Format periode tidak dikenali.</b>\nGunakan:\n• <code>/laporan</code> (bulan ini)\n• <code>/laporan 7hari</code>\n• <code>/laporan YYYY-MM</code> (contoh: <code>/laporan 2026-08</code>)",
                parse_mode=ParseMode.HTML,
            )
            return

    status_msg = await message.reply_text("⏳ <i>Mengambil data dan menyusun laporan...</i>", parse_mode=ParseMode.HTML)

    try:
        expenses = sheets.get_expenses_by_period(period)

        if not expenses:
            await status_msg.edit_text(
                f"ℹ️ Tidak ditemukan catatan pengeluaran untuk periode <b>{html.escape(period_label)}</b>.",
                parse_mode=ParseMode.HTML,
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
            f"📊 <b>Laporan Pengeluaran ({html.escape(period_label)})</b>",
            f"━━━━━━━━━━━━━━━━━━",
            f"💰 <b>Total Pengeluaran</b> : <code>{charts.format_rupiah(total_pengeluaran)}</code>",
            f"🧾 <b>Total Transaksi</b>   : <code>{total_transaksi}</code> transaksi",
            f"📅 <b>Rata-rata Harian</b>  : <code>{charts.format_rupiah(rata_rata_harian)}</code> / hari ({len(unique_dates)} hari aktif)",
            f"🏆 <b>Kategori Terbesar</b> : <b>{html.escape(top_category)}</b> (<code>{charts.format_rupiah(top_category_amount)}</code> / {top_cat_pct:.1f}%)",
            f"━━━━━━━━━━━━━━━━━━",
        ]
        caption = "\n".join(caption_lines)

        await status_msg.delete()

        if chart_buffer:
            await message.reply_photo(
                photo=chart_buffer,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(caption, parse_mode=ParseMode.HTML)

    except Exception as exc:
        logger.error("Error generating /laporan: %s", exc, exc_info=True)
        await status_msg.edit_text(f"❌ Gagal memuat laporan: <code>{html.escape(str(exc))}</code>", parse_mode=ParseMode.HTML)


@config.restricted
async def kategori_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /kategori
    Generates pie chart and detailed breakdown of expenses by category for current month.
    """
    message = update.effective_message
    current_month_str = datetime.now().strftime("%Y-%m")
    period_label = f"Bulan {current_month_str}"

    status_msg = await message.reply_text("⏳ <i>Menghitung rincian kategori pengeluaran...</i>", parse_mode=ParseMode.HTML)

    try:
        expenses = sheets.get_expenses_by_period("bulan-ini")

        if not expenses:
            await status_msg.edit_text(
                f"ℹ️ Belum ada catatan pengeluaran di {html.escape(period_label)}.",
                parse_mode=ParseMode.HTML,
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
            f"🥧 <b>Proporsi Kategori ({html.escape(period_label)})</b>",
            f"💰 <b>Total:</b> <code>{charts.format_rupiah(total_pengeluaran)}</code>\n",
            f"━━━━━━━━━━━━━━━━━━",
        ]

        for idx, (cat, amount) in enumerate(sorted_cats, start=1):
            pct = (amount / total_pengeluaran * 100) if total_pengeluaran > 0 else 0
            cnt = category_counts[cat]
            breakdown_lines.append(
                f"{idx}. <b>{html.escape(cat)}</b>: <code>{charts.format_rupiah(amount)}</code> ({pct:.1f}%) — <i>{cnt}x</i>"
            )
        breakdown_lines.append(f"━━━━━━━━━━━━━━━━━━")

        caption = "\n".join(breakdown_lines)

        await status_msg.delete()

        if chart_buffer:
            await message.reply_photo(
                photo=chart_buffer,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(caption, parse_mode=ParseMode.HTML)

    except Exception as exc:
        logger.error("Error generating /kategori: %s", exc, exc_info=True)
        await status_msg.edit_text(f"❌ Gagal memuat grafik kategori: <code>{html.escape(str(exc))}</code>", parse_mode=ParseMode.HTML)
