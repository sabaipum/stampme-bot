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
BOT_USERNAME = os.getenv("BOT_USERNAME", "stampmebot")  # Set this in Render env vars

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
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ *Usage:* `/getqr <campaign_id>`\n\n"
            "*Example:* `/getqr 1`\n\n"
            "Use /mycampaigns to see your campaign IDs.",
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        
        if campaign_id not in campaigns:
            await update.message.reply_text(
                "❌ Campaign not found!\n\n"
                "Use /mycampaigns to see your campaigns."
            )
            return
        
        campaign = campaigns[campaign_id]
        merchant_id = update.effective_user.id
        
        # Verify merchant owns this campaign
        if campaign["merchant_id"] != merchant_id:
            await update.message.reply_text("❌ You don't own this campaign.")
            return
        
        # Send "generating" message
        status_msg = await update.message.reply_text("🔄 Generating QR code...")
        
        # Generate QR code
        qr_link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_link)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to bytes
        bio = io.BytesIO()
        bio.name = f'qr_campaign_{campaign_id}.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        
        # Delete status message
        await status_msg.delete()
        
        # Send QR code
        await update.message.reply_photo(
            photo=bio,
            caption=f"📱 *QR Code for: {campaign['name']}*\n\n"
                    f"🎯 Stamps needed: {campaign['stamps_needed']}\n"
                    f"👥 Customers: {len(campaign['customers'])}\n\n"
                    f"📋 *Instructions:*\n"
                    f"• Print this QR code\n"
                    f"• Display it at your store\n"
                    f"• Customers scan to join!\n\n"
                    f"🔗 Direct link:\n`{qr_link}`",
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text(
            "❌ Campaign ID must be a number!\n\n"
            "*Example:* `/getqr 1`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error generating QR code: {str(e)}")

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List merchant's campaigns"""
    merchant_id = update.effective_user.id
    
    if merchant_id not in merchant_campaigns or not merchant_campaigns[merchant_id]:
        await update.message.reply_text(
            "📭 *You haven't created any campaigns yet!*\n\n"
            "🎯 *Get started:*\n"
            "Use `/newcampaign <n> <stamps>` to create your first campaign!\n\n"
            "*Example:* `/newcampaign Coffee 5`",
            parse_mode="Markdown"
        )
        return
    
    message = "📊 *Your Campaigns:*\n\n"
    
    for idx, campaign_id in enumerate(merchant_campaigns[merchant_id], 1):
        if campaign_id not in campaigns:
            continue
            
        campaign = campaigns[campaign_id]
        customer_count = len(campaign["customers"])
        completed_count = sum(1 for c in campaign["customers"].values() 
                            if c["stamps"] >= campaign["stamps_needed"])
        
        message += f"*{idx}. {campaign['name']}*\n"
        message += f"   🆔 ID: `{campaign_id}`\n"
        message += f"   🎯 Stamps: {campaign['stamps_needed']}\n"
        message += f"   👥 Customers: {customer_count}\n"
        message += f"   ✅ Completed: {completed_count}\n"
        message += f"   📱 Get QR: `/getqr {campaign_id}`\n"
        message += f"   ⭐ Stamp: `/stamp {campaign_id}`\n"
        message += "   ─────────────\n"
    
    message += "\n💡 *Tip:* Tap any command to use it!"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def stamp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add stamp to customer - shows customer list"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ *Usage:* `/stamp <campaign_id>`\n\n"
            "*Example:* `/stamp 1`\n\n"
            "This will show you a list of customers to stamp.\n"
            "Use /mycampaigns to see your campaign IDs.",
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        
        if campaign_id not in campaigns:
            await update.message.reply_text(
                "❌ Campaign not found!\n\n"
                "Use /mycampaigns to see your campaigns."
            )
            return
        
        campaign = campaigns[campaign_id]
        merchant_id = update.effective_user.id
        
        if campaign["merchant_id"] != merchant_id:
            await update.message.reply_text("❌ You don't own this campaign.")
            return
        
        if not campaign["customers"]:
            await update.message.reply_text(
                f"📭 *No customers yet for '{campaign['name']}'*\n\n"
                f"Share your QR code to get customers!\n"
                f"Use `/getqr {campaign_id}` to get the QR code.",
                parse_mode="Markdown"
            )
            return
        
        # Create inline keyboard with customer list
        keyboard = []
        for user_id, customer_data in campaign["customers"].items():
            username = customer_data["username"]
            stamps = customer_data["stamps"]
            needed = campaign["stamps_needed"]
            
            # Add status emoji
            if stamps >= needed:
                status = "✅"
            else:
                status = "⭐"
            
            button_text = f"{status} {username} ({stamps}/{needed})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"stamp_{campaign_id}_{user_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👥 *Select customer to add stamp:*\n\n"
            f"📋 Campaign: *{campaign['name']}*\n"
            f"🎯 Stamps needed: {campaign['stamps_needed']}\n\n"
            f"Tap a customer below to give them a stamp:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text(
            "❌ Campaign ID must be a number!\n\n"
            "*Example:* `/stamp 1`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks for stamping"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("stamp_"):
        parts = data.split("_")
        campaign_id = int(parts[1])
        customer_id = int(parts[2])
        
        if campaign_id not in campaigns:
            await query.edit_message_text("❌ Campaign no longer exists.")
            return
        
        campaign = campaigns[campaign_id]
        
        if customer_id not in campaign["customers"]:
            await query.edit_message_text("❌ Customer not found in this campaign.")
            return
        
        customer_data = campaign["customers"][customer_id]
        
        # Add stamp
        customer_data["stamps"] += 1
        current_stamps = customer_data["stamps"]
        stamps_needed = campaign["stamps_needed"]
        
        # Create progress bar
        progress = "⭐" * min(current_stamps, stamps_needed) + "☆" * max(0, stamps_needed - current_stamps)
        
        # Check if completed
        if current_stamps >= stamps_needed:
            await query.edit_message_text(
                f"🎉 *STAMP ADDED - REWARD EARNED!*\n\n"
                f"👤 Customer: {customer_data['username']}\n"
                f"📋 Campaign: {campaign['name']}\n"
                f"{progress}\n"
                f"Progress: {current_stamps}/{stamps_needed}\n\n"
                f"✅ *This customer has completed the campaign!*\n"
                f"🎁 They can now claim their reward!",
                parse_mode="Markdown"
            )
            
            # Notify customer of completion
            try:
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=f"🎉 *CONGRATULATIONS!*\n\n"
                         f"You've completed the *{campaign['name']}* campaign!\n\n"
                         f"{progress}\n"
                         f"✅ {current_stamps}/{stamps_needed} stamps collected\n\n"
                         f"🎁 *Show this message at the store to claim your reward!*\n\n"
                         f"Keep using /wallet to track your progress!",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Failed to notify customer: {e}")
        else:
            await query.edit_message_text(
                f"✅ *STAMP ADDED SUCCESSFULLY!*\n\n"
                f"👤 Customer: {customer_data['username']}\n"
                f"📋 Campaign: {campaign['name']}\n"
                f"{progress}\n"
                f"Progress: {current_stamps}/{stamps_needed}\n\n"
                f"💪 Keep going! Only {stamps_needed - current_stamps} more to go!",
                parse_mode="Markdown"
            )
            
            # Notify customer of new stamp
            try:
                remaining = stamps_needed - current_stamps
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=f"⭐ *NEW STAMP RECEIVED!*\n\n"
                         f"📋 Campaign: *{campaign['name']}*\n"
                         f"{progress}\n"
                         f"Progress: {current_stamps}/{stamps_needed}\n\n"
                         f"🎯 Only {remaining} more stamp{'s' if remaining != 1 else ''} to earn your reward!\n\n"
                         f"Use /wallet to see all your cards.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Failed to notify customer: {e}")

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
            "📭 *You don't have any stamp cards yet!*\n\n"
            "🎯 *How to get started:*\n"
            "1. Visit a participating store\n"
            "2. Scan their QR code\n"
            "3. Start collecting stamps!\n\n"
            "✨ Earn rewards with every purchase!",
            parse_mode="Markdown"
        )
        return
    
    message = "💳 *Your Stamp Cards:*\n\n"
    
    for campaign_id, campaign in user_campaigns:
        customer_data = campaign["customers"][user_id]
        stamps = customer_data["stamps"]
        needed = campaign["stamps_needed"]
        
        # Create progress bar with emojis
        filled = min(stamps, needed)
        progress = "⭐" * filled + "☆" * (needed - filled)
        
        # Determine status
        if stamps >= needed:
            status_text = "✅ *COMPLETED!* Claim your reward! 🎁"
            card_emoji = "🎉"
        else:
            percentage = int((stamps / needed) * 100)
            status_text = f"📊 Progress: {stamps}/{needed} ({percentage}%)"
            card_emoji = "📋"
        
        message += f"{card_emoji} *{campaign['name']}*\n"
        message += f"{progress}\n"
        message += f"{status_text}\n"
        message += "─────────────\n"
    
    message += "\n💡 *Keep scanning to earn more rewards!*"
    
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
