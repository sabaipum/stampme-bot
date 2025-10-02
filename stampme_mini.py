import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Get the bot token from environment variable
TOKEN = os.getenv(8128076326:AAHkSTU4ymvUh8epIHDScylTaS9arW-knQM)

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

# Example command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am your StampMe Mini Bot 🤖")

def main():
    # Build the application
    app = ApplicationBuilder().token(TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))

    # Run the bot
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
