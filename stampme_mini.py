import os
import asyncio
import io
import random
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import qrcode
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database_complete import StampMeDatabase

# Configuration
TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "stampmebot")
PORT = int(os.getenv("PORT", 10000))
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

# Brand Footer
BRAND_FOOTER = "\n\n💙 _Powered by StampMe_"

# Merchant Tips
MERCHANT_TIPS = [
    "Post your QR code near the counter to boost engagement!",
    "Respond to stamp requests quickly to keep customers happy.",
    "Add multiple reward tiers to encourage repeat visits.",
    "Share your referral link on social media!",
    "Consider running a limited-time bonus stamp promotion!",
]

# Initialize
db = StampMeDatabase(DATABASE_URL)
scheduler = AsyncIOScheduler()

# ==================== UTILITY FUNCTIONS ====================

def generate_progress_bar(current: int, total: int, length: int = 10) -> str:
    filled = int((current / total) * length) if total > 0 else 0
    return "█" * filled + "░" * (length - filled)

def generate_card_image(campaign_name: str, current_stamps: int, needed_stamps: int):
    width, height = 800, 400
    img = Image.new('RGB', (width, height), color='#6366f1')
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except:
        title_font = text_font = ImageFont.load_default()
    
    draw.text((40, 30), campaign_name[:30], fill='white', font=title_font)
    
    stamp_size = 55
    spacing = 18
    start_x = 40
    start_y = 120
    cols = min(5, needed_stamps)
    
    for i in range(min(needed_stamps, 20)):  # Max 20 stamps on card
        row = i // cols
        col = i % cols
        x = start_x + col * (stamp_size + spacing)
        y = start_y + row * (stamp_size + spacing)
        
        if i < current_stamps:
            draw.ellipse([x, y, x + stamp_size, y + stamp_size], fill='#fbbf24', outline='white', width=3)
            draw.text((x + 17, y + 12), "★", fill='white', font=text_font)
        else:
            draw.ellipse([x, y, x + stamp_size, y + stamp_size], fill='none', outline='white', width=2)
    
    progress_text = f"{current_stamps} / {needed_stamps} stamps"
    draw.text((40, height - 70), progress_text, fill='white', font=text_font)
    
    return img

async def health_check(request):
    return web.Response(text="StampMe Bot Running! 💙")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/healthz', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"✅ Health server running on port {PORT}")

# ==================== COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db.create_or_update_user(user_id, username, first_name)
    user = await db.get_user(user_id)
    
    # Handle deep links
    if context.args:
        arg = context.args[0]
        
        if arg.startswith("join_"):
            try:
                campaign_id = int(arg.split("_")[1])
                campaign = await db.get_campaign(campaign_id)
                
                if not campaign or not campaign['active']:
                    await update.message.reply_text("Sorry, this campaign is no longer available." + BRAND_FOOTER, parse_mode="Markdown")
                    return
                
                enrollment = await db.get_enrollment(campaign_id, user_id)
                
                if not enrollment:
                    await db.enroll_customer(campaign_id, user_id)
                    keyboard = [[InlineKeyboardButton("Request Stamp", callback_data=f"request_{campaign_id}")]]
                    
                    await update.message.reply_text(
                        f"🎉 *Welcome!*\n\nYou've joined: *{campaign['name']}*\n\nCollect {campaign['stamps_needed']} stamps to earn rewards!\n\n👉 Request your first stamp below!" + BRAND_FOOTER,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                else:
                    progress_bar = generate_progress_bar(enrollment['stamps'], campaign['stamps_needed'])
                    keyboard = [[InlineKeyboardButton("Request Stamp", callback_data=f"request_{campaign_id}")]]
                    
                    await update.message.reply_text(
                        f"👋 *Welcome back!*\n\nCampaign: *{campaign['name']}*\n{progress_bar}\nProgress: {enrollment['stamps']}/{campaign['stamps_needed']}\n\nReady for another visit?" + BRAND_FOOTER,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                return
            except Exception as e:
                print(f"Error joining campaign: {e}")
                return
    
    # Regular start
    if user and user['user_type'] == 'merchant':
        if user['merchant_approved']:
            keyboard = [
                [InlineKeyboardButton("📊 Dashboard", callback_data="merchant_dashboard")],
                [InlineKeyboardButton("⏳ Pending Requests", callback_data="show_pending")]
            ]
            
            pending_count = await db.get_pending_count(user_id)
            message = f"👋 Hi {first_name}!\n\nWelcome back to your business dashboard.\n\n"
            if pending_count > 0:
                message += f"⚠️ You have *{pending_count}* pending stamp requests!\n\n"
            message += "What would you like to do?" + BRAND_FOOTER
            
            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "🏪 Welcome to StampMe for Business!\n\nYour account is pending approval by our team. You'll be notified within 24 hours." + BRAND_FOOTER,
                parse_mode="Markdown"
            )
    else:
        keyboard = [
            [InlineKeyboardButton("💳 My Wallet", callback_data="show_wallet")],
            [InlineKeyboardButton("🏪 Become a Merchant", callback_data="request_merchant")]
        ]
        
        await update.message.reply_text(
            f"👋 Hi {first_name}!\n\nWelcome to StampMe! We help you collect stamps and earn rewards at your favorite stores.\n\n🎯 *How it works:*\n1. Scan a QR code at any store\n2. Request a stamp after your visit\n3. Collect rewards automatically!\n\nTry /wallet to see your cards." + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    user = await db.get_user(update.effective_user.id)
    
    if user and user['user_type'] == 'merchant' and user['merchant_approved']:
        message = (
            "🏪 *Merchant Help*\n\n"
            "*Main Commands:*\n"
            "/newcampaign <n> <stamps> - Create campaign\n"
            "/mycampaigns - List campaigns\n"
            "/getqr <id> - Get QR code\n"
            "/pending - View requests\n"
            "/dashboard - Statistics\n"
            "/addreward <id> <stamps> <reward>\n"
            "/stats <id> - Analytics\n"
            "/share <id> - Referral link"
        )
    else:
        message = (
            "👋 *Customer Help*\n\n"
            "/wallet - View stamp cards\n"
            "/start - Main menu\n\n"
            "Scan QR codes at stores to join campaigns!"
        )
    
    await update.message.reply_text(message + BRAND_FOOTER, parse_mode="Markdown")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show wallet"""
    user_id = update.effective_user.id
    enrollments = await db.get_customer_enrollments(user_id)
    
    if not enrollments:
        keyboard = [[InlineKeyboardButton("Find a Store", url=f"https://t.me/{BOT_USERNAME}")]]
        await update.message.reply_text(
            "💳 *Your Wallet is Empty*\n\nScan a QR code at any participating store to start collecting stamps!" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    for e in enrollments:
        try:
            img = generate_card_image(e['name'], e['stamps'], e['stamps_needed'])
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            
            progress_bar = generate_progress_bar(e['stamps'], e['stamps_needed'])
            
            if e['completed']:
                caption = f"🎉 *{e['name']}*\n\n{progress_bar}\n✅ *COMPLETED!*\n\nShow this to claim your reward!"
            else:
                caption = f"📋 *{e['name']}*\n\n{progress_bar}\n{e['stamps']}/{e['stamps_needed']} stamps\n\nKeep collecting!"
            
            keyboard = []
            if not e['completed']:
                keyboard.append([InlineKeyboardButton("Request Stamp", callback_data=f"request_{e['campaign_id']}")])
            
            await update.message.reply_photo(
                photo=bio,
                caption=caption + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error showing wallet card: {e}")

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create campaign"""
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("⚠️ You need merchant approval first.\n\nUse /start and tap 'Become a Merchant'" + BRAND_FOOTER)
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 *Create Campaign*\n\n*Usage:*\n`/newcampaign <n> <stamps>`\n\n*Example:*\n`/newcampaign Coffee 5`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    try:
        stamps_needed = int(context.args[-1])
        name = " ".join(context.args[:-1])
        
        if not (1 <= stamps_needed <= 50):
            await update.message.reply_text("Stamps must be between 1 and 50")
            return
        
        campaign_id = await db.create_campaign(user_id, name, stamps_needed)
        
        keyboard = [[InlineKeyboardButton("📱 Get QR Code", callback_data=f"getqr_{campaign_id}")]]
        
        await update.message.reply_text(
            f"✅ *Campaign Created!*\n\n📋 {name}\n🎯 {stamps_needed} stamps needed\n🆔 Campaign ID: `{campaign_id}`\n\nGet your QR code below!" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Last argument must be a number")
    except Exception as e:
        print(f"Error creating campaign: {e}")
        await update.message.reply_text("Error creating campaign")

async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get QR code"""
    if not context.args:
        await update.message.reply_text("*Usage:* `/getqr <campaign_id>`\n\n*Example:* `/getqr 1`" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign:
            await update.message.reply_text("Campaign not found")
            return
        
        if campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("You don't own this campaign")
            return
        
        link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        await update.message.reply_photo(
            photo=bio,
            caption=f"📱 *QR Code: {campaign['name']}*\n\n🎯 {campaign['stamps_needed']} stamps needed\n\nDisplay at your store!\n\nLink: `{link}`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Campaign ID must be a number")
    except Exception as e:
        print(f"Error generating QR: {e}")
        await update.message.reply_text("Error generating QR code")

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending requests"""
    user_id = update.effective_user.id
    requests = await db.get_pending_requests(user_id)
    
    if not requests:
        await update.message.reply_text("📭 *No Pending Requests*\n\nYou're all caught up!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    keyboard = []
    for req in requests[:15]:
        customer_name = req['username'] or req['first_name']
        progress = f"{req['current_stamps']}/{req['stamps_needed']}"
        button_text = f"{customer_name} - {req['campaign_name']} ({progress})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"viewreq_{req['id']}")])
    
    if len(requests) > 1:
        keyboard.append([InlineKeyboardButton(f"✅ Approve All ({len(requests)})", callback_data="approve_all")])
    
    await update.message.reply_text(
        f"⏳ *Pending Requests ({len(requests)})*\n\nTap to review:" + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def stamp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alternative to pending - same functionality"""
    await pending(update, context)

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show dashboard"""
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("Merchant approval required")
        return
    
    campaigns = await db.get_merchant_campaigns(user_id)
    pending_count = await db.get_pending_count(user_id)
    today_stats = await db.get_daily_stats(user_id)
    
    total_customers = sum(c['total_joins'] for c in campaigns)
    total_completions = sum(c['total_completions'] for c in campaigns)
    
    message = (
        f"📊 *Your Dashboard*\n\n"
        f"📆 *Today:*\n"
        f"  Visits: {today_stats['visits']}\n"
        f"  Stamps given: {today_stats['stamps_given']}\n\n"
        f"📈 *Overall:*\n"
        f"  Campaigns: {len(campaigns)}\n"
        f"  Total customers: {total_customers}\n"
        f"  Rewards claimed: {total_completions}\n"
    )
    
    if pending_count > 0:
        message += f"\n⏳ *{pending_count} pending requests*"
    
    keyboard = [
        [InlineKeyboardButton("⏳ Pending", callback_data="show_pending")],
        [InlineKeyboardButton("📋 Campaigns", callback_data="my_campaigns")]
    ]
    
    if pending_count > 0:
        keyboard.insert(0, [InlineKeyboardButton(f"✅ Approve All", callback_data="approve_all")])
    
    await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List campaigns"""
    campaigns = await db.get_merchant_campaigns(update.effective_user.id)
    
    if not campaigns:
        await update.message.reply_text(
            "📭 *No campaigns yet*\n\nCreate one with:\n`/newcampaign <n> <stamps>`\n\nExample: `/newcampaign Coffee 5`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    message = "📋 *Your Campaigns*\n\n"
    keyboard = []
    
    for c in campaigns:
        message += f"*{c['name']}* (ID: `{c['id']}`)\n"
        message += f"  🎯 {c['stamps_needed']} stamps\n"
        message += f"  👥 {c['total_joins']} customers\n"
        message += f"  ✅ {c['total_completions']} completed\n\n"
        
        keyboard.append([InlineKeyboardButton(f"📱 {c['name']}", callback_data=f"campaign_detail_{c['id']}")])
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="Markdown"
    )

async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add reward tier"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "🎁 *Add Reward*\n\n*Usage:*\n`/addreward <id> <stamps> <reward>`\n\n*Example:*\n`/addreward 1 5 Free Coffee`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        stamps_req = int(context.args[1])
        reward = " ".join(context.args[2:])
        
        campaign = await db.get_campaign(campaign_id)
        if not campaign or campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("Campaign not found or you don't own it")
            return
        
        await db.add_reward_tier(campaign_id, stamps_req, reward)
        
        await update.message.reply_text(
            f"✅ *Reward Added!*\n\n📋 {campaign['name']}\n🎯 At {stamps_req} stamps: {reward}" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Invalid format. Check your numbers.")
    except Exception as e:
        print(f"Error adding reward: {e}")
        await update.message.reply_text("Error adding reward")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats"""
    if not context.args:
        await update.message.reply_text("*Usage:* `/stats <campaign_id>`\n\n*Example:* `/stats 1`" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign or campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("Campaign not found")
            return
        
        customers = await db.get_campaign_customers(campaign_id)
        total_stamps = sum(c['stamps'] for c in customers)
        completed = sum(1 for c in customers if c['completed'])
        completion_rate = (completed / len(customers) * 100) if customers else 0
        
        message = (
            f"📊 *Campaign Stats*\n\n"
            f"📋 *{campaign['name']}*\n"
            f"🆔 ID: {campaign_id}\n\n"
            f"👥 *Customers:*\n"
            f"  Total: {len(customers)}\n"
            f"  Completed: {completed}\n"
            f"  Rate: {completion_rate:.1f}%\n\n"
            f"⭐ *Stamps:*\n"
            f"  Total given: {total_stamps}\n"
            f"  Needed: {campaign['stamps_needed']}"
        )
        
        keyboard = [[InlineKeyboardButton("📱 Get QR", callback_data=f"getqr_{campaign_id}")]]
        
        await update.message.reply_text(
            message + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Campaign ID must be a number")

async def share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Share referral link"""
    if not context.args:
        await update.message.reply_text("*Usage:* `/share <campaign_id>`\n\n*Example:* `/share 1`" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign:
            await update.message.reply_text("Campaign not found")
            return
        
        user_id = update.effective_user.id
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}_{campaign_id}"
        
        await update.message.reply_text(
            f"🎁 *Share & Earn*\n\nShare this link:\n`{link}`\n\nYou both get a bonus stamp when they join!\n\n📋 {campaign['name']}" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("Campaign ID must be a number")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    pending_merchants = await db.get_pending_merchants()
    
    message = f"🔧 *Admin Panel*\n\nPending merchants: {len(pending_merchants)}\n\n"
    
    keyboard = []
    for merchant in pending_merchants:
        button_text = f"{merchant['first_name']} (@{merchant['username'] or 'no username'})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"admin_approve_{merchant['id']}")])
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="Markdown"
    )

# ==================== CALLBACK HANDLERS ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    try:
        # Request stamp
        if data.startswith("request_"):
            campaign_id = int(data.split("_")[1])
            campaign = await db.get_campaign(campaign_id)
            enrollment = await db.get_enrollment(campaign_id, user_id)
            
            if not enrollment:
                await query.edit_message_text("Please join this campaign first")
                return
            
            request_id = await db.create_stamp_request(campaign_id, user_id, campaign['merchant_id'], enrollment['id'])
            await db.queue_notification(campaign['merchant_id'], f"⏳ New stamp request from {query.from_user.first_name}")
            
            await query.edit_message_text(
                "⏳ *Stamp Request Sent!*\n\nThe merchant will review it soon. You'll get notified!" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
        
        # View request
        elif data.startswith("viewreq_"):
            request_id = int(data.split("_")[1])
            
            async with db.pool.acquire() as conn:
                req = await conn.fetchrow('''
                    SELECT sr.*, c.name as campaign_name, u.username, u.first_name, e.stamps, ca.stamps_needed
                    FROM stamp_requests sr
                    JOIN campaigns ca ON sr.campaign_id = ca.id
                    JOIN users u ON sr.customer_id = u.id
                    JOIN enrollments e ON sr.enrollment_id = e.id
                    WHERE sr.id = $1
                ''', request_id)
            
            if not req:
                await query.edit_message_text("Request not found")
                return
            
            customer_name = req['username'] or req['first_name']
            progress_bar = generate_progress_bar(req['stamps'], req['stamps_needed'])
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{request_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{request_id}")
                ],
                [InlineKeyboardButton("« Back", callback_data="show_pending")]
            ]
            
            await query.edit_message_text(
                f"👤 *{customer_name}*\n📋 {req['campaign_name']}\n\n{progress_bar}\n{req['stamps']}/{req['stamps_needed']} stamps\n\nApprove or reject?" + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        
        # Approve
        elif data.startswith("approve_"):
            request_id = int(data.split("_")[1])
            result = await db.approve_stamp_request(request_id)
            
            if result:
                campaign = result['campaign']
                progress_bar = generate_progress_bar(result['new_stamps'], campaign['stamps_needed'])
                
                if result['completed']:
                    await db.queue_notification(result['customer_id'], f"🎉 *REWARD EARNED!*\n\nYou completed {campaign['name']}!\n\nShow this to claim your reward!" + BRAND_FOOTER)
                    await query.edit_message_text(f"🎉 *Approved - Reward Earned!*\n\n{progress_bar}\n\nCustomer completed the campaign!" + BRAND_FOOTER, parse_mode="Markdown")
                else:
                    await db.queue_notification(result['customer_id'], f"⭐ *New Stamp!*\n\n{campaign['name']}\n{progress_bar}\n{result['new_stamps']}/{campaign['stamps_needed']}" + BRAND_FOOTER)
                    await query.edit_message_text(f"✅ *Approved!*\n\n{progress_bar}\n{result['new_stamps']}/{campaign['stamps_needed']} stamps" + BRAND_FOOTER, parse_mode="Markdown")
            else:
                await query.edit_message_text("Request already processed")
        
        # Reject
        elif data.startswith("reject_"):
            request_id = int(data.split("_")[1])
            result = await db.reject_stamp_request(request_id)
            if result:
                await db.queue_notification(result['customer_id'], "Your stamp request was not approved. Please contact the merchant.")
            await query.edit_message_text("❌ Request rejected" + BRAND_FOOTER)
        
        # Approve all
        elif data == "approve_all":
            requests = await db.get_pending_requests(user_id)
            count = 0
            for req in requests:
                result = await db.approve_stamp_request(req['id'])
                if result:
                    count += 1
            await query.edit_message_text(f"✅ Approved {count} request(s)!\n\nAll customers notified." + BRAND_FOOTER, parse_mode="Markdown")
        
        # Show wallet
        elif data == "show_wallet":
            await query.message.delete()
            await wallet(update, context)
        
        # Show pending
        elif data == "show_pending":
            await query.message.delete()
            await pending(update, context)
        
        # Merchant dashboard
        elif data == "merchant_dashboard":
            await query.message.delete()
            await dashboard(update, context)
        
        # My campaigns
        elif data == "my_campaigns":
            await query.message.delete()
            await mycampaigns(update, context)
        
        # Request merchant
        elif data == "request_merchant":
            await db.request_merchant_access(user_id)
            for admin_id in ADMIN_IDS:
                await db.queue_notification(admin_id, f"🏪 New merchant request from {query.from_user.first_name} (@{query.from_user.username or 'no username'})")
            await query.edit_message_text(
                "⏳ *Request Sent!*\n\nYour merchant application is being reviewed. You'll be notified within 24 hours!" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
        
        # Get QR callback
        elif data.startswith("getqr_"):
            campaign_id = int(data.split("_")[1])
            context.args = [str(campaign_id)]
            await query.message.delete()
            await getqr(update, context)
        
        # Campaign detail
        elif data.startswith("campaign_detail_"):
            campaign_id = int(data.split("_")[2])
            campaign = await db.get_campaign(campaign_id)
            customers = await db.get_campaign_customers(campaign_id)
            
            message = (
                f"📋 *{campaign['name']}*\n\n"
                f"🆔 ID: `{campaign_id}`\n"
                f"🎯 {campaign['stamps_needed']} stamps\n"
                f"👥 {len(customers)} customers\n"
                f"✅ {campaign['total_completions']} completed"
            )
            
            keyboard = [
                [InlineKeyboardButton("📱 Get QR", callback_data=f"getqr_{campaign_id}")],
                [InlineKeyboardButton("📊 Statistics", callback_data=f"stats_{campaign_id}")],
                [InlineKeyboardButton("« Back", callback_data="my_campaigns")]
            ]
            
            await query.edit_message_text(
                message + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        
        # Stats callback
        elif data.startswith("stats_"):
            campaign_id = int(data.split("_")[1])
            context.args = [str(campaign_id)]
            await query.message.delete()
            await stats_command(update, context)
        
        # Admin approve
        elif data.startswith("admin_approve_"):
            if user_id not in ADMIN_IDS:
                return
            merchant_id = int(data.split("_")[2])
            await db.approve_merchant(merchant_id, user_id)
            await db.queue_notification(
                merchant_id,
                "🎉 *Congratulations!*\n\nYour merchant account has been approved!\n\nUse /newcampaign to create your first campaign!" + BRAND_FOOTER
            )
            await query.edit_message_text(f"✅ Merchant approved!" + BRAND_FOOTER, parse_mode="Markdown")
    
    except Exception as e:
        print(f"Callback error: {e}")
        try:
            await query.edit_message_text("Error processing request. Please try again." + BRAND_FOOTER)
        except:
            pass

# ==================== BACKGROUND TASKS ====================

async def send_notifications(app):
    """Send queued notifications"""
    while True:
        try:
            notifications = await db.get_pending_notifications()
            for notif in notifications:
                try:
                    await app.bot.send_message(notif['user_id'], notif['message'], parse_mode="Markdown")
                    await db.mark_notification_sent(notif['id'])
                except Exception as e:
                    print(f"Failed to send notification: {e}")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Notification task error: {e}")
            await asyncio.sleep(5)

async def send_daily_summaries():
    """Send daily summaries to merchants"""
    try:
        async with db.pool.acquire() as conn:
            merchants = await conn.fetch('''
                SELECT u.id, u.first_name FROM users u
                JOIN merchant_settings ms ON u.id = ms.merchant_id
                WHERE u.user_type = 'merchant' 
                AND u.merchant_approved = TRUE 
                AND ms.daily_summary_enabled = TRUE
            ''')
        
        today = datetime.now().date()
        
        for merchant in merchants:
            try:
                stats = await db.get_daily_stats(merchant['id'], today)
                pending = await db.get_pending_count(merchant['id'])
                tip = random.choice(MERCHANT_TIPS)
                
                message = (
                    f"📆 *Daily Summary - {today.strftime('%B %d')}*\n\n"
                    f"👥 Visits: {stats['visits']}\n"
                    f"⭐ Stamps given: {stats['stamps_given']}\n"
                    f"🎁 Rewards: {stats['rewards_claimed']}\n"
                )
                
                if pending > 0:
                    message += f"⏳ Pending: {pending}\n"
                
                message += f"\n💡 *Tip:* {tip}"
                
                await db.queue_notification(merchant['id'], message + BRAND_FOOTER)
            except Exception as e:
                print(f"Error sending summary to {merchant['id']}: {e}")
    except Exception as e:
        print(f"Error in daily summaries: {e}")

# ==================== MAIN ====================

async def main():
    """Start the bot"""
    print("🚀 Starting StampMe Bot...")
    
    try:
        await db.connect()
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    await start_web_server()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add all command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("newcampaign", newcampaign))
    app.add_handler(CommandHandler("getqr", getqr))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("stamp", stamp_command))  # Alternative to pending
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("mycampaigns", mycampaigns))
    app.add_handler(CommandHandler("addreward", addreward))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("share", share))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    await app.initialize()
    await app.start()
    
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(2)
        print("✅ Webhook cleared")
    except Exception as e:
        print(f"⚠️ Webhook warning: {e}")
    
    try:
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            timeout=30
        )
        print("✅ Bot is running!")
        print(f"📱 Bot: @{BOT_USERNAME}")
        print(f"🔧 Admin IDs: {ADMIN_IDS}")
    except Exception as e:
        print(f"❌ Polling error: {e}")
        raise
    
    # Start background tasks
    asyncio.create_task(send_notifications(app))
    print("✅ Notification sender started")
    
    # Schedule daily summaries
    scheduler.add_job(send_daily_summaries, 'cron', hour=18, minute=0)
    scheduler.start()
    print("✅ Daily summary scheduler started (6 PM)")
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

