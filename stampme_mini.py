import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Get your bot token from environment variable
TOKEN = os.getenv("BOT_TOKEN")  # Make sure you set BOT_TOKEN in Render

# Example command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am your StampMe bot 🤖")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /start to test the bot.")

def main():
    # Build the application
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    # Start polling
    app.run_polling()

if __name__ == "__main__":
    main()
