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

# Conversation states for new program wizard
PROGRAM_NAME, PROGRAM_STAMPS, PROGRAM_REWARD, PROGRAM_DESCRIPTION, PROGRAM_CATEGORY = range(5)

# Initialize
db = StampMeDatabase(DATABASE_URL)
scheduler = AsyncIOScheduler()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== RATE LIMITING ====================

class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
        self.blocked_users = {}
    
    def check_rate_limit(self, user_id: int) -> tuple[bool, int]:
        """Check if user is within rate limits"""
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

# ==================== VISUAL KEYBOARDS ====================

def get_customer_keyboard():
    """Main keyboard for customers"""
    keyboard = [
        [KeyboardButton("💳 My Wallet"), KeyboardButton("📍 Find Stores")],
        [KeyboardButton("🆔 Show My ID"), KeyboardButton("🎁 My Rewards")],
        [KeyboardButton("⚙️ Settings"), KeyboardButton("❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_merchant_keyboard():
    """Main keyboard for merchants"""
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("⏳ Pending")],
        [KeyboardButton("📸 Scan Customer"), KeyboardButton("📋 My Programs")],
        [KeyboardButton("➕ New Program"), KeyboardButton("⚙️ Settings")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def get_admin_keyboard():
    """Main keyboard for admins"""
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

# ==================== AUTO-MIGRATION ====================

async def run_migrations(pool):
    """Run database migrations automatically on startup"""
    try:
        async with pool.acquire() as conn:
            print("  📝 Updating campaigns table...")
            await conn.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='campaigns' AND column_name='category'
                    ) THEN
                        ALTER TABLE campaigns ADD COLUMN category VARCHAR(50);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='campaigns' AND column_name='location_lat'
                    ) THEN
                        ALTER TABLE campaigns ADD COLUMN location_lat DECIMAL(10, 8);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='campaigns' AND column_name='location_lng'
                    ) THEN
                        ALTER TABLE campaigns ADD COLUMN location_lng DECIMAL(11, 8);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='campaigns' AND column_name='description'
                    ) THEN
                        ALTER TABLE campaigns ADD COLUMN description TEXT;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='campaigns' AND column_name='reward_description'
                    ) THEN
                        ALTER TABLE campaigns ADD COLUMN reward_description TEXT;
                    END IF;
                END $$;
            """)
            print("    ✓ Campaigns table updated")
            
            print("  📝 Updating users table...")
            await conn.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='users' AND column_name='onboarded'
                    ) THEN
                        ALTER TABLE users ADD COLUMN onboarded BOOLEAN DEFAULT FALSE;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='users' AND column_name='tutorial_completed'
                    ) THEN
                        ALTER TABLE users ADD COLUMN tutorial_completed BOOLEAN DEFAULT FALSE;
                    END IF;
                END $$;
            """)
            print("    ✓ Users table updated")
            
            print("  📝 Creating user_preferences table...")
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
            print("    ✓ user_preferences table ready")
            
            print("  📝 Creating merchant_settings table...")
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
            print("    ✓ merchant_settings table ready")
            
            print("  📝 Creating reward_claims table...")
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
            print("    ✓ reward_claims table ready")
            
            print("  📝 Creating audit_log table...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                    action VARCHAR(100) NOT NULL,
                    details JSONB,
                    ip_address INET,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            print("    ✓ audit_log table ready")
            
            print("  📝 Creating indexes...")
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_campaigns_category ON campaigns(category);
                CREATE INDEX IF NOT EXISTS idx_campaigns_active ON campaigns(active);
                CREATE INDEX IF NOT EXISTS idx_enrollments_customer ON enrollments(customer_id);
                CREATE INDEX IF NOT EXISTS idx_enrollments_completed ON enrollments(completed);
                CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_reward_claims_customer ON reward_claims(customer_id);
            """)
            print("    ✓ Indexes created")
            
            print("  🎉 All migrations completed successfully!")
            
    except Exception as e:
        print(f"  ❌ Migration error: {e}")
        import traceback
        traceback.print_exc()
        print("  ⚠️ Continuing bot startup...")

# ==================== SETTINGS HANDLERS ====================

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Settings menu with real functionality"""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    # Get or create preferences
    try:
        async with db.pool.acquire() as conn:
            prefs = await conn.fetchrow(
                "SELECT * FROM user_preferences WHERE user_id = $1",
                user_id
            )
            
            if not prefs:
                await conn.execute(
                    """INSERT INTO user_preferences (user_id) VALUES ($1)
                    ON CONFLICT (user_id) DO NOTHING""",
                    user_id
                )
                prefs = await conn.fetchrow(
                    "SELECT * FROM user_preferences WHERE user_id = $1",
                    user_id
                )
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
    
    message = (
        "⚙️ *Settings*\n\n"
        f"User ID: `{user_id}`\n"
        f"Account Type: {user['user_type'].title()}\n\n"
        "Configure your preferences below:"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(
            message + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            message + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

# ==================== NEW PROGRAM WIZARD (CONVERSATIONAL) ====================

async def new_program_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the new program wizard"""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text(
            "❌ Only approved merchants can create programs!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]]
    
    await update.message.reply_text(
        "🎯 *Create New Loyalty Program*\n\n"
        "Let's set up your program step by step.\n\n"
        "First, what's the name of your program?\n"
        "_Example: \"Buy 5 Get 1 Free\" or \"Coffee Club\"_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return PROGRAM_NAME

async def program_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive program name"""
    program_name = update.message.text.strip()
    
    if len(program_name) < 3:
        await update.message.reply_text(
            "⚠️ Program name is too short. Please enter at least 3 characters:",
            parse_mode="Markdown"
        )
        return PROGRAM_NAME
    
    if len(program_name) > 50:
        await update.message.reply_text(
            "⚠️ Program name is too long (max 50 characters). Please try again:",
            parse_mode="Markdown"
        )
        return PROGRAM_NAME
    
    context.user_data['program_name'] = program_name
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]]
    
    await update.message.reply_text(
        f"✅ Great! Program name: *{program_name}*\n\n"
        "How many stamps are needed to complete the card?\n"
        "_Enter a number between 3 and 20_\n"
        "_Example: 5, 8, 10_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return PROGRAM_STAMPS

async def program_stamps_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive stamps needed"""
    try:
        stamps = int(update.message.text.strip())
        
        if stamps < 3 or stamps > 20:
            await update.message.reply_text(
                "⚠️ Please enter a number between 3 and 20:",
                parse_mode="Markdown"
            )
            return PROGRAM_STAMPS
        
        context.user_data['stamps_needed'] = stamps
        
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]]
        
        await update.message.reply_text(
            f"✅ Perfect! {stamps} stamps to complete.\n\n"
            "What reward do customers get when they complete the card?\n"
            "_Example: \"Free Coffee\", \"20% Off\", \"Free Dessert\"_",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        return PROGRAM_REWARD
        
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a valid number:",
            parse_mode="Markdown"
        )
        return PROGRAM_STAMPS

async def program_reward_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive reward description"""
    reward = update.message.text.strip()
    
    if len(reward) < 3:
        await update.message.reply_text(
            "⚠️ Reward description is too short. Please enter at least 3 characters:",
            parse_mode="Markdown"
        )
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
    
    await update.message.reply_text(
        f"✅ Reward: *{reward}*\n\n"
        "What category best describes your business?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return PROGRAM_CATEGORY

async def program_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection"""
    query = update.callback_query
    await query.answer()
    
    category_map = {
        "cat_food": "Food & Beverage",
        "cat_beauty": "Beauty & Wellness",
        "cat_retail": "Retail & Shopping",
        "cat_fitness": "Fitness & Sports",
        "cat_entertainment": "Entertainment",
        "cat_services": "Services"
    }
    
    category = category_map.get(query.data, "Other")
    context.user_data['category'] = category
    
    keyboard = [
        [InlineKeyboardButton("⏭️ Skip", callback_data="skip_description")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_program")]
    ]
    
    await query.message.edit_text(
        f"✅ Category: *{category}*\n\n"
        "Finally, add a short description (optional):\n"
        "_Tell customers what makes your program special!_\n"
        "_You can skip this step._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return PROGRAM_DESCRIPTION

async def program_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive description and create program"""
    if update.callback_query:
        await update.callback_query.answer()
        description = None
        message = update.callback_query.message
    else:
        description = update.message.text.strip()
        if len(description) > 200:
            await update.message.reply_text(
                "⚠️ Description is too long (max 200 characters). Please try again:",
                parse_mode="Markdown"
            )
            return PROGRAM_DESCRIPTION
        message = update.message
    
    context.user_data['description'] = description
    
    # Create the campaign
    user_id = update.effective_user.id
    
    try:
        campaign_id = await db.create_campaign(
            merchant_id=user_id,
            name=context.user_data['program_name'],
            stamps_needed=context.user_data['stamps_needed'],
            reward_description=context.user_data['reward_description'],
            category=context.user_data.get('category'),
            description=description
        )
        
        # Generate QR code
        bot_username = BOT_USERNAME
        join_link = f"https://t.me/{bot_username}?start=join_{campaign_id}"
        
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
        
        summary = (
            "🎉 *Program Created Successfully!*\n\n"
            f"📝 Name: *{context.user_data['program_name']}*\n"
            f"⭐ Stamps: {context.user_data['stamps_needed']}\n"
            f"🎁 Reward: {context.user_data['reward_description']}\n"
            f"📁 Category: {context.user_data.get('category', 'N/A')}\n"
        )
        
        if description:
            summary += f"📄 Description: {description}\n"
        
        summary += f"\n🔗 Share Link:\n`{join_link}`\n\n"
        summary += "👆 Print this QR code and display it in your store!"
        
        await message.reply_photo(
            photo=bio,
            caption=summary + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        # Clear user data
        context.user_data.clear()
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        await message.reply_text(
            "❌ Error creating program. Please try again later." + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def cancel_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel program creation"""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    
    await query.message.edit_text(
        "❌ Program creation cancelled." + BRAND_FOOTER,
        parse_mode="Markdown"
    )
    
    return ConversationHandler.END

# ==================== SCAN CUSTOMER ====================

async def scan_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan customer with camera instructions"""
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    if not user or user['user_type'] != 'merchant' or not user.get('merchant_approved', False):
        await update.message.reply_text(
            "❌ Only approved merchants can scan customers!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("📸 Open Camera", callback_data="open_camera_scan")],
        [InlineKeyboardButton("🔢 Enter Customer ID", callback_data="manual_customer_id")],
        [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
    ]
    
    message = (
        "📸 *Scan Customer*\n\n"
        "*Option 1: Use Camera*\n"
        "1. Tap 'Open Camera' below\n"
        "2. Point at customer's QR code\n"
        "3. Bot will read the ID automatically\n\n"
        "*Option 2: Manual Entry*\n"
        "• Ask customer for their ID number\n"
        "• Enter it manually\n\n"
        "Choose an option:"
    )
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ==================== ADMIN PANEL ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel with full functionality"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "❌ Access denied!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    try:
        async with db.pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            total_merchants = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE user_type = 'merchant'"
            )
            pending_merchants = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE user_type = 'merchant' AND merchant_approved = FALSE"
            )
            total_campaigns = await conn.fetchval("SELECT COUNT(*) FROM campaigns")
            active_campaigns = await conn.fetchval(
                "SELECT COUNT(*) FROM campaigns WHERE active = TRUE"
            )
            total_enrollments = await conn.fetchval("SELECT COUNT(*) FROM enrollments")
    except Exception as e:
        logger.error(f"Error getting admin stats: {e}")
        total_users = total_merchants = pending_merchants = 0
        total_campaigns = active_campaigns = total_enrollments = 0
    
    keyboard = [
        [InlineKeyboardButton(f"✅ Approve Merchants ({pending_merchants})", callback_data="admin_approve_merchants")],
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("🏪 Campaign Management", callback_data="admin_campaigns")],
        [InlineKeyboardButton("📊 Detailed Analytics", callback_data="admin_analytics")],
        [InlineKeyboardButton("📢 Send Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔧 System Settings", callback_data="admin_settings")]
    ]
    
    message = (
        "👑 *Admin Control Panel*\n\n"
        "📊 *System Overview:*\n"
        f"• Total Users: {total_users}\n"
        f"• Merchants: {total_merchants}\n"
        f"• Pending Approval: {pending_merchants}\n"
        f"• Total Programs: {total_campaigns}\n"
        f"• Active Programs: {active_campaigns}\n"
        f"• Total Enrollments: {total_enrollments}\n\n"
        "Choose an action:"
    )
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ==================== MESSAGE HANDLER (TAP-BASED) ====================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages from reply keyboard"""
    text = update.message.text
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    allowed, remaining = rate_limiter.check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            "⚠️ Please slow down! Wait a moment.",
            reply_markup=get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard()
        )
        return
    
    # Admin commands
    if user_id in ADMIN_IDS:
        if text == "👑 Admin Panel":
            await admin_panel(update, context)
            return
        elif text == "📊 System Stats":
            await system_stats(update, context)
            return
        elif text == "👥 Manage Users":
            await manage_users(update, context)
            return
        elif text == "🏪 Manage Merchants":
            await manage_merchants(update, context)
            return
        elif text == "📢 Broadcast":
            await broadcast_menu(update, context)
            return
    
    # Customer commands
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
    # Merchant commands
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
        keyboard = get_admin_keyboard() if user_id in ADMIN_IDS else (
            get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard()
        )
        await update.message.reply_text(
            "👆 Please use the menu buttons below!",
            reply_markup=keyboard
        )


