import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Make sure you have set BOT_TOKEN in your environment variables
TOKEN = os.getenv("BOT_TOKEN")

# Example in-memory storage for stamps (replace with database for real app)
user_stamps = {}  # {user_id: stamp_count}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    await update.message.reply_text(
        "Welcome to StampMe! Use /stamp to collect a stamp and /status to check your stamps."
    )

async def stamp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect a stamp"""
    user_id = update.effective_user.id
    if user_id not in user_stamps:
        user_stamps[user_id] = 0
    user_stamps[user_id] += 1
    await update.message.reply_text(f"You collected a stamp! Total stamps: {user_stamps[user_id]}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check stamp status"""
    user_id = update.effective_user.id
    stamps = user_stamps.get(user_id, 0)
    await update.message.reply_text(f"You have {stamps} stamps.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset stamps (admin only)"""
    user_id = update.effective_user.id
    if user_id == 123456789:  # replace with your Telegram user ID
        user_stamps.clear()
        await update.message.reply_text("All stamps have been reset!")
    else:
        await update.message.reply_text("You are not authorized to reset stamps.")

def main():
    # Build the bot application
    app = ApplicationBuilder().token(TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stamp", stamp))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset", reset))

    # Start polling
    app.run_polling()

if __name__ == "__main__":
    main()
