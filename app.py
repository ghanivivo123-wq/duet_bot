import asyncio
import logging
import threading
import gradio as gr
import main

# Setup logger
logger = logging.getLogger(__name__)

def run_telegram_bot():
    """Run main Telegram bot loop in a dedicated thread."""
    try:
        logger.info("Memulai Telegram Bot background thread di Hugging Face Space...")
        main.main()
    except Exception as e:
        logger.error("Error pada Telegram Bot thread: %s", e, exc_info=True)

# Start bot in background thread
bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()

# Minimal Gradio Web Interface for Hugging Face port 7860 healthcheck
with gr.Blocks(title="Telegram Expense Bot Status") as demo:
    gr.Markdown("# 🤖 Telegram Expense Tracker Bot")
    gr.Markdown("### Status: **Aktif & Berjalan 🟢**")
    gr.Markdown(
        "Bot Telegram pencatat pengeluaran (*QRIS & Receipt OCR*) sedang aktif melayani pesan di latar belakang.\n\n"
        "Buka aplikasi Telegram kamu untuk mulai mencatat transaksi!"
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
