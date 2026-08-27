import logging
import sys
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import config
import sheets
from handlers.edit_handler import (
    callback_cancel_delete_last,
    callback_confirm_delete_last,
    get_edit_conversation_handler,
    hapus_terakhir_command,
)
from handlers.photo_handler import (
    callback_cancel_expense,
    callback_save_expense,
    get_photo_conversation_handler,
)
from handlers.report_handler import (
    kategori_command,
    laporan_command,
    start_command,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a friendly notification if possible."""
    logger.error("Exception saat menangani update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Terjadi kesalahan internal pada bot. Silakan coba beberapa saat lagi."
            )
        except Exception:
            pass


def main() -> None:
    """Main application entry point."""
    logger.info("=== Memulai QRIS & Receipt Expense Tracker Bot ===")

    # 1. Validasi konfigurasi
    if not config.validate_config():
        logger.critical("Bot gagal dijalankan karena konfigurasi belum lengkap. Periksa file .env.")
        sys.exit(1)

    # 2. Inisialisasi Google Sheet
    logger.info("Memeriksa koneksi Google Sheets...")
    sheet_ok = sheets.init_sheet()
    if not sheet_ok:
        logger.warning(
            "Tidak dapat memverifikasi koneksi Google Sheets saat startup. "
            "Bot akan tetap berjalan, tetapi pastikan Service Account memiliki akses 'Editor' ke Spreadsheet."
        )

    # 3. Bangun Telegram Application
    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # 4. Registrasi Handlers
    # Conversation Handlers (diurutkan di atas pesan biasa)
    application.add_handler(get_photo_conversation_handler())
    application.add_handler(get_edit_conversation_handler())

    # Command Handlers
    application.add_handler(CommandHandler(["start", "help"], start_command))
    application.add_handler(CommandHandler("laporan", laporan_command))
    application.add_handler(CommandHandler("kategori", kategori_command))
    application.add_handler(CommandHandler("hapus_terakhir", hapus_terakhir_command))

    # Callback Query Handlers
    application.add_handler(CallbackQueryHandler(callback_save_expense, pattern="^confirm_save_expense$"))
    application.add_handler(CallbackQueryHandler(callback_cancel_expense, pattern="^confirm_cancel_expense$"))
    application.add_handler(CallbackQueryHandler(callback_confirm_delete_last, pattern=r"^confirm_delete_last_\d+$"))
    application.add_handler(CallbackQueryHandler(callback_cancel_delete_last, pattern="^cancel_delete_last$"))

    # Error handler
    application.add_error_handler(error_handler)

    # 5. Jalankan Long Polling
    logger.info(
        "Bot aktif dengan Long Polling. Whitelist Chat ID: %s. Menunggu pesan...",
        config.ALLOWED_CHAT_ID,
    )
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
