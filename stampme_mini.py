import os
import asyncio
import io
import random
from datetime import datetime, time, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import qrcode
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import StampMeDatabase

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
    
    draw.text((40, 30), campaign_name, fill='white', font=title_font)
    
    stamp_size = 55
    spacing = 18
    start_x = 40
    start_y = 120
    cols = min(5, needed_stamps)
    
    for i in range(needed_stamps):
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
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db.create_or_update_user(user_id, username, first_name)
    user = await db.get_user(user_id)
    
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
                        f"🎉 *Welcome!*\n\nYou've joined: *{campaign['name']}*\nCollect {campaign['stamps_needed']} stamps to earn rewards!\n\n👉 Request your first stamp below!" + BRAND_FOOTER,
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
                "🏪 Welcome to StampMe for Business!\n\nYou're almost ready to start rewarding your customers.\n\n⏳ *Next step:*\nYour account is pending approval by our team. You'll be notified within 24 hours." + BRAND_FOOTER,
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
    user = await db.get_user(update.effective_user.id)
    
    if user and user['user_type'] == 'merchant' and user['merchant_approved']:
        message = "🏪 *Merchant Help*\n\n/newcampaign - Create campaign\n/mycampaigns - View campaigns\n/pending - See requests\n/dashboard - Statistics\n/getqr <id> - Get QR code"
    else:
        message = "👋 *Customer Help*\n\n/wallet - View stamp cards\n/start - Main menu\n\nScan QR codes at stores to join campaigns!"
    
    await update.message.reply_text(message + BRAND_FOOTER, parse_mode="Markdown")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    enrollments = await db.get_customer_enrollments(user_id)
    
    if not enrollments:
        await update.message.reply_text("💳 *Your Wallet is Empty*\n\nScan a QR code at any participating store to start collecting stamps!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    for e in enrollments:
        img = generate_card_image(e['name'], e['stamps'], e['stamps_needed'])
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        progress_bar = generate_progress_bar(e['stamps'], e['stamps_needed'])
        
        if e['completed']:
            caption = f"🎉 *{e['name']}*\n\n{progress_bar}\n✅ *COMPLETED!*\n\nShow this card to claim your reward!\nMerchant: {e['merchant_name']}"
        else:
            caption = f"📋 *{e['name']}*\n\n{progress_bar}\n{e['stamps']}/{e['stamps_needed']} stamps\n\nKeep collecting!\nMerchant: {e['merchant_name']}"
        
        keyboard = []
        if not e['completed']:
            keyboard.append([InlineKeyboardButton("Request Stamp", callback_data=f"request_{e['campaign_id']}")])
        
        await update.message.reply_photo(
            photo=bio,
            caption=caption + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode="Markdown"
        )

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("⚠️ You need merchant approval to create campaigns." + BRAND_FOOTER)
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 *Create a Campaign*\n\n*Usage:* `/newcampaign <n> <stamps>`\n\n*Example:* `/newcampaign Coffee 5`" + BRAND_FOOTER,
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
            f"✅ *Campaign Created!*\n\n📋 {name}\n🎯 {stamps_needed} stamps\n🆔 ID: {campaign_id}\n\n👉 Get your QR code below!" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error creating campaign: {e}")
        await update.message.reply_text("Error creating campaign")

async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/getqr <campaign_id>`" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign or campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("Campaign not found")
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
            caption=f"📱 *QR Code: {campaign['name']}*\n\n🎯 {campaign['stamps_needed']} stamps\n\nDisplay this at your store!\n\nLink: `{link}`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error generating QR: {e}")
        await update.message.reply_text("Error generating QR code")

async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"⏳ *Pending Stamp Requests*\n\nYou have {len(requests)} request(s) waiting.\n\nTap to review:" + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def merchant_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("Merchant approval required")
        return
    
    campaigns = await db.get_merchant_campaigns(user_id)
    pending_count = await db.get_pending_count(user_id)
    today_stats = await db.get_daily_stats(user_id)
    
    message = (
        f"📊 *Your Dashboard*\n\n"
        f"📆 *Today:*\n  Visits: {today_stats['visits']}\n  Stamps: {today_stats['stamps_given']}\n\n"
        f"📈 *Overall:*\n  Campaigns: {len(campaigns)}\n"
    )
    
    if pending_count > 0:
        message += f"\n⏳ *{pending_count} pending requests*"
    
    keyboard = [
        [InlineKeyboardButton("⏳ Pending Requests", callback_data="show_pending")],
        [InlineKeyboardButton("📋 My Campaigns", callback_data="my_campaigns")]
    ]
    
    await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    campaigns = await db.get_merchant_campaigns(update.effective_user.id)
    
    if not campaigns:
        await update.message.reply_text("📭 No campaigns yet\n\nUse: `/newcampaign <n> <stamps>`" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    message = "📋 *Your Campaigns*\n\n"
    for c in campaigns:
        message += f"*{c['name']}* (ID: {c['id']})\n  🎯 {c['stamps_needed']} stamps\n\n"
    
    await update.message.reply_text(message + BRAND_FOOTER, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    try:
        if data.startswith("request_"):
            campaign_id = int(data.split("_")[1])
            campaign = await db.get_campaign(campaign_id)
            enrollment = await db.get_enrollment(campaign_id, user_id)
            
            if not enrollment:
                await query.edit_message_text("Join this campaign first")
                return
            
            request_id = await db.create_stamp_request(campaign_id, user_id, campaign['merchant_id'], enrollment['id'])
            await db.queue_notification(campaign['merchant_id'], f"⏳ New stamp request from {query.from_user.first_name}")
            
            await query.edit_message_text("⏳ *Stamp request sent!*\n\nThe merchant will review it soon." + BRAND_FOOTER, parse_mode="Markdown")
        
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
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{request_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{request_id}")],
                [InlineKeyboardButton("« Back", callback_data="show_pending")]
            ]
            
            await query.edit_message_text(
                f"👤 *Customer:* {customer_name}\n📋 *Campaign:* {req['campaign_name']}\n\n{progress_bar}\nProgress: {req['stamps']}/{req['stamps_needed']}" + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        
        elif data.startswith("approve_"):
            request_id = int(data.split("_")[1])
            result = await db.approve_stamp_request(request_id)
            
            if result:
                campaign = result['campaign']
                progress_bar = generate_progress_bar(result['new_stamps'], campaign['stamps_needed'])
                
                if result['completed']:
                    await db.queue_notification(result['customer_id'], f"🎉 *REWARD EARNED!*\n\nCongratulations! You've completed {campaign['name']}!" + BRAND_FOOTER)
                    await query.edit_message_text(f"🎉 *Stamp Approved - Reward Earned!*\n\n{progress_bar}\nCustomer completed!" + BRAND_FOOTER, parse_mode="Markdown")
                else:
                    await db.queue_notification(result['customer_id'], f"⭐ *New stamp!*\n\n{campaign['name']}\n{progress_bar}\n{result['new_stamps']}/{campaign['stamps_needed']}" + BRAND_FOOTER)
                    await query.edit_message_text(f"✅ *Approved!*\n\n{progress_bar}\nProgress: {result['new_stamps']}/{campaign['stamps_needed']}" + BRAND_FOOTER, parse_mode="Markdown")
        
        elif data.startswith("reject_"):
            request_id = int(data.split("_")[1])
            await db.reject_stamp_request(request_id)
            await query.edit_message_text("❌ Request rejected" + BRAND_FOOTER)
        
        elif data == "approve_all":
            requests = await db.get_pending_requests(user_id)
            for req in requests:
                await db.approve_stamp_request(req['id'])
            await query.edit_message_text(f"✅ Approved {len(requests)} requests!" + BRAND_FOOTER)
        
        elif data == "show_wallet":
            await query.message.delete()
            await wallet(update, context)
        
        elif data == "show_pending":
            await query.message.delete()
            await pending_requests(update, context)
        
        elif data == "merchant_dashboard":
            await query.message.delete()
            await merchant_dashboard(update, context)
        
        elif data == "request_merchant":
            await db.request_merchant_access(user_id)
            for admin_id in ADMIN_IDS:
                await db.queue_notification(admin_id, f"🏪 New merchant request from {query.from_user.first_name}")
            await query.edit_message_text("⏳ Your request is pending approval!" + BRAND_FOOTER)
        
        elif data.startswith("getqr_"):
            campaign_id = int(data.split("_")[1])
            context.args = [str(campaign_id)]
            await query.message.delete()
            await getqr(update, context)
        
        elif data.startswith("admin_approve_"):
            if user_id not in ADMIN_IDS:
                return
            merchant_id = int(data.split("_")[2])
            await db.approve_merchant(merchant_id, user_id)
            await db.queue_notification(merchant_id, "🎉 *Congratulations!*\n\nYour merchant account has been approved!\n\nUse /newcampaign to get started!" + BRAND_FOOTER)
            await query.edit_message_text(f"✅ Merchant approved!" + BRAND_FOOTER)
    
    except Exception as e:
        print(f"Callback error: {e}")
        await query.edit_message_text("Error processing request")

# ==================== BACKGROUND TASKS ====================

async def send_notifications(app):
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
    async with db.pool.acquire() as conn:
        merchants = await conn.fetch('''
            SELECT u.id, u.first_name FROM users u
            JOIN merchant_settings ms ON u.id = ms.merchant_id
            WHERE u.user_type = 'merchant' AND u.merchant_approved = TRUE AND ms.daily_summary_enabled = TRUE
        ''')
    
    for merchant in merchants:
        try:
            stats = await db.get_daily_stats(merchant['id'])
            tip = random.choice(MERCHANT_TIPS)
            
            message = (
                f"📆 *Daily Summary*\n\n"
                f"👥 Visits: {stats['visits']}\n"
                f"⭐ Stamps: {stats['stamps_given']}\n\n"
                f"💡 *Tip:* {tip}"
                + BRAND_FOOTER
            )
            await db.queue_notification(merchant['id'], message)
        except Exception as e:
            print(f"Error sending summary: {e}")

# ==================== MAIN ====================

async def main():
    print("🚀 Starting StampMe Bot...")
    
    try:
        await db.connect()
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    await start_web_server()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("newcampaign", newcampaign))
    app.add_handler(CommandHandler("getqr", getqr))
    app.add_handler(CommandHandler("pending", pending_requests))
    app.add_handler(CommandHandler("dashboard", merchant_dashboard))
    app.add_handler(CommandHandler("mycampaigns", mycampaigns))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    await app.initialize()
    await app.start()
    
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(2)
        print("✅ Webhook cleared")
    except:
        pass
    
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES, timeout=30)
    
    print("✅ Bot is running!")
    print(f"📱 @{BOT_USERNAME}")
    
    asyncio.create_task(send_notifications(app))
    print("✅ Notification sender started")
    
    scheduler.add_job(send_daily_summaries, 'cron', hour=18, minute=0)
    scheduler.start()
    print("✅ Scheduler started")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
