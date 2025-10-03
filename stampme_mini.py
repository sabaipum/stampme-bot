import os
import asyncio
import io
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import qrcode

# Configuration
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")  # Set this in Render env vars

# In-memory storage (use database in production)
campaigns = {}  # {campaign_id: {"name": str, "stamps_needed": int, "merchant_id": int, "customers": {user_id: stamps}}}
campaign_counter = 0
merchant_campaigns = {}  # {merchant_id: [campaign_ids]}

# Health check endpoint
async def health_check(request):
    return web.Response(text="StampMe Bot is running! 🎉")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/healthz', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"✅ Health check server started on port {PORT}")

# ==================== COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command and deep links for joining campaigns"""
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    # Check if this is a deep link (QR code scan)
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        
        # Handle campaign join via QR code
        if arg.startswith("join_"):
            campaign_id = int(arg.split("_")[1])
            
            if campaign_id not in campaigns:
                await update.message.reply_text("❌ Campaign not found.")
                return
            
            campaign = campaigns[campaign_id]
            
            # Add customer to campaign
            if user_id not in campaign["customers"]:
                campaign["customers"][user_id] = {
                    "stamps": 0,
                    "username": username
                }
                await update.message.reply_text(
                    f"👋 Welcome! You've joined **{campaign['name']}** campaign!\n\n"
                    f"🎯 Collect {campaign['stamps_needed']} stamps to earn your reward.\n"
                    f"📊 Current progress: 0/{campaign['stamps_needed']}\n\n"
                    f"Use /wallet to check your stamps anytime!",
                    parse_mode="Markdown"
                )
            else:
                current_stamps = campaign["customers"][user_id]["stamps"]
                await update.message.reply_text(
                    f"Welcome back to **{campaign['name']}**!\n\n"
                    f"📊 Your progress: {current_stamps}/{campaign['stamps_needed']} stamps",
                    parse_mode="Markdown"
                )
            return
    
    # Normal start message
    await update.message.reply_text(
        "🎉 **Welcome to StampMe Bot!**\n\n"
        "**For Customers:**\n"
        "• Scan QR codes at participating stores\n"
        "• Use /wallet to check your stamps\n\n"
        "**For Merchants:**\n"
        "• /newcampaign <name> <stamps> - Create campaign\n"
        "• /mycampaigns - View your campaigns\n"
        "• /getqr <campaign_id> - Get QR code\n"
        "• /stamp <campaign_id> - Add stamps\n"
        "• /help - See all commands",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help information"""
    await update.message.reply_text(
        "📖 **StampMe Bot Commands**\n\n"
        "**Customer Commands:**\n"
        "• /wallet - View your stamp cards\n"
        "• /start - Start the bot\n\n"
        "**Merchant Commands:**\n"
        "• /newcampaign <name> <stamps> - Create new campaign\n"
        "  Example: `/newcampaign Coffee 5`\n"
        "• /mycampaigns - List your campaigns\n"
        "• /getqr <campaign_id> - Generate QR code\n"
        "• /stamp <campaign_id> - Add stamp to customer\n"
        "• /campaign <campaign_id> - View campaign details\n\n"
        "Need help? Contact support!",
        parse_mode="Markdown"
    )

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new stamp campaign"""
    global campaign_counter
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/newcampaign <name> <stamps_needed>`\n"
            "Example: `/newcampaign Coffee 5`",
            parse_mode="Markdown"
        )
        return
    
    try:
        stamps_needed = int(context.args[-1])
        campaign_name = " ".join(context.args[:-1])
        
        if stamps_needed < 1 or stamps_needed > 20:
            await update.message.reply_text("❌ Stamps needed must be between 1 and 20.")
            return
        
        merchant_id = update.effective_user.id
        campaign_counter += 1
        campaign_id = campaign_counter
        
        # Create campaign
        campaigns[campaign_id] = {
            "name": campaign_name,
            "stamps_needed": stamps_needed,
            "merchant_id": merchant_id,
            "customers": {}
        }
        
        # Track merchant campaigns
        if merchant_id not in merchant_campaigns:
            merchant_campaigns[merchant_id] = []
        merchant_campaigns[merchant_id].append(campaign_id)
        
        await update.message.reply_text(
            f"✅ **Campaign Created!**\n\n"
            f"📋 Name: {campaign_name}\n"
            f"🎯 Stamps needed: {stamps_needed}\n"
            f"🆔 Campaign ID: {campaign_id}\n\n"
            f"Use `/getqr {campaign_id}` to generate your QR code!",
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Last argument must be a number (stamps needed).")

async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate QR code for a campaign"""
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/getqr <campaign_id>`", parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        
        if campaign_id not in campaigns:
            await update.message.reply_text("❌ Campaign not found.")
            return
        
        campaign = campaigns[campaign_id]
        merchant_id = update.effective_user.id
        
        # Verify merchant owns this campaign
        if campaign["merchant_id"] != merchant_id:
            await update.message.reply_text("❌ You don't own this campaign.")
            return
        
        # Generate QR code
        qr_link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qr_link)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to bytes
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        await update.message.reply_photo(
            photo=bio,
            caption=f"📱 **QR Code for {campaign['name']}**\n\n"
                    f"Customers scan this to join!\n"
                    f"Link: `{qr_link}`",
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Campaign ID must be a number.")

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List merchant's campaigns"""
    merchant_id = update.effective_user.id
    
    if merchant_id not in merchant_campaigns or not merchant_campaigns[merchant_id]:
        await update.message.reply_text("📭 You haven't created any campaigns yet.\n\nUse /newcampaign to create one!")
        return
    
    message = "📊 **Your Campaigns:**\n\n"
    
    for campaign_id in merchant_campaigns[merchant_id]:
        campaign = campaigns[campaign_id]
        customer_count = len(campaign["customers"])
        message += f"🆔 ID: {campaign_id}\n"
        message += f"📋 Name: {campaign['name']}\n"
        message += f"🎯 Stamps: {campaign['stamps_needed']}\n"
        message += f"👥 Customers: {customer_count}\n"
        message += "─────────────\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def stamp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add stamp to customer - shows customer list"""
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/stamp <campaign_id>`", parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        
        if campaign_id not in campaigns:
            await update.message.reply_text("❌ Campaign not found.")
            return
        
        campaign = campaigns[campaign_id]
        merchant_id = update.effective_user.id
        
        if campaign["merchant_id"] != merchant_id:
            await update.message.reply_text("❌ You don't own this campaign.")
            return
        
        if not campaign["customers"]:
            await update.message.reply_text("📭 No customers have joined this campaign yet.")
            return
        
        # Create inline keyboard with customer list
        keyboard = []
        for user_id, customer_data in campaign["customers"].items():
            username = customer_data["username"]
            stamps = customer_data["stamps"]
            button_text = f"{username} ({stamps}/{campaign['stamps_needed']})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"stamp_{campaign_id}_{user_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👥 **Select customer to stamp:**\n\nCampaign: {campaign['name']}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Campaign ID must be a number.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("stamp_"):
        parts = data.split("_")
        campaign_id = int(parts[1])
        customer_id = int(parts[2])
        
        campaign = campaigns[campaign_id]
        customer_data = campaign["customers"][customer_id]
        
        # Add stamp
        customer_data["stamps"] += 1
        current_stamps = customer_data["stamps"]
        stamps_needed = campaign["stamps_needed"]
        
        # Check if completed
        if current_stamps >= stamps_needed:
            await query.edit_message_text(
                f"🎉 **Stamp Added!**\n\n"
                f"Customer: {customer_data['username']}\n"
                f"Progress: {current_stamps}/{stamps_needed}\n\n"
                f"✅ **REWARD EARNED!** This customer completed the campaign!",
                parse_mode="Markdown"
            )
            
            # Notify customer
            try:
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=f"🎉 **Congratulations!**\n\n"
                         f"You've completed the **{campaign['name']}** campaign!\n"
                         f"Show this message to claim your reward! 🎁",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            await query.edit_message_text(
                f"✅ **Stamp Added!**\n\n"
                f"Customer: {customer_data['username']}\n"
                f"Progress: {current_stamps}/{stamps_needed}\n\n"
                f"Keep going! 💪",
                parse_mode="Markdown"
            )
            
            # Notify customer
            try:
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=f"⭐ **New Stamp!**\n\n"
                         f"Campaign: {campaign['name']}\n"
                         f"Progress: {current_stamps}/{stamps_needed}",
                    parse_mode="Markdown"
                )
            except:
                pass

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show customer's stamp cards"""
    user_id = update.effective_user.id
    
    # Find all campaigns user is in
    user_campaigns = []
    for campaign_id, campaign in campaigns.items():
        if user_id in campaign["customers"]:
            user_campaigns.append((campaign_id, campaign))
    
    if not user_campaigns:
        await update.message.reply_text(
            "📭 You don't have any stamp cards yet.\n\n"
            "Scan a QR code at a participating store to get started!"
        )
        return
    
    message = "💳 **Your Stamp Cards:**\n\n"
    
    for campaign_id, campaign in user_campaigns:
        customer_data = campaign["customers"][user_id]
        stamps = customer_data["stamps"]
        needed = campaign["stamps_needed"]
        
        # Create progress bar
        progress = "⭐" * stamps + "☆" * (needed - stamps)
        
        status = "✅ COMPLETED!" if stamps >= needed else f"{stamps}/{needed}"
        
        message += f"📋 **{campaign['name']}**\n"
        message += f"{progress}\n"
        message += f"Status: {status}\n"
        message += "─────────────\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def campaign_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View campaign details"""
    if len(context.args) != 1:
        await update.message.reply_text("❌ Usage: `/campaign <campaign_id>`", parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        
        if campaign_id not in campaigns:
            await update.message.reply_text("❌ Campaign not found.")
            return
        
        campaign = campaigns[campaign_id]
        merchant_id = update.effective_user.id
        
        if campaign["merchant_id"] != merchant_id:
            await update.message.reply_text("❌ You don't own this campaign.")
            return
        
        message = f"📊 **Campaign Details**\n\n"
        message += f"🆔 ID: {campaign_id}\n"
        message += f"📋 Name: {campaign['name']}\n"
        message += f"🎯 Stamps needed: {campaign['stamps_needed']}\n"
        message += f"👥 Total customers: {len(campaign['customers'])}\n\n"
        
        if campaign["customers"]:
            message += "**Customers:**\n"
            for user_id, customer_data in campaign["customers"].items():
                username = customer_data["username"]
                stamps = customer_data["stamps"]
                status = "✅" if stamps >= campaign['stamps_needed'] else f"{stamps}/{campaign['stamps_needed']}"
                message += f"• {username}: {status}\n"
        
        await update.message.reply_text(message, parse_mode="Markdown")
        
    except ValueError:
        await update.message.reply_text("❌ Campaign ID must be a number.")

# ==================== MAIN ====================

async def main():
    """Start the bot"""
    print("🚀 Starting StampMe Bot...")
    
    # Start health check server
    await start_web_server()
    
    # Build telegram application
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("newcampaign", newcampaign))
    app.add_handler(CommandHandler("getqr", getqr))
    app.add_handler(CommandHandler("mycampaigns", mycampaigns))
    app.add_handler(CommandHandler("stamp", stamp_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("campaign", campaign_details))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Initialize and start
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    print("✅ Bot is running!")
    print(f"📱 Bot username: @{BOT_USERNAME}")
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
