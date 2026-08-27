import html
import logging
import re
from typing import Any, Dict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import charts
import config
import sheets
from handlers.photo_handler import _parse_field_updates

logger = logging.getLogger(__name__)

# State for /edit [id]
AWAITING_ROW_EDIT = 10


# -----------------------------------------------------------------------------
# /hapus_terakhir Handlers
# -----------------------------------------------------------------------------

@config.restricted
async def hapus_terakhir_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /hapus_terakhir command - asks confirmation before deleting last row."""
    message = update.effective_message

    try:
        all_records = sheets.get_all_expenses()
        if not all_records:
            await message.reply_text("ℹ️ Belum ada data pengeluaran yang tersimpan di Google Sheets.")
            return

        last_record = all_records[-1]
        exp_id = last_record.get("id", "-")
        nominal_formatted = charts.format_rupiah(last_record.get("nominal", 0))
        keterangan = html.escape(str(last_record.get("keterangan", "-")))
        tanggal = html.escape(str(last_record.get("tanggal", "-")))
        kategori = html.escape(str(last_record.get("kategori", "-")))

        confirm_text = (
            f"⚠️ <b>Konfirmasi Hapus Transaksi Terakhir</b>\n\n"
            f"Yakin ingin menghapus data transaksi berikut dari Spreadsheet?\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>ID</b>        : <code>{exp_id}</code>\n"
            f"💵 <b>Nominal</b>   : <code>{nominal_formatted}</code>\n"
            f"🏷 <b>Keterangan</b>: {keterangan}\n"
            f"📁 <b>Kategori</b>  : {kategori}\n"
            f"📅 <b>Tanggal</b>   : <code>{tanggal}</code>\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

        keyboard = [
            [
                InlineKeyboardButton("🗑️ Ya, Hapus", callback_data=f"confirm_delete_last_{exp_id}"),
                InlineKeyboardButton("❌ Batal", callback_data="cancel_delete_last"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await message.reply_text(confirm_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    except Exception as exc:
        logger.error("Error on /hapus_terakhir: %s", exc, exc_info=True)
        await message.reply_text(f"❌ Terjadi kesalahan: <code>{html.escape(str(exc))}</code>", parse_mode=ParseMode.HTML)


@config.restricted
async def callback_confirm_delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback when user confirms deleting last row."""
    query = update.callback_query
    await query.answer()

    try:
        deleted = sheets.delete_last_expense()
        if not deleted:
            await query.edit_message_text("⚠️ Tidak ada transaksi yang dapat dihapus.")
            return

        exp_id = deleted.get("id", "-")
        nominal = charts.format_rupiah(deleted.get("nominal", 0))
        ket = html.escape(str(deleted.get("keterangan", "")))

        await query.edit_message_text(
            f"✅ <b>Transaksi ID {exp_id}</b> (<code>{nominal}</code> — <i>{ket}</i>) berhasil dihapus dari Google Sheets.",
            parse_mode=ParseMode.HTML,
        )

    except Exception as exc:
        logger.error("Error deleting last expense: %s", exc, exc_info=True)
        await query.edit_message_text(f"❌ Gagal menghapus baris dari Google Sheets: <code>{html.escape(str(exc))}</code>", parse_mode=ParseMode.HTML)


@config.restricted
async def callback_cancel_delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback when user cancels deleting last row."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Penghapusan data transaksi dibatalkan.")


# -----------------------------------------------------------------------------
# /edit [id] Conversation Flow
# -----------------------------------------------------------------------------

@config.restricted
async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle /edit [id] command.
    Fetches record from Google Sheets and prompts user for updates.
    """
    message = update.effective_message
    args = context.args or []

    if not args:
        await message.reply_text(
            "⚠️ Harap sertakan ID transaksi yang ingin diedit.\n\nContoh: <code>/edit 5</code>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    try:
        target_id = int(args[0])
    except ValueError:
        await message.reply_text("⚠️ ID transaksi harus berupa angka.\nContoh: <code>/edit 5</code>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    status_msg = await message.reply_text(f"⏳ <i>Mencari data transaksi ID {target_id}...</i>", parse_mode=ParseMode.HTML)

    try:
        record, row_idx = sheets.get_expense_by_id(target_id)
        if not record:
            await status_msg.edit_text(f"❌ Transaksi dengan ID <code>{target_id}</code> tidak ditemukan di Spreadsheet.", parse_mode=ParseMode.HTML)
            return ConversationHandler.END

        # Store editing state in context
        context.user_data["editing_expense_id"] = target_id
        context.user_data["editing_expense_data"] = record

        nominal_formatted = charts.format_rupiah(record.get("nominal", 0))

        info_text = (
            f"📝 <b>Edit Transaksi ID: {target_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Jenis Bukti</b> : {html.escape(str(record.get('jenis_bukti', '-')))}\n"
            f"• <b>Tanggal</b>     : <code>{html.escape(str(record.get('tanggal', '-')))}</code>\n"
            f"• <b>Waktu</b>       : <code>{html.escape(str(record.get('waktu', '-')))}</code>\n"
            f"• <b>Nominal</b>     : <code>{nominal_formatted}</code>\n"
            f"• <b>Merchant</b>    : {html.escape(str(record.get('merchant', '-') or '-'))}\n"
            f"• <b>Keterangan</b>  : {html.escape(str(record.get('keterangan', '-')))}\n"
            f"• <b>Kategori</b>    : {html.escape(str(record.get('kategori', '-')))}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"Kirim field yang ingin diubah. Contoh:\n"
            f"• <code>nominal: 45000</code>\n"
            f"• <code>keterangan: Nasi Padang Komplit</code>\n"
            f"• <code>kategori: Makanan & Minuman</code>\n"
            f"• <code>merchant: RM Padang Sederhana</code>\n"
            f"• <code>tanggal: 2026-08-27</code>\n"
            f"• <code>waktu: 12:30</code>\n"
            f"• <code>jenis_bukti: QRIS</code>\n\n"
            f"<i>(Bisa ubah beberapa field sekaligus per baris. Ketik <code>batal</code> untuk membatalkan)</i>"
        )

        await status_msg.edit_text(info_text, parse_mode=ParseMode.HTML)
        return AWAITING_ROW_EDIT

    except Exception as exc:
        logger.error("Error fetching record for edit: %s", exc, exc_info=True)
        await status_msg.edit_text(f"❌ Gagal memuat data: <code>{html.escape(str(exc))}</code>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END


@config.restricted
async def handle_edit_row_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process user input to update specific fields of the row."""
    message = update.effective_message
    if not message or not message.text:
        return AWAITING_ROW_EDIT

    text = message.text.strip()
    if text.lower() in ["batal", "/batal", "cancel"]:
        context.user_data.pop("editing_expense_id", None)
        context.user_data.pop("editing_expense_data", None)
        await message.reply_text("❌ Proses edit dibatalkan.")
        return ConversationHandler.END

    target_id = context.user_data.get("editing_expense_id")
    if not target_id:
        await message.reply_text("⚠️ Sesi edit telah berakhir.")
        return ConversationHandler.END

    updates = _parse_field_updates(text)
    if not updates:
        # Fallback if only single number or text given
        raw_clean = re.sub(r"[^\d]", "", text)
        if raw_clean:
            updates["nominal"] = int(raw_clean)
        else:
            updates["keterangan"] = text

    status_msg = await message.reply_text("⏳ <i>Menyimpan perubahan ke Google Sheets...</i>", parse_mode=ParseMode.HTML)

    try:
        success = sheets.update_expense(target_id, updates)
        if not success:
            await status_msg.edit_text("❌ Gagal mengupdate data. Pastikan baris masih ada di Google Sheets.")
            return ConversationHandler.END

        # Fetch updated record
        updated_rec, _ = sheets.get_expense_by_id(target_id)
        context.user_data.pop("editing_expense_id", None)
        context.user_data.pop("editing_expense_data", None)

        nominal_str = charts.format_rupiah(updated_rec.get("nominal", 0)) if updated_rec else ""
        ket_str = html.escape(str(updated_rec.get("keterangan", ""))) if updated_rec else ""

        await status_msg.edit_text(
            f"✅ <b>Transaksi ID {target_id} berhasil diupdate!</b>\n\n"
            f"• Nominal: <code>{nominal_str}</code>\n"
            f"• Keterangan: {ket_str}\n"
            f"• Kategori: {html.escape(str(updated_rec.get('kategori', '-') if updated_rec else '-'))}\n"
            f"• Tanggal: <code>{html.escape(str(updated_rec.get('tanggal', '-') if updated_rec else '-'))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    except Exception as exc:
        logger.error("Error updating row %s: %s", target_id, exc, exc_info=True)
        await status_msg.edit_text(f"❌ Terjadi kesalahan saat mengupdate: <code>{html.escape(str(exc))}</code>", parse_mode=ParseMode.HTML)
        return ConversationHandler.END


def get_edit_conversation_handler() -> ConversationHandler:
    """Build and return ConversationHandler for /edit [id]."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("edit", edit_command),
        ],
        states={
            AWAITING_ROW_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_row_input),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CommandHandler("batal", lambda u, c: ConversationHandler.END),
        ],
        name="edit_row_conversation",
        persistent=False,
        per_message=False,
    )
