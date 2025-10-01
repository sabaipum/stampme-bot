import os
from telegram.ext import Updater, CommandHandler

# Get token from environment (Render Dashboard → Environment → add key BOT_TOKEN)
BOT_TOKEN = os.getenv("BOT_TOKEN")

def start(update, context):
    update.message.reply_text("Welcome to StampMe Mini! 🎉 Use /newcampaign to begin.")

def newcampaign(update, context):
    update.message.reply_text("📌 New campaign created! Share this QR/link with your customers.")

def stamp(update, context):
    update.message.reply_text("✅ 1 stamp added!")

def wallet(update, context):
    update.message.reply_text("💳 You have X stamps (demo).")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("newcampaign", newcampaign))
    dp.add_handler(CommandHandler("stamp", stamp))
    dp.add_handler(CommandHandler("wallet", wallet))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
