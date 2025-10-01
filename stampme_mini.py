import os
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ.get("8128076326:AAHkSTU4ymvUh8epIHDScylTaS9arW-knQM")  # Bot token from Render environment
DATA_FILE = "data.json"

# Load / Save helper
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"campaigns": {}, "wallets": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to StampMe Bot MVP!\nUse /newcampaign to create one.")

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = str(update.effective_user.id)
    campaign_id = f"c{len(data['campaigns'])+1}"
    data["campaigns"][campaign_id] = {"owner": user_id, "stamps": {}}
    save_data(data)

    deep_link = f"https://t.me/{context.bot.username}?start={campaign_id}"
    await update.message.reply_text(f"✅ Campaign created!\nScan QR or click link:\n{deep_link}")

async def start_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if context.args:
        campaign_id = context.args[0]
        user_id = str(update.effective_user.id)
        if campaign_id in data["campaigns"]:
            campaign = data["campaigns"][campaign_id]
            campaign["stamps"][user_id] = campaign["stamps"].get(user_id, 0) + 1
            save_data(data)
            await update.message.reply_text(f"🎉 +1 stamp in {campaign_id}! Total: {campaign['stamps'][user_id]}")
        else:
            await update.message.reply_text("❌ Campaign not found.")
    else:
        await update.message.reply_text("Use deep link to join campaign.")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = str(update.effective_user.id)
    msg = "💳 Your Wallet:\n"
    found = False
    for cid, c in data["campaigns"].items():
        if user_id in c["stamps"]:
            msg += f"- {cid}: {c['stamps'][user_id]} stamps\n"
            found = True
    if not found:
        msg += "No stamps yet."
    await update.message.reply_text(msg)

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = str(update.effective_user.id)
    msg = "📊 Your Campaigns:\n"
    found = False
    for cid, c in data["campaigns"].items():
        if c["owner"] == user_id:
            msg += f"- {cid}: {len(c['stamps'])} customers\n"
            found = True
    if not found:
        msg += "None."
    await update.message.reply_text(msg)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_campaign))
    app.add_handler(CommandHandler("newcampaign", newcampaign))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("mycampaigns", mycampaigns))

    print("✅ Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
