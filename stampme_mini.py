# stampme_mini.py
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("8128076326:AAHkSTU4ymvUh8epIHDScylTaS9arW-knQM")  # make sure BOT_TOKEN is set in Render

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello 👋 I’m your StampMe bot!")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Available commands:\n/start - Say hi\n/help - Show this help")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling()   # ✅ replaces Updater

if __name__ == "__main__":
    main()
