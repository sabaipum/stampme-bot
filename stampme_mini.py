import os
import asyncio
import io
import random
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
import qrcode
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database_complete import StampMeDatabase
from collections import defaultdict
import logging

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

# Conversation states
PROGRAM_NAME, PROGRAM_STAMPS, PROGRAM_REWARD, PROGRAM_DESCRIPTION, PROGRAM_CATEGORY = range(5)

# Initialize
db = StampMeDatabase(DATABASE_URL)
scheduler = AsyncIOScheduler()

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== RATE LIMITING ====================

class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
        self.blocked_users = {}
    
    def check_rate_limit(self, user_id: int) -> tuple[bool, int]:
        now = datetime.now()
        if user_id in self.blocked_users:
            if now < self.blocked_users[user_id]:
                return False, 0
            else:
                del self.blocked_users[user_id]
        cutoff = now - timedelta(seconds=60)
        self.requests[user_id] = [req_time for req_time in self.requests[user_id] if req_time > cutoff]
        if len(self.requests[user_id]) >= 30:
            self.blocked_users[user_id] = now + timedelta(minutes=5)
            return False, 0
        self.requests[user_id].append(now)
        remaining = 30 - len(self.requests[user_id])
        return True, remaining

rate_limiter = RateLimiter()

# ==================== KEYBOARDS ====================

def get_customer_keyboard():
    keyboard = [
        [KeyboardButton("💳 My Wallet"), KeyboardButton("📍 Find Stores")],
        [KeyboardButton("🆔 Show My ID"), KeyboardButton("🎁 My Rewards")],
        [KeyboardButton("⚙️ Settings"), KeyboardButton("❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_merchant_keyboard():
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("⏳ Pending")],
        [KeyboardButton("📸 Scan Customer"), KeyboardButton("📋 My Programs")],
        [KeyboardButton("➕ New Program"), KeyboardButton("⚙️ Settings")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("👑 Admin Panel"), KeyboardButton("📊 System Stats")],
        [KeyboardButton("👥 Manage Users"), KeyboardButton("🏪 Manage Merchants")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("⚙️ Settings")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

# ==================== UTILITY FUNCTIONS ====================

def generate_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total == 0:
        return "░" * length
    filled = int((current / total) * length)
    filled = max(0, min(length, filled))
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
    for i in range(min(needed_stamps, 20)):
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

# ==================== MIGRATIONS ====================

async def run_migrations(pool):
    try:
        async with pool.acquire() as conn:
            print("  📝 Running migrations...")
            await conn.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='category') THEN
                        ALTER TABLE campaigns ADD COLUMN category VARCHAR(50);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='description') THEN
                        ALTER TABLE campaigns ADD COLUMN description TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='campaigns' AND column_name='reward_description') THEN
                        ALTER TABLE campaigns ADD COLUMN reward_description TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='onboarded') THEN
                        ALTER TABLE users ADD COLUMN onboarded BOOLEAN DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='tutorial_completed') THEN
                        ALTER TABLE users ADD COLUMN tutorial_completed BOOLEAN DEFAULT FALSE;
                    END IF;
                END $$;
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    notification_enabled BOOLEAN DEFAULT TRUE,
                    marketing_emails BOOLEAN DEFAULT TRUE,
                    data_sharing BOOLEAN DEFAULT FALSE,
                    language VARCHAR(10) DEFAULT 'en',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS merchant_settings (
                    merchant_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    notification_frequency VARCHAR(20) DEFAULT 'immediate',
                    daily_summary_enabled BOOLEAN DEFAULT TRUE,
                    auto_approve_trusted BOOLEAN DEFAULT FALSE,
                    business_hours JSONB,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reward_claims (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
                    customer_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    merchant_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    claimed_at TIMESTAMP DEFAULT NOW(),
                    reward_value TEXT
                );
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_campaigns_category ON campaigns(category);
                CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(active);
                CREATE INDEX IF NOT EXISTS idx_enrollments_customer ON enrollments(customer_id);
            """)
            print("  ✅ Migrations complete!")
    except Exception as e:
        print(f"  ⚠️ Migration error: {e}")

# ==================== SETTINGS ====================

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    try:
        async with db.pool.acquire() as conn:
            prefs = await conn.fetchrow("SELECT * FROM user_preferences WHERE user_id = $1", user_id)
            if not prefs:
                await conn.execute("INSERT INTO user_preferences (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
                prefs = await conn.fetchrow("SELECT * FROM user_preferences WHERE user_id = $1", user_id)
    except Exception as e:
        logger.error(f"Error getting preferences: {e}")
        prefs = {'notification_enabled': True, 'marketing_emails': True, 'data_sharing': False}
    
    notif_status = "✅ ON" if prefs.get('notification_enabled', True) else "❌ OFF"
    marketing_status = "✅ ON" if prefs.get('marketing_emails', True) else "❌ OFF"
    data_status = "✅ ON" if prefs.get('data_sharing', False) else "❌ OFF"
    
    keyboard = [
        [InlineKeyboardButton(f"🔔 Notifications: {notif_status}", callback_data="settings_notifications")],
        [InlineKeyboardButton(f"📧 Marketing: {marketing_status}", callback_data="settings_marketing")],
        [InlineKeyboardButton(f"📊 Data Sharing: {data_status}", callback_data="settings_data")],
        [InlineKeyboardButton("🌐 Language (EN)", callback_data="settings_language")],
        [InlineKeyboardButton("🗑️ Delete My Data", callback_data="settings_delete_confirm")],
        [InlineKeyboardButton("« Back", callback_data="settings_close")]
    ]
    
    message = f"⚙️ *Settings*\n\nUser ID: `{user_id}`\nAccount Type: {user['user_type'].title()}\n\nConfigure your preferences below:"
    
    if update.callback_query:
        await update.callback_query.message.edit_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==================== NEW PROGRAM WIZARD ====================

async def new_program_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text("❌ Only approved merchants can create programs!" + BRAND_FOOTER, parse_mode="Markdown")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]]
    await update.message.reply_text("🎯 *Create New Loyalty Program*\n\nLet's set up your program step by step.\n\nFirst, what's the name of your program?\n_Example: \"Buy 5 Get 1 Free\" or \"Coffee Club\"_", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PROGRAM_NAME

async def program_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    program_name = update.message.text.strip()
    if len(program_name) < 3:
        await update.message.reply_text("⚠️ Program name is too short. Please enter at least 3 characters:", parse_mode="Markdown")
        return PROGRAM_NAME
    if len(program_name) > 50:
        await update.message.reply_text("⚠️ Program name is too long (max 50 characters). Please try again:", parse_mode="Markdown")
        return PROGRAM_NAME
    context.user_data['program_name'] = program_name
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]]
    await update.message.reply_text(f"✅ Great! Program name: *{program_name}*\n\nHow many stamps are needed to complete the card?\n_Enter a number between 3 and 20_\n_Example: 5, 8, 10_", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PROGRAM_STAMPS

async def program_stamps_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stamps = int(update.message.text.strip())
        if stamps < 3 or stamps > 20:
            await update.message.reply_text("⚠️ Please enter a number between 3 and 20:", parse_mode="Markdown")
            return PROGRAM_STAMPS
        context.user_data['stamps_needed'] = stamps
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]]
        await update.message.reply_text(f"✅ Perfect! {stamps} stamps to complete.\n\nWhat reward do customers get when they complete the card?\n_Example: \"Free Coffee\", \"20% Off\", \"Free Dessert\"_", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return PROGRAM_REWARD
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number:", parse_mode="Markdown")
        return PROGRAM_STAMPS

async def program_reward_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reward = update.message.text.strip()
    if len(reward) < 3:
        await update.message.reply_text("⚠️ Reward description is too short. Please enter at least 3 characters:", parse_mode="Markdown")
        return PROGRAM_REWARD
    context.user_data['reward_description'] = reward
    keyboard = [
        [InlineKeyboardButton("☕ Food & Beverage", callback_data="cat_food")],
        [InlineKeyboardButton("💇 Beauty & Wellness", callback_data="cat_beauty")],
        [InlineKeyboardButton("🛍️ Retail & Shopping", callback_data="cat_retail")],
        [InlineKeyboardButton("🏋️ Fitness & Sports", callback_data="cat_fitness")],
        [InlineKeyboardButton("🎭 Entertainment", callback_data="cat_entertainment")],
        [InlineKeyboardButton("🔧 Services", callback_data="cat_services")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]
    ]
    await update.message.reply_text(f"✅ Reward: *{reward}*\n\nWhat category best describes your business?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PROGRAM_CATEGORY

async def program_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_map = {
        "cat_food": "Food & Beverage", "cat_beauty": "Beauty & Wellness", "cat_retail": "Retail & Shopping",
        "cat_fitness": "Fitness & Sports", "cat_entertainment": "Entertainment", "cat_services": "Services"
    }
    category = category_map.get(query.data, "Other")
    context.user_data['category'] = category
    keyboard = [
        [InlineKeyboardButton("⏭️ Skip", callback_data="skip_description")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]
    ]
    await query.message.edit_text(f"✅ Category: *{category}*\n\nFinally, add a short description (optional):\n_Tell customers what makes your program special!_\n_You can skip this step._", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PROGRAM_DESCRIPTION

async def program_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        description = None
        message = update.callback_query.message
    else:
        description = update.message.text.strip()
        if len(description) > 200:
            await update.message.reply_text("⚠️ Description is too long (max 200 characters). Please try again:", parse_mode="Markdown")
            return PROGRAM_DESCRIPTION
        message = update.message
    context.user_data['description'] = description
    user_id = update.effective_user.id if update.effective_user else context.user_data.get('user_id')
    try:
        campaign_id = await db.create_campaign(
            merchant_id=user_id,
            name=context.user_data['program_name'],
            stamps_needed=context.user_data['stamps_needed'],
            reward_description=context.user_data['reward_description'],
            category=context.user_data.get('category'),
            description=description
        )
        join_link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(join_link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        keyboard = [
            [InlineKeyboardButton("📤 Share Link", url=join_link)],
            [InlineKeyboardButton("📋 View My Programs", callback_data="view_my_programs")]
        ]
        summary = f"🎉 *Program Created Successfully!*\n\n📝 Name: *{context.user_data['program_name']}*\n⭐ Stamps: {context.user_data['stamps_needed']}\n🎁 Reward: {context.user_data['reward_description']}\n📁 Category: {context.user_data.get('category', 'N/A')}\n"
        if description:
            summary += f"📄 Description: {description}\n"
        summary += f"\n🔗 Share Link:\n`{join_link}`\n\n👆 Print this QR code and display it in your store!"
        await message.reply_photo(photo=bio, caption=summary + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        await message.reply_text("❌ Error creating program. Please try again later." + BRAND_FOOTER, parse_mode="Markdown")
        return ConversationHandler.END

async def cancel_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.edit_text("❌ Program creation cancelled." + BRAND_FOOTER, parse_mode="Markdown")
    return ConversationHandler.END

# ==================== MESSAGE HANDLERS ====================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    allowed, remaining = rate_limiter.check_rate_limit(user_id)
    if not allowed:
        keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else (get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard())
        await update.message.reply_text("⚠️ Please slow down! Wait a moment.", reply_markup=keyboard)
        return
    
    if user_id in ADMIN_IDS:
        if text == "👑 Admin Panel":
            await admin_panel(update, context)
            return
        elif text == "📊 System Stats":
            await system_stats(update, context)
            return
        elif text == "🏪 Manage Merchants":
            await manage_merchants(update, context)
            return
    
    if text == "💳 My Wallet":
        await wallet(update, context)
    elif text == "📍 Find Stores":
        await find_stores(update, context)
    elif text == "🆔 Show My ID":
        await myid(update, context)
    elif text == "🎁 My Rewards":
        await show_rewards(update, context)
    elif text == "⚙️ Settings":
        await settings_menu(update, context)
    elif text == "❓ Help":
        await help_command(update, context)
    elif text == "📊 Dashboard":
        await dashboard(update, context)
    elif text == "⏳ Pending":
        await pending(update, context)
    elif text == "📸 Scan Customer":
        await scan_customer_menu(update, context)
    elif text == "📋 My Programs":
        await mycampaigns(update, context)
    elif text == "➕ New Program":
        await new_program_start(update, context)
    else:
        keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else (get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard())
        await update.message.reply_text("👆 Please use the menu buttons below!", reply_markup=keyboard)

# ==================== COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    await db.create_or_update_user(user_id, username, first_name)
    user = await db.get_user(user_id)
    is_admin = user_id in ADMIN_IDS
    
    if context.args:
        arg = context.args[0]
        if arg.startswith("join_"):
            try:
                campaign_id = int(arg.split("_")[1])
                campaign = await db.get_campaign(campaign_id)
                if not campaign or not campaign['active']:
                    await update.message.reply_text("😕 This program is no longer available" + BRAND_FOOTER, reply_markup=get_customer_keyboard(), parse_mode="Markdown")
                    return
                enrollment = await db.get_enrollment(campaign_id, user_id)
                if not enrollment:
                    await db.enroll_customer(campaign_id, user_id)
                    keyboard = [[InlineKeyboardButton("⭐ Request First Stamp", callback_data=f"request_{campaign_id}")]]
                    await update.message.reply_text(f"🎉 *Welcome!*\n\nYou joined: *{campaign['name']}*\n\n🎯 Collect {campaign['stamps_needed']} stamps for rewards!\n\nUse the menu below 👇" + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                    await update.message.reply_text("Quick access:", reply_markup=get_customer_keyboard())
                    if not user.get('onboarded'):
                        await db.mark_user_onboarded(user_id)
                else:
                    progress_bar = generate_progress_bar(enrollment['stamps'], campaign['stamps_needed'], 20)
                    await update.message.reply_text(f"👋 Welcome back!\n\n*{campaign['name']}*\n{progress_bar}\n\n{enrollment['stamps']}/{campaign['stamps_needed']} stamps" + BRAND_FOOTER, reply_markup=get_customer_keyboard(), parse_mode="Markdown")
                return
            except Exception as e:
                logger.error(f"Error: {e}")
                return
    
    if is_admin:
        await update.message.reply_text(f"👑 *Admin Mode Activated*\n\nWelcome, {first_name}!\n\nUse the admin controls below:" + BRAND_FOOTER, reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        return
    
    if user and user['user_type'] == 'merchant':
        if user.get('merchant_approved', False):
            pending_count = await db.get_pending_count(user_id)
            message = f"👋 Welcome back, {first_name}!\n\n"
            if pending_count > 0:
                message += f"⚠️ {pending_count} pending requests\n\n"
            message += "Use the menu below 👇"
            await update.message.reply_text(message + BRAND_FOOTER, reply_markup=get_merchant_keyboard(), parse_mode="Markdown")
        else:
            await update.message.reply_text("🏪 *Merchant Application Pending*\n\nYour account is being reviewed.\nYou'll be notified within 24 hours!" + BRAND_FOOTER, parse_mode="Markdown")
    else:
        is_new = not user.get('onboarded', False)
        if is_new:
            keyboard = [[InlineKeyboardButton("🎯 Quick Tutorial", callback_data="start_tutorial")], [InlineKeyboardButton("🔍 Find Stores", callback_data="find_stores")]]
            await update.message.reply_text(f"👋 Hi {first_name}!\n\nWelcome to *StampMe* 💙\n\nYour smart digital loyalty card!\n\n✨ *Features:*\n• Collect stamps at stores\n• Track progress in real-time\n• Earn rewards automatically\n• No more paper cards!\n\nUse the menu below to get started 👇" + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            await update.message.reply_text("Tap these buttons anytime:", reply_markup=get_customer_keyboard())
            await db.mark_user_onboarded(user_id)
        else:
            try:
                enrollments = await db.get_customer_enrollments(user_id)
                completed = sum(1 for e in enrollments if e.get('completed', False))
                message = f"👋 Welcome back, {first_name}!\n\n"
                if enrollments:
                    message += f"📊 *Quick Stats:*\n• {len(enrollments)} active cards\n"
                    if completed > 0:
                        message += f"• 🎁 {completed} rewards ready!\n"
                    message += "\n"
                message += "Use the menu below 👇"
                await update.message.reply_text(message + BRAND_FOOTER, reply_markup=get_customer_keyboard(), parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Error getting enrollments: {e}")
                await update.message.reply_text(f"👋 Welcome back, {first_name}!\n\nUse the menu below 👇" + BRAND_FOOTER, reply_markup=get_customer_keyboard(), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user(update.effective_user.id)
    if user and user['user_type'] == 'merchant' and user.get('merchant_approved', False):
        keyboard = [[InlineKeyboardButton("📖 Getting Started", callback_data="help_merchant_start")], [InlineKeyboardButton("⭐ Managing Stamps", callback_data="help_stamps")], [InlineKeyboardButton("💡 Best Practices", callback_data="help_tips")]]
        message = "❓ *Merchant Help*\n\nChoose a topic or use the menu buttons below 👇"
    else:
        keyboard = [[InlineKeyboardButton("🎯 How to Collect Stamps", callback_data="help_customer_stamps")], [InlineKeyboardButton("🎁 How to Claim Rewards", callback_data="help_rewards")], [InlineKeyboardButton("🆔 Using Your ID", callback_data="help_id")]]
        message = "❓ *Help Center*\n\n*Quick Guide:*\n• Tap 💳 My Wallet to see your cards\n• Tap 🆔 Show My ID at checkout\n• Tap 📍 Find Stores to discover shops\n\nUse the menu buttons below for quick access!"
    await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    enrollments = await db.get_customer_enrollments(user_id)
    if not enrollments:
        keyboard = [[InlineKeyboardButton("🔍 Find Stores", callback_data="find_stores_wallet")]]
        await update.message.reply_text("💳 *Your Wallet is Empty*\n\nStart collecting loyalty cards from your favorite stores!" + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    await update.message.reply_text(f"💳 *Your Wallet* ({len(enrollments)} cards)" + BRAND_FOOTER, parse_mode="Markdown")
    for e in enrollments:
        try:
            img = generate_card_image(e['name'], e['stamps'], e['stamps_needed'])
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            progress_bar = generate_progress_bar(e['stamps'], e['stamps_needed'], 20)
            keyboard = []
            if e['completed']:
                caption = f"🎉 *{e['name']}*\n\n{progress_bar}\n✅ REWARD READY!"
                keyboard.append([InlineKeyboardButton("🎁 Claim Reward", callback_data=f"claim_reward_{e['campaign_id']}")])
            else:
                caption = f"📋 *{e['name']}*\n\n{progress_bar}\n{e['stamps']}/{e['stamps_needed']} stamps"
                keyboard.append([InlineKeyboardButton("⭐ Request Stamp", callback_data=f"request_{e['campaign_id']}")])
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            await update.message.reply_photo(photo=bio, caption=caption + BRAND_FOOTER, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error generating card: {e}")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(str(user_id))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    keyboard = [[InlineKeyboardButton("💳 View My Wallet", callback_data="view_wallet")], [InlineKeyboardButton("📍 Find Stores", callback_data="find_stores")]]
    await update.message.reply_photo(photo=bio, caption=f"🆔 *Your Customer ID*\n\nID: `{user_id}`\n\nShow this QR code to merchants when checking out!" + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        enrollments = await db.get_customer_enrollments(user_id)
        completed = [e for e in enrollments if e.get('completed', False)]
        if not completed:
            await update.message.reply_text("🎁 *No Rewards Ready Yet*\n\nKeep collecting stamps to unlock rewards!\nCheck your wallet to see your progress." + BRAND_FOOTER, parse_mode="Markdown")
            return
        message = f"🎁 *Your Rewards* ({len(completed)} ready!)\n\n"
        keyboard = []
        for reward in completed:
            message += f"✅ *{reward['name']}*\n🎯 {reward['stamps']}/{reward['stamps_needed']} stamps\n🎁 Reward: {reward.get('reward_description', 'Prize!')}\n\n"
            keyboard.append([InlineKeyboardButton(f"🎉 Claim: {reward['name'][:20]}", callback_data=f"claim_reward_{reward['campaign_id']}")])
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting rewards: {e}")
        await update.message.reply_text("❌ Error loading rewards." + BRAND_FOOTER, parse_mode="Markdown")

async def find_stores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with db.pool.acquire() as conn:
            stores = await conn.fetch("SELECT DISTINCT u.id, u.first_name, u.username, c.category, COUNT(c.id) as program_count FROM users u JOIN campaigns c ON c.merchant_id = u.id WHERE u.user_type = 'merchant' AND u.merchant_approved = TRUE AND c.active = TRUE GROUP BY u.id, u.first_name, u.username, c.category ORDER BY program_count DESC LIMIT 15")
        if not stores:
            await update.message.reply_text("🔍 *Find Stores*\n\nNo participating stores yet.\nCheck back soon for new merchants!" + BRAND_FOOTER, parse_mode="Markdown")
            return
        message = f"🔍 *Participating Stores* ({len(stores)})\n\n"
        keyboard = []
        for store in stores:
            store_name = store['first_name'] or store['username'] or f"Store {store['id']}"
            category = store.get('category', 'General')
            program_count = store['program_count']
            message += f"🏪 *{store_name}*\n📁 {category} • {program_count} program(s)\n\n"
            keyboard.append([InlineKeyboardButton(f"View: {store_name[:25]}", callback_data=f"view_store_{store['id']}")])
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error finding stores: {e}")
        await update.message.reply_text("❌ Error loading stores." + BRAND_FOOTER, parse_mode="Markdown")

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text("❌ Only approved merchants can view dashboard!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    try:
        async with db.pool.acquire() as conn:
            total_programs = await conn.fetchval("SELECT COUNT(*) FROM campaigns WHERE merchant_id = $1", user_id)
            active_programs = await conn.fetchval("SELECT COUNT(*) FROM campaigns WHERE merchant_id = $1 AND active = TRUE", user_id)
            total_enrollments = await conn.fetchval("SELECT COUNT(*) FROM enrollments e JOIN campaigns c ON e.campaign_id = c.id WHERE c.merchant_id = $1", user_id)
            completed_cards = await conn.fetchval("SELECT COUNT(*) FROM enrollments e JOIN campaigns c ON e.campaign_id = c.id WHERE c.merchant_id = $1 AND e.completed = TRUE", user_id)
        keyboard = [[InlineKeyboardButton("⏳ View Pending", callback_data="view_pending_dashboard")], [InlineKeyboardButton("📋 My Programs", callback_data="view_programs_dashboard")]]
        tip = random.choice(MERCHANT_TIPS)
        message = f"📊 *Merchant Dashboard*\n\n*Overview:*\n• Programs: {total_programs} ({active_programs} active)\n• Total Customers: {total_enrollments}\n• Completed Cards: {completed_cards}\n\n💡 *Tip:* {tip}"
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting dashboard: {e}")
        await update.message.reply_text("❌ Error loading dashboard." + BRAND_FOOTER, parse_mode="Markdown")

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text("❌ Only approved merchants can view pending requests!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    try:
        pending_requests = await db.get_pending_requests(user_id)
        if not pending_requests:
            await update.message.reply_text("⏳ *No Pending Requests*\n\nAll caught up! 🎉" + BRAND_FOOTER, parse_mode="Markdown")
            return
        message = f"⏳ *Pending Requests* ({len(pending_requests)})\n\n"
        keyboard = []
        for req in pending_requests[:10]:
            customer_name = req.get('customer_name', f"User {req['customer_id']}")
            campaign_name = req.get('campaign_name', 'Unknown')
            message += f"👤 {customer_name}\n📋 {campaign_name}\n⏰ {req.get('created_at', 'N/A')}\n\n"
            keyboard.append([InlineKeyboardButton(f"✅ Approve: {customer_name[:15]}", callback_data=f"approve_stamp_{req['id']}"), InlineKeyboardButton("❌ Deny", callback_data=f"deny_stamp_{req['id']}")])
        if len(pending_requests) > 10:
            message += f"_...and {len(pending_requests) - 10} more_"
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting pending requests: {e}")
        await update.message.reply_text("❌ Error loading pending requests." + BRAND_FOOTER, parse_mode="Markdown")

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text("❌ Only approved merchants can view programs!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    try:
        campaigns = await db.get_merchant_campaigns(user_id)
        if not campaigns:
            keyboard = [[InlineKeyboardButton("➕ Create First Program", callback_data="create_first_program")]]
            await update.message.reply_text("📋 *Your Programs*\n\nYou haven't created any programs yet.\nStart now to attract customers!" + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        message = f"📋 *Your Programs* ({len(campaigns)})\n\n"
        for camp in campaigns[:10]:
            status = "✅ Active" if camp.get('active', True) else "⏸️ Paused"
            message += f"*{camp['name']}*\n• {status} • {camp['stamps_needed']} stamps\n• Reward: {camp.get('reward_description', 'N/A')}\n\n"
        keyboard = [[InlineKeyboardButton("➕ Create New Program", callback_data="create_new_program")]]
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting campaigns: {e}")
        await update.message.reply_text("❌ Error loading programs." + BRAND_FOOTER, parse_mode="Markdown")

async def scan_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text("❌ Only approved merchants can scan customers!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    keyboard = [[InlineKeyboardButton("📸 How to Use Camera", callback_data="open_camera_scan")], [InlineKeyboardButton("🔢 Enter Customer ID", callback_data="manual_customer_id")]]
    message = "📸 *Scan Customer*\n\n*Quick Method:*\nUse: `/givestamp <customer_id> <campaign_id>`\n\n*Or choose an option below:*"
    await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def givestamp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text("❌ Only approved merchants can give stamps!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/givestamp <customer_id> <campaign_id>`\n\nExample: `/givestamp 123456789 1`\n\nOr use: 📸 Scan Customer from menu!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    try:
        customer_id = int(context.args[0])
        campaign_id = int(context.args[1])
        campaign = await db.get_campaign(campaign_id)
        if not campaign or campaign['merchant_id'] != user_id:
            await update.message.reply_text("❌ Campaign not found or you don't own it!" + BRAND_FOOTER, parse_mode="Markdown")
            return
        enrollment = await db.get_enrollment(campaign_id, customer_id)
        if not enrollment:
            await update.message.reply_text("❌ Customer not enrolled in this program!" + BRAND_FOOTER, parse_mode="Markdown")
            return
        await db.add_stamp(campaign_id, customer_id)
        new_enrollment = await db.get_enrollment(campaign_id, customer_id)
        progress_bar = generate_progress_bar(new_enrollment['stamps'], campaign['stamps_needed'], 20)
        message = f"✅ *Stamp Given!*\n\nCustomer: `{customer_id}`\nProgram: {campaign['name']}\n\n{progress_bar}\n{new_enrollment['stamps']}/{campaign['stamps_needed']} stamps"
        if new_enrollment.get('completed'):
            message += "\n\n🎉 *CARD COMPLETED!* Customer earned a reward!"
        await update.message.reply_text(message + BRAND_FOOTER, parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=customer_id, text=f"⭐ *New Stamp!*\n\nYou received a stamp from {campaign['name']}!\n\n{progress_bar}\n{new_enrollment['stamps']}/{campaign['stamps_needed']} stamps" + ("\n\n🎉 *REWARD READY!* Check 🎁 My Rewards" if new_enrollment.get('completed') else "") + BRAND_FOOTER, parse_mode="Markdown")
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Invalid customer ID or campaign ID!" + BRAND_FOOTER, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error giving stamp: {e}")
        await update.message.reply_text("❌ Error giving stamp." + BRAND_FOOTER, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access denied!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    try:
        async with db.pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            total_merchants = await conn.fetchval("SELECT COUNT(*) FROM users WHERE user_type = 'merchant'")
            pending_merchants = await conn.fetchval("SELECT COUNT(*) FROM users WHERE user_type = 'merchant' AND merchant_approved = FALSE")
            total_campaigns = await conn.fetchval("SELECT COUNT(*) FROM campaigns")
            active_campaigns = await conn.fetchval("SELECT COUNT(*) FROM campaigns WHERE active = TRUE")
            total_enrollments = await conn.fetchval("SELECT COUNT(*) FROM enrollments")
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        total_users = total_merchants = pending_merchants = 0
        total_campaigns = active_campaigns = total_enrollments = 0
    keyboard = [[InlineKeyboardButton(f"✅ Approve Merchants ({pending_merchants})", callback_data="admin_approve_merchants")], [InlineKeyboardButton("👥 User Management", callback_data="admin_users")]]
    message = f"👑 *Admin Control Panel*\n\n📊 *System Overview:*\n• Total Users: {total_users}\n• Merchants: {total_merchants}\n• Pending Approval: {pending_merchants}\n• Total Programs: {total_campaigns}\n• Active Programs: {active_campaigns}\n• Total Enrollments: {total_enrollments}\n\nChoose an action:"
    await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        async with db.pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            new_users_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '24 hours'")
            total_merchants = await conn.fetchval("SELECT COUNT(*) FROM users WHERE user_type = 'merchant'")
            total_campaigns = await conn.fetchval("SELECT COUNT(*) FROM campaigns")
        message = f"📊 *Detailed System Statistics*\n\n*Users*\n• Total: {total_users}\n• New (24h): {new_users_today}\n\n*Merchants*\n• Total: {total_merchants}\n\n*Programs*\n• Total: {total_campaigns}"
        await update.message.reply_text(message + BRAND_FOOTER, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await update.message.reply_text("❌ Error retrieving statistics." + BRAND_FOOTER)

async def manage_merchants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        async with db.pool.acquire() as conn:
            pending = await conn.fetch("SELECT id, username, first_name FROM users WHERE user_type = 'merchant' AND merchant_approved = FALSE ORDER BY created_at DESC LIMIT 10")
        if not pending:
            await update.message.reply_text("✅ No pending merchant applications!" + BRAND_FOOTER, parse_mode="Markdown")
            return
        keyboard = []
        for merchant in pending:
            name = merchant['first_name'] or merchant['username'] or f"User {merchant['id']}"
            keyboard.append([InlineKeyboardButton(f"✅ Approve: {name}", callback_data=f"approve_merchant_{merchant['id']}")])
        message = f"🏪 *Pending Merchant Applications*\n\nFound {len(pending)} pending application(s).\nTap to approve:"
        await update.message.reply_text(message + BRAND_FOOTER, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error getting pending merchants: {e}")
        await update.message.reply_text("❌ Error retrieving merchant applications." + BRAND_FOOTER)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    try:
        await query.answer()
    except:
        pass
    
    if data.startswith("settings_"):
        if data == "settings_notifications":
            try:
                async with db.pool.acquire() as conn:
                    current = await conn.fetchval("SELECT notification_enabled FROM user_preferences WHERE user_id = $1", user_id)
                    new_value = not current
                    await conn.execute("UPDATE user_preferences SET notification_enabled = $1 WHERE user_id = $2", new_value, user_id)
                await query.answer(f"Notifications {'enabled' if new_value else 'disabled'}!")
                await settings_menu(update, context)
            except:
                await query.answer("Error updating setting")
        elif data == "settings_marketing":
            try:
                async with db.pool.acquire() as conn:
                    current = await conn.fetchval("SELECT marketing_emails FROM user_preferences WHERE user_id = $1", user_id)
                    new_value = not current
                    await conn.execute("UPDATE user_preferences SET marketing_emails = $1 WHERE user_id = $2", new_value, user_id)
                await query.answer(f"Marketing emails {'enabled' if new_value else 'disabled'}!")
                await settings_menu(update, context)
            except:
                await query.answer("Error updating setting")
        elif data == "settings_data":
            try:
                async with db.pool.acquire() as conn:
                    current = await conn.fetchval("SELECT data_sharing FROM user_preferences WHERE user_id = $1", user_id)
                    new_value = not current
                    await conn.execute("UPDATE user_preferences SET data_sharing = $1 WHERE user_id = $2", new_value, user_id)
                await query.answer(f"Data sharing {'enabled' if new_value else 'disabled'}!")
                await settings_menu(update, context)
            except:
                await query.answer("Error updating setting")
        elif data == "settings_close":
            await query.message.delete()
    elif data.startswith("approve_merchant_"):
        if user_id not in ADMIN_IDS:
            await query.answer("Access denied!")
            return
        merchant_id = int(data.split("_")[2])
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE users SET merchant_approved = TRUE WHERE id = $1", merchant_id)
            await query.answer("✅ Merchant approved!")
            await manage_merchants(update, context)
        except:
            await query.answer("Error approving merchant")
    elif data == "start_tutorial":
        keyboard = [[InlineKeyboardButton("Next →", callback_data="tutorial_2")]]
        await query.message.edit_text("🎯 *Quick Tutorial (1/3)*\n\n*Step 1: Join a Program*\n\n• Find stores near you\n• Scan their QR code\n• Start collecting stamps!\n\nSimple as that! 🎉", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "tutorial_2":
        keyboard = [[InlineKeyboardButton("← Back", callback_data="start_tutorial")], [InlineKeyboardButton("Next →", callback_data="tutorial_3")]]
        await query.message.edit_text("🎯 *Quick Tutorial (2/3)*\n\n*Step 2: Collect Stamps*\n\n• Show your ID at checkout\n• Merchant scans your QR code\n• You get a stamp instantly!\n\nTrack your progress in 💳 My Wallet", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "tutorial_3":
        keyboard = [[InlineKeyboardButton("← Back", callback_data="tutorial_2")], [InlineKeyboardButton("✅ Got it!", callback_data="tutorial_complete")]]
        await query.message.edit_text("🎯 *Quick Tutorial (3/3)*\n\n*Step 3: Get Rewards*\n\n• Complete your card\n• Claim your reward in 🎁 My Rewards\n• Show proof to merchant\n• Enjoy your prize!\n\nReady to start? 🚀", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "tutorial_complete":
        await query.message.edit_text("✅ *Tutorial Complete!*\n\nYou're all set! Use the menu below to:\n• 📍 Find stores\n• 💳 View your wallet\n• 🆔 Show your ID\n\nHappy stamping! 🎉" + BRAND_FOOTER, parse_mode="Markdown")
    else:
        await query.answer("Action processed!")

async def send_notifications(app):
    while True:
        try:
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in notifications: {e}")
            await asyncio.sleep(5)

async def send_daily_summaries():
    pass

async def main():
    print("🚀 Starting StampMe Bot...")
    print("🔄 Clearing any existing bot instances...")
    for attempt in range(5):
        try:
            temp_app = ApplicationBuilder().token(TOKEN).build()
            await temp_app.initialize()
            for i in range(3):
                result = await temp_app.bot.delete_webhook(drop_pending_updates=True)
                print(f"    ✓ Webhook clear attempt {i+1}: {result}")
                await asyncio.sleep(2)
            await temp_app.shutdown()
            print(f"  ✓ Attempt {attempt + 1}: All clear")
            await asyncio.sleep(5)
            break
        except Exception as e:
            print(f"  ⚠️ Attempt {attempt + 1} failed: {e}")
            if attempt < 4:
                wait_time = (attempt + 1) * 3
                print(f"  ⏳ Waiting {wait_time} seconds before retry...")
                await asyncio.sleep(wait_time)
            else:
                print("\n❌ CRITICAL: Could not clear old instances after 5 attempts")
                return
    
    try:
        await db.connect()
        print("✅ Database connected")
        print("\n🔄 Running migrations...")
        await run_migrations(db.pool)
        print("✅ Migrations complete!\n")
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    await start_web_server()
    print("🤖 Building bot...")
    app = ApplicationBuilder().token(TOKEN).build()
    
    program_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newprogram", new_program_start), MessageHandler(filters.Regex("^➕ New Program$"), new_program_start)],
        states={
            PROGRAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, program_name_received)],
            PROGRAM_STAMPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, program_stamps_received)],
            PROGRAM_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, program_reward_received)],
            PROGRAM_CATEGORY: [CallbackQueryHandler(program_category_selected, pattern="^cat_")],
            PROGRAM_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, program_description_received), CallbackQueryHandler(program_description_received, pattern="^skip_description$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_program, pattern="^cancel_program$"), CommandHandler("cancel", cancel_program)],
        allow_reentry=True
    )
    
    app.add_handler(program_conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("mycampaigns", mycampaigns))
    app.add_handler(CommandHandler("givestamp", givestamp))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    await app.initialize()
    await app.start()
    print("📡 Starting polling...")
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    print("✅ Bot is running!")
    print(f"📱 Bot: @{BOT_USERNAME}")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    
    asyncio.create_task(send_notifications(app))
    scheduler.add_job(send_daily_summaries, 'cron', hour=18, minute=0)
    scheduler.start()
    
    print("\n🧪 Creating sample test data...")
    try:
        async with db.pool.acquire() as conn:
            test_merchant = await conn.fetchval("SELECT id FROM users WHERE id = 999999991 LIMIT 1")
            if not test_merchant:
                await conn.execute("INSERT INTO users (id, username, first_name, user_type, merchant_approved) VALUES (999999991, 'testcafe', 'Test Cafe', 'merchant', TRUE) ON CONFLICT (id) DO NOTHING")
                await conn.execute("INSERT INTO campaigns (merchant_id, name, stamps_needed, reward_description, category, description, active) VALUES (999999991, 'Coffee Lover Card', 8, 'Free Coffee', 'Food & Beverage', 'Get 8 stamps, get 1 free coffee!', TRUE) ON CONFLICT DO NOTHING")
                print("  ✓ Test merchant created (ID: 999999991)")
                print("  ✓ Test campaign created")
                print("  ℹ️  Use /start join_1 to test as customer")
            else:
                print("  ℹ️  Test data already exists")
    except Exception as e:
        logger.error(f"Error creating test data: {e}")
        print("  ⚠️  Could not create test data")
    
    print("\n" + "="*50)
    print("🎉 STAMPME BOT READY!")
    print("="*50)
    print("\n📋 TESTING GUIDE:")
    print("1. Start as admin: /start")
    print("2. Test merchant: ID 999999991")
    print("3. Join test program: /start join_1")
    print("4. View wallet: 💳 My Wallet")
    print("5. Show ID: 🆔 Show My ID")
    print("\n" + "="*50 + "\n")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

