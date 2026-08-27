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
import gemini_extract
import sheets

logger = logging.getLogger(__name__)

# Conversation States
AWAITING_CAPTION = 1
AWAITING_EDIT_INPUT = 2


def _build_summary_message(data: Dict[str, Any]) -> str:
    """Format extracted/edited expense data into readable Telegram message."""
    nominal_formatted = charts.format_rupiah(data.get("nominal", 0))
    jenis_bukti = data.get("jenis_bukti", "Nota")
    tanggal = data.get("tanggal", "-")
    waktu = data.get("waktu", "")
    waktu_str = f" ({waktu})" if waktu else ""
    merchant = data.get("merchant", "") or "-"
    keterangan = data.get("keterangan", "") or "-"
    kategori = data.get("kategori", "Lain-lain")
    confidence = data.get("confidence", "medium")

    icon = "📱" if jenis_bukti == "QRIS" else "🧾"

    lines = [
        f"{icon} *Ringkasan Bukti Transaksi ({jenis_bukti})*",
        f"━━━━━━━━━━━━━━━━━━",
        f"💵 *Nominal*    : `{nominal_formatted}`",
        f"🏷 *Keterangan* : {keterangan}",
        f"📁 *Kategori*   : {kategori}",
        f"🏪 *Merchant*   : {merchant}",
        f"📅 *Tanggal*    : {tanggal}{waktu_str}",
        f"━━━━━━━━━━━━━━━━━━",
    ]

    if confidence == "low":
        lines.append("\n⚠️ _Catatan: Beberapa data mungkin kurang akurat, silakan cek dulu ya sebelum disimpan._")

    return "\n".join(lines)


def _get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Generate inline keyboard buttons for Save, Edit, Cancel."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Simpan", callback_data="confirm_save_expense"),
            InlineKeyboardButton("✏️ Edit", callback_data="confirm_edit_expense"),
            InlineKeyboardButton("❌ Batal", callback_data="confirm_cancel_expense"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


@config.restricted
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Step 1: Receive photo from user.
    If caption exists -> run Gemini OCR directly.
    If no caption -> ask 'Beli apa nih?' and wait for caption.
    """
    message = update.effective_message
    if not message or not message.photo:
        return ConversationHandler.END

    # Get largest available photo
    photo = message.photo[-1]
    file_id = photo.file_id
    caption = (message.caption or "").strip()

    # Save photo file_id to user_data
    context.user_data["photo_file_id"] = file_id

    if not caption:
        # Ask user for description
        await message.reply_text(
            "📷 Foto bukti pembayaran diterima!\n\n*Beli apa nih?* (Ketik keterangan singkat belanjaan kamu)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return AWAITING_CAPTION

    # Caption is present, proceed directly to extraction
    return await _process_and_extract(update, context, file_id, caption)


@config.restricted
async def handle_caption_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Step 2: Receive caption when user replies to 'Beli apa nih?'.
    """
    message = update.effective_message
    if not message or not message.text:
        return AWAITING_CAPTION

    caption = message.text.strip()
    file_id = context.user_data.get("photo_file_id")

    if not file_id:
        await message.reply_text("❌ Sesi foto telah berakhir. Silakan kirim ulang foto bukti transaksi.")
        return ConversationHandler.END

    return await _process_and_extract(update, context, file_id, caption)


async def _process_and_extract(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    caption: str,
) -> int:
    """Download photo, call Gemini API, and display confirmation message."""
    message = update.effective_message
    chat_id = update.effective_chat.id

    processing_msg = await message.reply_text("⏳ _Membaca bukti transaksi dengan Gemini..._", parse_mode=ParseMode.MARKDOWN)

    try:
        # Download photo bytes
        bot = context.bot
        tg_file = await bot.get_file(file_id)
        photo_bytes = await tg_file.download_as_bytearray()

        # Call Gemini extraction
        result = gemini_extract.extract_expense_from_image(
            image_bytes=bytes(photo_bytes),
            mime_type="image/jpeg",
            user_caption=caption,
        )

        if not result["success"] or not result["data"]:
            err_text = result.get("error") or "Gagal membaca teks dari gambar."
            logger.warning("Gemini extraction error: %s", err_text)
            await processing_msg.edit_text(
                f"⚠️ *Gagal mengekstrak data otomatis.*\n\n"
                f"Detail: `{err_text}`\n\n"
                f"Silakan coba kirim foto yang lebih jelas atau pencatatan dibatalkan.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

        data = result["data"]
        data["sumber_foto"] = file_id

        # Store in user_data
        context.user_data["current_expense_draft"] = data

        # Render summary
        summary_text = _build_summary_message(data)
        keyboard = _get_confirmation_keyboard()

        await processing_msg.edit_text(
            summary_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    except Exception as exc:
        logger.error("Error saat memproses foto transaksi: %s", exc, exc_info=True)
        await processing_msg.edit_text(
            f"❌ Terjadi kesalahan saat memproses gambar: `{exc}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END


@config.restricted
async def callback_save_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback when user clicks '✅ Simpan'."""
    query = update.callback_query
    await query.answer()

    draft = context.user_data.get("current_expense_draft")
    if not draft:
        await query.edit_message_text("⚠️ Data transaksi tidak ditemukan atau sudah tersimpan/batal.")
        return

    try:
        saved_record = sheets.add_expense(draft)
        nominal_formatted = charts.format_rupiah(saved_record.get("nominal", 0))
        keterangan = saved_record.get("keterangan", "")
        jenis = saved_record.get("jenis_bukti", "Nota")
        tanggal = saved_record.get("tanggal", "")
        exp_id = saved_record.get("id", "-")

        # Clear draft
        context.user_data.pop("current_expense_draft", None)
        context.user_data.pop("photo_file_id", None)

        confirmation_text = (
            f"✅ *Tercatat:* `{nominal_formatted}` — *{keterangan}*\n"
            f"📌 ID: `{exp_id}` | _{jenis}_ | 📅 `{tanggal}`\n"
            f"💾 Data berhasil disimpan ke Google Sheets."
        )

        await query.edit_message_text(confirmation_text, parse_mode=ParseMode.MARKDOWN)

    except Exception as exc:
        logger.error("Gagal menyimpan ke Google Sheets: %s", exc, exc_info=True)
        await query.edit_message_text(
            f"❌ Gagal menyimpan ke Google Sheets: `{exc}`\nCoba periksa koneksi atau izin Service Account.",
            parse_mode=ParseMode.MARKDOWN,
        )


@config.restricted
async def callback_cancel_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback when user clicks '❌ Batal'."""
    query = update.callback_query
    await query.answer()

    context.user_data.pop("current_expense_draft", None)
    context.user_data.pop("photo_file_id", None)

    await query.edit_message_text("❌ Pencatatan transaksi dibatalkan.")
    return ConversationHandler.END


@config.restricted
async def callback_start_edit_draft(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback when user clicks '✏️ Edit' on draft."""
    query = update.callback_query
    await query.answer()

    draft = context.user_data.get("current_expense_draft")
    if not draft:
        await query.edit_message_text("⚠️ Data transaksi tidak ditemukan atau sudah kadaluarsa.")
        return ConversationHandler.END

    instruction_text = (
        "✏️ *Edit Data Transaksi*\n\n"
        "Kirim field yang ingin diubah dalam format bebas, contoh:\n"
        "• `nominal: 35000`\n"
        "• `kategori: Makanan & Minuman`\n"
        "• `keterangan: Beli bakso super`\n"
        "• `merchant: Bakso Pak Kumis`\n"
        "• `tanggal: 2026-08-27`\n"
        "• `waktu: 13:00`\n"
        "• `jenis_bukti: QRIS`\n\n"
        "_(Bisa ketik beberapa field sekaligus per baris. Ketik `batal` untuk membatalkan edit.)_"
    )

    await query.message.reply_text(instruction_text, parse_mode=ParseMode.MARKDOWN)
    return AWAITING_EDIT_INPUT


@config.restricted
async def handle_edit_draft_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input for editing the current draft."""
    message = update.effective_message
    if not message or not message.text:
        return AWAITING_EDIT_INPUT

    text = message.text.strip()
    if text.lower() in ["batal", "/batal", "cancel"]:
        await message.reply_text("Penyuntingan dibatalkan.")
        draft = context.user_data.get("current_expense_draft")
        if draft:
            summary_text = _build_summary_message(draft)
            keyboard = _get_confirmation_keyboard()
            await message.reply_text(summary_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    draft = context.user_data.get("current_expense_draft")
    if not draft:
        await message.reply_text("⚠️ Sesi transaksi tidak ditemukan. Silakan kirim ulang foto.")
        return ConversationHandler.END

    # Parse key-value lines
    updates = _parse_field_updates(text)

    if not updates:
        # If user just sent a number, treat as nominal
        raw_clean = re.sub(r"[^\d]", "", text)
        if raw_clean:
            updates["nominal"] = int(raw_clean)
        else:
            # Treat as description
            updates["keterangan"] = text

    # Apply updates to draft
    for key, val in updates.items():
        if key == "nominal":
            try:
                num_val = float(str(val).replace(".", "").replace(",", ".").replace("Rp", "").strip())
                if num_val.is_integer():
                    num_val = int(num_val)
                draft["nominal"] = num_val
            except ValueError:
                pass
        elif key == "jenis_bukti":
            val_str = str(val).upper()
            draft["jenis_bukti"] = "QRIS" if "QRIS" in val_str else "Nota"
        elif key in draft:
            draft[key] = val

    context.user_data["current_expense_draft"] = draft

    # Re-display updated summary
    summary_text = "🔄 *Data Telah Diperbarui:*\n\n" + _build_summary_message(draft)
    keyboard = _get_confirmation_keyboard()

    await message.reply_text(summary_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


def _parse_field_updates(text: str) -> Dict[str, Any]:
    """Parse text containing 'field: value' lines."""
    updates = {}
    lines = text.split("\n")
    aliases = {
        "nominal": "nominal",
        "harga": "nominal",
        "total": "nominal",
        "biaya": "nominal",
        "keterangan": "keterangan",
        "ket": "keterangan",
        "deskripsi": "keterangan",
        "kategori": "kategori",
        "kat": "kategori",
        "merchant": "merchant",
        "toko": "merchant",
        "penjual": "merchant",
        "tanggal": "tanggal",
        "tgl": "tanggal",
        "waktu": "waktu",
        "jam": "waktu",
        "jenis": "jenis_bukti",
        "jenis_bukti": "jenis_bukti",
        "bukti": "jenis_bukti",
    }

    for line in lines:
        line = line.strip()
        if ":" in line:
            parts = line.split(":", 1)
            raw_key = parts[0].strip().lower()
            val = parts[1].strip()
            if raw_key in aliases:
                target_key = aliases[raw_key]
                updates[target_key] = val
        elif "=" in line:
            parts = line.split("=", 1)
            raw_key = parts[0].strip().lower()
            val = parts[1].strip()
            if raw_key in aliases:
                target_key = aliases[raw_key]
                updates[target_key] = val

    return updates


@config.restricted
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel in conversation."""
    await update.effective_message.reply_text("Aksi dibatalkan.")
    return ConversationHandler.END


def get_photo_conversation_handler() -> ConversationHandler:
    """Build and return the ConversationHandler for photo flows."""
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO, handle_photo),
            CallbackQueryHandler(callback_start_edit_draft, pattern="^confirm_edit_expense$"),
        ],
        states={
            AWAITING_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_caption_reply),
            ],
            AWAITING_EDIT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_draft_input),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("batal", cancel_conversation),
            CallbackQueryHandler(callback_cancel_expense, pattern="^confirm_cancel_expense$"),
        ],
        name="photo_conversation",
        persistent=False,
    )
