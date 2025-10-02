# stampme_mini.py
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ---- Handlers ----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! Welcome to StampMe Bot.\nUse /help to see available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available commands:\n/start - Welcome message\n/help - List commands\n/ping - Test bot"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pong! 🏓")

# ---- Main ----
if __name__ == "__main__":
    TOKEN = "YOUR_BOT_TOKEN"

    # No Updater! Just use ApplicationBuilder
    app = ApplicationBuilder().token(TOKEN).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))

    print("🚀 Bot is starting...")
    app.run_polling()
