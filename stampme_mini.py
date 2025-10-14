import os
import asyncio
import io
import random
from datetime import datetime, timedelta
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
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
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

def get_merchant_keyboard():
    """Main keyboard for merchants"""
    keyboard = [
        [KeyboardButton("📊 Dashboard"), KeyboardButton("⏳ Pending")],
        [KeyboardButton("👥 Scan Customer"), KeyboardButton("📋 My Programs")],
        [KeyboardButton("➕ New Program"), KeyboardButton("⚙️ Settings")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

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

# ==================== MESSAGE HANDLER (TAP-BASED) ====================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages from reply keyboard"""
    text = update.message.text
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    
    # Rate limiting
    allowed, remaining = rate_limiter.check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            "⚠️ Please slow down! Wait a moment.",
            reply_markup=get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard()
        )
        return
    
    # Customer actions
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
    
    # Merchant actions
    elif text == "📊 Dashboard":
        await dashboard(update, context)
    
    elif text == "⏳ Pending":
        await pending(update, context)
    
    elif text == "👥 Scan Customer":
        await scan_customer_menu(update, context)
    
    elif text == "📋 My Programs":
        await mycampaigns(update, context)
    
    elif text == "➕ New Program":
        await new_program_wizard(update, context)
    
    else:
        await update.message.reply_text(
            "👆 Please use the menu buttons below!",
            reply_markup=get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard()
        )

# ==================== COMMAND HANDLERS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with keyboard"""
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
                    await update.message.reply_text(
                        "😕 *Program Not Available*\n\n"
                        "This loyalty program is no longer active." + BRAND_FOOTER,
                        reply_markup=get_customer_keyboard(),
                        parse_mode="Markdown"
                    )
                    return
                
                enrollment = await db.get_enrollment(campaign_id, user_id)
                
                if not enrollment:
                    await db.enroll_customer(campaign_id, user_id)
                    keyboard = [[InlineKeyboardButton("⭐ Request First Stamp", callback_data=f"request_{campaign_id}")]]
                    
                    await update.message.reply_text(
                        f"🎉 *Welcome!*\n\n"
                        f"You joined: *{campaign['name']}*\n\n"
                        f"🎯 Collect {campaign['stamps_needed']} stamps for rewards!\n\n"
                        f"Use the menu below to navigate 👇" + BRAND_FOOTER,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                    
                    await update.message.reply_text(
                        "Quick access menu:",
                        reply_markup=get_customer_keyboard()
                    )
                    
                    if not user.get('onboarded'):
                        await db.mark_user_onboarded(user_id)
                    
                else:
                    progress_bar = generate_progress_bar(enrollment['stamps'], campaign['stamps_needed'], 20)
                    remaining = campaign['stamps_needed'] - enrollment['stamps']
                    
                    await update.message.reply_text(
                        f"👋 *Welcome Back!*\n\n"
                        f"*{campaign['name']}*\n"
                        f"{progress_bar}\n\n"
                        f"Progress: {enrollment['stamps']}/{campaign['stamps_needed']} stamps\n"
                        f"Just {remaining} more! 🎁" + BRAND_FOOTER,
                        reply_markup=get_customer_keyboard(),
                        parse_mode="Markdown"
                    )
                return
            except Exception as e:
                logger.error(f"Error joining campaign: {e}")
                return
    
    # Regular start
    if user and user['user_type'] == 'merchant':
        if user['merchant_approved']:
            pending_count = await db.get_pending_count(user_id)
            
            message = f"👋 Welcome back, {first_name}!\n\n"
            if pending_count > 0:
                message += f"⚠️ {pending_count} pending requests\n\n"
            message += "Use the menu below 👇"
            
            await update.message.reply_text(
                message + BRAND_FOOTER,
                reply_markup=get_merchant_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "🏪 *Merchant Application Pending*\n\n"
                "Your account is being reviewed.\n"
                "You'll be notified within 24 hours!" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
    else:
        # Customer welcome
        is_new = not user.get('onboarded', False)
        
        if is_new:
            keyboard = [
                [InlineKeyboardButton("🎯 Quick Tutorial", callback_data="start_tutorial")],
                [InlineKeyboardButton("🔍 Find Stores", callback_data="find_stores")]
            ]
            
            await update.message.reply_text(
                f"👋 Hi {first_name}!\n\n"
                f"Welcome to *StampMe* 💙\n\n"
                f"Your smart digital loyalty card!\n\n"
                f"✨ *Features:*\n"
                f"• Collect stamps at stores\n"
                f"• Track progress in real-time\n"
                f"• Earn rewards automatically\n"
                f"• No more paper cards!\n\n"
                f"Use the menu below to get started 👇" + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            
            await update.message.reply_text(
                "Tap these buttons anytime:",
                reply_markup=get_customer_keyboard()
            )
            
            await db.mark_user_onboarded(user_id)
        else:
            enrollments = await db.get_customer_enrollments(user_id)
            completed = sum(1 for e in enrollments if e['completed'])
            
            message = f"👋 Welcome back, {first_name}!\n\n"
            if enrollments:
                message += f"📊 *Quick Stats:*\n"
                message += f"• {len(enrollments)} active cards\n"
                if completed > 0:
                    message += f"• 🎁 {completed} rewards ready!\n"
                message += "\n"
            
            message += "Use the menu below 👇"
            
            await update.message.reply_text(
                message + BRAND_FOOTER,
                reply_markup=get_customer_keyboard(),
                parse_mode="Markdown"
            )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    user = await db.get_user(update.effective_user.id)
    
    if user and user['user_type'] == 'merchant' and user['merchant_approved']:
        keyboard = [
            [InlineKeyboardButton("📖 Getting Started", callback_data="help_merchant_start")],
            [InlineKeyboardButton("⭐ Managing Stamps", callback_data="help_stamps")],
            [InlineKeyboardButton("💡 Best Practices", callback_data="help_tips")]
        ]
        
        await update.message.reply_text(
            "❓ *Merchant Help Center*\n\n"
            "Choose a topic 👇" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        keyboard = [
            [InlineKeyboardButton("🎯 How to Collect Stamps", callback_data="help_customer_stamps")],
            [InlineKeyboardButton("🎁 How to Claim Rewards", callback_data="help_rewards")],
            [InlineKeyboardButton("🆔 Using Your ID", callback_data="help_id")]
        ]
        
        await update.message.reply_text(
            "❓ *Help Center*\n\n"
            "What do you need help with? 👇" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show wallet"""
    user_id = update.effective_user.id
    enrollments = await db.get_customer_enrollments(user_id)
    
    if not enrollments:
        keyboard = [[InlineKeyboardButton("🔍 Find Stores", callback_data="find_stores")]]
        await update.message.reply_text(
            "💳 *Your Wallet is Empty*\n\n"
            "You haven't joined any programs yet!\n\n"
            "Find stores to start collecting stamps 🎯" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    await update.message.reply_text(
        f"💳 *Your Wallet* ({len(enrollments)} cards)" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
    
    for e in enrollments:
        try:
            img = generate_card_image(e['name'], e['stamps'], e['stamps_needed'])
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            
            progress_bar = generate_progress_bar(e['stamps'], e['stamps_needed'], 20)
            percentage = int((e['stamps'] / e['stamps_needed']) * 100) if e['stamps_needed'] > 0 else 0
            
            if e['completed']:
                caption = (
                    f"🎉 *{e['name']}*\n\n"
                    f"{progress_bar} 100%\n\n"
                    f"✅ *REWARD READY!*\n\n"
                    f"Show this at the store to claim!"
                )
                keyboard = [[InlineKeyboardButton("🎁 How to Claim", callback_data=f"claim_help_{e['campaign_id']}")]]
            else:
                remaining = e['stamps_needed'] - e['stamps']
                caption = (
                    f"📋 *{e['name']}*\n\n"
                    f"{progress_bar} {percentage}%\n\n"
                    f"✅ {e['stamps']}/{e['stamps_needed']} stamps\n"
                    f"⏳ {remaining} more to go!\n\n"
                    f"Keep collecting! 💪"
                )
                keyboard = [[InlineKeyboardButton("⭐ Request Stamp", callback_data=f"request_{e['campaign_id']}")]]
            
            await update.message.reply_photo(
                photo=bio,
                caption=caption + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error showing card: {e}")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show customer ID card"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(str(user_id))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    card_width, card_height = 800, 500
    card = Image.new('RGB', (card_width, card_height), color='#6366f1')
    draw = ImageDraw.Draw(card)
    
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        name_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except:
        title_font = name_font = text_font = ImageFont.load_default()
    
    qr_img = qr_img.resize((200, 200))
    card.paste(qr_img, (550, 150))
    
    draw.text((40, 40), "StampMe", fill='white', font=title_font)
    draw.text((40, 100), "CUSTOMER ID", fill='#fbbf24', font=text_font)
    draw.text((40, 180), first_name, fill='white', font=name_font)
    
    if username:
        draw.text((40, 230), f"@{username}", fill='#e0e0e0', font=text_font)
    
    draw.text((40, 280), f"ID: {user_id}", fill='white', font=text_font)
    draw.text((40, 420), "Show this at checkout", fill='white', font=text_font)
    
    bio = io.BytesIO()
    card.save(bio, 'PNG')
    bio.seek(0)
    
    caption = (
        f"🆔 *Your StampMe ID*\n\n"
        f"👤 {first_name}\n"
        f"🔢 ID: `{user_id}`\n\n"
        f"✨ *How to use:*\n"
        f"1️⃣ Show this card to the cashier\n"
        f"2️⃣ They scan the QR code\n"
        f"3️⃣ Get stamps instantly!" + BRAND_FOOTER
    )
    
    await update.message.reply_photo(
        photo=bio,
        caption=caption,
        parse_mode="Markdown"
    )

async def find_stores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find stores"""
    async with db.pool.acquire() as conn:
        stores = await conn.fetch("""
            SELECT DISTINCT
                c.id, c.name, c.stamps_needed, c.category,
                u.first_name as merchant_name,
                COUNT(DISTINCT e.customer_id) as total_customers
            FROM campaigns c
            JOIN users u ON c.merchant_id = u.id
            LEFT JOIN enrollments e ON c.id = e.campaign_id
            WHERE c.active = TRUE
            GROUP BY c.id, c.name, c.stamps_needed, c.category, u.first_name
            ORDER BY total_customers DESC
            LIMIT 10
        """)
    
    if not stores:
        await update.message.reply_text(
            "😕 *No Stores Yet*\n\n"
            "We're onboarding merchants daily!\n"
            "Check back soon! 🚀" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    await update.message.reply_text(
        f"🔍 *Find Stores*\n\n"
        f"Found {len(stores)} participating stores!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
    
    for store in stores:
        popularity = "🔥🔥🔥" if store['total_customers'] > 50 else "🔥🔥" if store['total_customers'] > 20 else "🔥"
        
        message = (
            f"🏪 *{store['name']}*\n\n"
            f"👤 By: {store['merchant_name']}\n"
            f"🎯 Collect {store['stamps_needed']} stamps\n"
            f"👥 {store['total_customers']} customers\n"
            f"{popularity} Popularity"
        )
        
        if store['category']:
            message += f"\n📁 Category: #{store['category']}"
        
        keyboard = [[InlineKeyboardButton("🎯 Join Program", callback_data=f"join_{store['id']}")]]
        
        await update.message.reply_text(
            message + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show rewards"""
    user_id = update.effective_user.id
    
    async with db.pool.acquire() as conn:
        ready_rewards = await conn.fetch("""
            SELECT c.id, c.name, u.first_name as merchant_name
            FROM enrollments e
            JOIN campaigns c ON e.campaign_id = c.id
            JOIN users u ON c.merchant_id = u.id
            WHERE e.customer_id = $1 AND e.completed = true
        """, user_id)
    
    if not ready_rewards:
        await update.message.reply_text(
            "🎁 *No Rewards Ready Yet*\n\n"
            "Keep collecting stamps! 💪" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    await update.message.reply_text(
        f"🎉 *{len(ready_rewards)} Rewards Ready!*\n\n"
        "Show these at the store to claim 👇" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
    
    for reward in ready_rewards:
        keyboard = [[InlineKeyboardButton("📍 Store Location", callback_data=f"store_loc_{reward['id']}")]]
        
        await update.message.reply_text(
            f"🎁 *{reward['name']}*\n"
            f"🏪 {reward['merchant_name']}\n\n"
            f"█████████████████████ 100%\n\n"
            f"✅ REWARD READY TO CLAIM!" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Settings menu"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("🔔 Notifications", callback_data="toggle_notif")],
        [InlineKeyboardButton("🔒 Privacy & Data", callback_data="privacy_settings")],
        [InlineKeyboardButton("📥 Download My Data", callback_data="download_data")]
    ]
    
    await update.message.reply_text(
        "⚙️ *Settings*\n\n"
        "Manage your preferences 👇" + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Merchant dashboard"""
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text(
            "⚠️ Merchant approval required" + BRAND_FOOTER,
            reply_markup=get_merchant_keyboard()
        )
        return
    
    campaigns = await db.get_merchant_campaigns(user_id)
    pending_count = await db.get_pending_count(user_id)
    today_stats = await db.get_daily_stats(user_id)
    
    total_customers = sum(c.get('total_joins', 0) for c in campaigns)
    total_completions = sum(c.get('total_completions', 0) for c in campaigns)
    
    message = (
        f"📊 *Your Dashboard*\n\n"
        f"📅 *Today:*\n"
        f"• Visits: {today_stats['visits']}\n"
        f"• Stamps: {today_stats['stamps_given']}\n"
        f"• Rewards: {today_stats['rewards_claimed']}\n\n"
        f"📈 *Overall:*\n"
        f"• Programs: {len(campaigns)}\n"
        f"• Customers: {total_customers}\n"
        f"• Completed: {total_completions}\n"
    )
    
    if pending_count > 0:
        message += f"\n⚠️ *{pending_count} pending requests!*"
    
    keyboard = [
        [InlineKeyboardButton(f"⏳ Pending ({pending_count})", callback_data="show_pending")],
        [InlineKeyboardButton("📋 My Programs", callback_data="my_campaigns")]
    ]
    
    if pending_count > 0:
        keyboard.insert(0, [InlineKeyboardButton(f"✅ Approve All", callback_data="approve_all")])
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Merchant dashboard"""
user_id = update.effective_user.id
if not await db.is_merchant_approved(user_id):
    await update.message.reply_text(
        "⚠️ Merchant approval required" + BRAND_FOOTER,
        reply_markup=get_merchant_keyboard()
    )
    return

campaigns = await db.get_merchant_campaigns(user_id)
pending_count = await db.get_pending_count(user_id)
today_stats = await db.get_daily_stats(user_id)

total_customers = sum(c.get('total_joins', 0) for c in campaigns)
total_completions = sum(c.get('total_completions', 0) for c in campaigns)

message = (
    f"📊 *Your Dashboard*\n\n"
    f"📅 *Today:*\n"
    f"• Visits: {today_stats['visits']}\n"
    f"• Stamps: {today_stats['stamps_given']}\n"
    f"• Rewards: {today_stats['rewards_claimed']}\n\n"
    f"📈 *Overall:*\n"
    f"• Programs: {len(campaigns)}\n"
    f"• Customers: {total_customers}\n"
    f"• Completed: {total_completions}\n"
)

if pending_count > 0:
    message += f"\n⚠️ *{pending_count} pending requests!*"

keyboard = [
    [InlineKeyboardButton(f"⏳ Pending ({pending_count})", callback_data="show_pending")],
    [InlineKeyboardButton("📋 My Programs", callback_data="my_campaigns")]
]

if pending_count > 0:
    keyboard.insert(0, [InlineKeyboardButton(f"✅ Approve All", callback_data="approve_all")])

await update.message.reply_text(
    message + BRAND_FOOTER,
    reply_markup=InlineKeyboardMarkup(keyboard),
    parse_mode="Markdown"
)
async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Show pending requests"""
user_id = update.effective_user.id
requests = await db.get_pending_requests(user_id)
if not requests:
    await update.message.reply_text(
        "📭 *No Pending Requests*\n\n"
        "You're all caught up!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
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
    f"⏳ *Pending Requests ({len(requests)})*\n\n"
    f"Tap to review 👇" + BRAND_FOOTER,
    reply_markup=InlineKeyboardMarkup(keyboard),
    parse_mode="Markdown"
)
async def scan_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Scan customer menu"""
user_id = update.effective_user.id
if not await db.is_merchant_approved(user_id):
    await update.message.reply_text(
        "⚠️ Merchant approval required" + BRAND_FOOTER,
        reply_markup=get_merchant_keyboard()
    )
    return

async with db.pool.acquire() as conn:
    recent_customers = await conn.fetch("""
        SELECT DISTINCT
            u.id, u.first_name, u.username,
            MAX(sr.created_at) as last_visit
        FROM stamp_requests sr
        JOIN users u ON sr.customer_id = u.id
        JOIN campaigns c ON sr.campaign_id = c.id
        WHERE c.merchant_id = $1
        AND sr.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY u.id, u.first_name, u.username
        ORDER BY last_visit DESC
        LIMIT 10
    """, user_id)

if not recent_customers:
    keyboard = [
        [InlineKeyboardButton("📖 How to Scan", callback_data="scan_tutorial")],
        [InlineKeyboardButton("🔍 Search Customer", callback_data="search_customer")]
    ]
    
    await update.message.reply_text(
        "👥 *Scan Customer*\n\n"
        "No recent customers yet.\n\n"
        "Ask customer to show their ID (/myid)\n"
        "Or use the search option 👇" + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return

await update.message.reply_text(
    f"👥 *Recent Customers*\n\n"
    f"Tap a customer to add stamps 👇" + BRAND_FOOTER,
    parse_mode="Markdown"
)

for customer in recent_customers:
    async with db.pool.acquire() as conn:
        progress = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_cards,
                SUM(e.stamps) as total_stamps,
                COUNT(*) FILTER (WHERE e.completed = true) as rewards_ready
            FROM enrollments e
            JOIN campaigns c ON e.campaign_id = c.id
            WHERE e.customer_id = $1 AND c.merchant_id = $2
        """, customer['id'], user_id)
    
    customer_name = f"{customer['first_name']}"
    if customer['username']:
        customer_name += f" @{customer['username']}"
    
    card_message = (
        f"👤 *{customer['first_name']}*\n"
        f"{'@' + customer['username'] if customer['username'] else ''}\n\n"
        f"📊 Cards: {progress['total_cards']}\n"
        f"⭐ Stamps: {progress['total_stamps']}\n"
    )
    
    if progress['rewards_ready'] > 0:
        card_message += f"🎁 {progress['rewards_ready']} rewards ready!\n"
    
    keyboard = [[InlineKeyboardButton("⭐ Add Stamp", callback_data=f"quickstamp_{customer['id']}")]]
    
    if progress['rewards_ready'] > 0:
        keyboard.append([InlineKeyboardButton("🎁 Clear Reward", callback_data=f"quickreward_{customer['id']}")])
    
    await update.message.reply_text(
        card_message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""List campaigns"""
campaigns = await db.get_merchant_campaigns(update.effective_user.id)
if not campaigns:
    await update.message.reply_text(
        "📭 *No Programs Yet*\n\n"
        "Create your first program:\n"
        "Tap '➕ New Program' in the menu!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
    return

message = f"📋 *Your Programs* ({len(campaigns)})\n\n"
keyboard = []

for c in campaigns:
    message += f"*{c['name']}*\n"
    message += f"  🎯 {c['stamps_needed']} stamps\n"
    message += f"  👥 {c.get('total_joins', 0)} customers\n\n"
    
    keyboard.append([InlineKeyboardButton(f"📱 {c['name']}", callback_data=f"campaign_detail_{c['id']}")])

await update.message.reply_text(
    message + BRAND_FOOTER,
    reply_markup=InlineKeyboardMarkup(keyboard),
    parse_mode="Markdown"
)
async def new_program_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Start program creation wizard"""
user_id = update.effective_user.id
if not await db.is_merchant_approved(user_id):
    await update.message.reply_text(
        "⚠️ Merchant approval required" + BRAND_FOOTER,
        reply_markup=get_merchant_keyboard()
    )
    return

keyboard = [
    [InlineKeyboardButton("📝 Start Creating", callback_data="wizard_step1")],
    [InlineKeyboardButton("« Cancel", callback_data="cancel_wizard")]
]

await update.message.reply_text(
    "➕ *Create New Program*\n\n"
    "Let's create your loyalty program in 3 easy steps!\n\n"
    "📝 Step 1: Program name\n"
    "🎯 Step 2: Number of stamps\n"
    "🎁 Step 3: Rewards\n\n"
    "Ready? Let's go! 🚀" + BRAND_FOOTER,
    reply_markup=InlineKeyboardMarkup(keyboard),
    parse_mode="Markdown"
)
async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Create campaign (legacy command)"""
user_id = update.effective_user.id
if not await db.is_merchant_approved(user_id):
    await update.message.reply_text("⚠️ Merchant approval required" + BRAND_FOOTER)
    return

if len(context.args) < 2:
    await update.message.reply_text(
        "📋 *Create Program*\n\n"
        "*Usage:* `/newcampaign <name> <stamps>`\n"
        "*Example:* `/newcampaign Coffee 5`" + BRAND_FOOTER,
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
        f"✅ *Program Created!*\n\n"
        f"📋 {name}\n"
        f"🎯 {stamps_needed} stamps\n"
        f"🆔 ID: `{campaign_id}`" + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
except Exception as e:
    logger.error(f"Error creating campaign: {e}")
    await update.message.reply_text("Error creating program" + BRAND_FOOTER)
    async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Get QR code"""
if not context.args:
await update.message.reply_text("Usage: /getqr <campaign_id>" + BRAND_FOOTER, parse_mode="Markdown")
return
try:
    campaign_id = int(context.args[0])
    campaign = await db.get_campaign(campaign_id)
    
    if not campaign or campaign['merchant_id'] != update.effective_user.id:
        await update.message.reply_text("Campaign not found" + BRAND_FOOTER)
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
        caption=f"📱 *{campaign['name']}*\n\n🎯 {campaign['stamps_needed']} stamps\n\nLink: `{link}`" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
except Exception as e:
    logger.error(f"Error generating QR: {e}")
    async def givestamp(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Give stamp directly (legacy)"""
await update.message.reply_text(
"👉 Use the new menu!\n\n"
"Tap '👥 Scan Customer' in the menu below for easier stamp management!" + BRAND_FOOTER,
reply_markup=get_merchant_keyboard()
)
async def clearreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Clear reward (legacy)"""
await update.message.reply_text(
"👉 Use the new menu!\n\n"
"Tap '👥 Scan Customer' to manage rewards easily!" + BRAND_FOOTER,
reply_markup=get_merchant_keyboard()
)
async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Add reward tier"""
if len(context.args) < 3:
await update.message.reply_text(
"🎁 Add Reward\n\n"
"Usage: /addreward <id> <stamps> <reward>\n"
"Example: /addreward 1 5 Free Coffee" + BRAND_FOOTER,
parse_mode="Markdown"
)
return
try:
    campaign_id = int(context.args[0])
    stamps_req = int(context.args[1])
    reward = " ".join(context.args[2:])
    
    campaign = await db.get_campaign(campaign_id)
    if not campaign or campaign['merchant_id'] != update.effective_user.id:
        await update.message.reply_text("Campaign not found" + BRAND_FOOTER)
        return
    
    await db.add_reward_tier(campaign_id, stamps_req, reward)
    
    await update.message.reply_text(
        f"✅ *Reward Added!*\n\n"
        f"📋 {campaign['name']}\n"
        f"🎯 {stamps_req} stamps: {reward}" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
except Exception as e:
    logger.error(f"Error adding reward: {e}")
    async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Show stats"""
await update.message.reply_text(
"👉 Check your dashboard!\n\n"
"Tap '📊 Dashboard' in the menu for detailed stats!" + BRAND_FOOTER,
reply_markup=get_merchant_keyboard()
)
async def share(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Share link"""
if not context.args:
await update.message.reply_text("Usage: /share <campaign_id>" + BRAND_FOOTER, parse_mode="Markdown")
return
try:
    campaign_id = int(context.args[0])
    campaign = await db.get_campaign(campaign_id)
    
    if not campaign:
        await update.message.reply_text("Campaign not found" + BRAND_FOOTER)
        return
    
    link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
    
    await update.message.reply_text(
        f"🎁 *Share Your Program*\n\n"
        f"📋 {campaign['name']}\n\n"
        f"Share this link:\n`{link}`" + BRAND_FOOTER,
        parse_mode="Markdown"
    )
except Exception as e:
    logger.error(f"Error sharing: {e}")
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
"""Handle all button callbacks"""
query = update.callback_query
try:
    await query.answer()
except:
    pass

data = query.data
user_id = query.from_user.id

logger.info(f"Button clicked: {data} by user {user_id}")

try:
    # Show wallet
    if data == "show_wallet":
        await query.message.reply_text("Opening wallet..." + BRAND_FOOTER)
        # Trigger wallet command
        return
    
    # Become merchant
    elif data == "request_merchant":
        await db.request_merchant_access(user_id)
        
        for admin_id in ADMIN_IDS:
            try:
                await db.queue_notification(
                    admin_id,
                    f"🏪 New merchant request from {query.from_user.first_name}"
                )
            except:
                pass
        
        await query.edit_message_text(
            "⏳ *Request Sent!*\n\n"
            "You'll be notified within 24 hours!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    # Find stores
    elif data == "find_stores":
        await query.message.reply_text("Loading stores..." + BRAND_FOOTER)
        return
    
    # Join campaign
    elif data.startswith("join_"):
        campaign_id = int(data.split("_")[1])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign or not campaign['active']:
            await query.edit_message_text("This program is no longer available" + BRAND_FOOTER)
            return
        
        enrollment = await db.get_enrollment(campaign_id, user_id)
        
        if enrollment:
            await query.edit_message_text(
                f"✅ You're already a member of {campaign['name']}!" + BRAND_FOOTER
            )
            return
        
        await db.enroll_customer(campaign_id, user_id)
        
        keyboard = [[InlineKeyboardButton("💳 View Card", callback_data="show_wallet")]]
        
        await query.edit_message_text(
            f"🎉 *JOINED!*\n\n"
            f"Welcome to *{campaign['name']}*!\n\n"
            f"🎯 Collect {campaign['stamps_needed']} stamps\n\n"
            f"Your card is in your wallet 💳" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Request stamp
    elif data.startswith("request_"):
        campaign_id = int(data.split("_")[1])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign:
            await query.edit_message_text("Campaign not found" + BRAND_FOOTER)
            return
        
        enrollment = await db.get_enrollment(campaign_id, user_id)
        
        if not enrollment:
            await query.edit_message_text("Please join this program first" + BRAND_FOOTER)
            return
        
        request_id = await db.create_stamp_request(
            campaign_id, user_id, campaign['merchant_id'], enrollment['id']
        )
        
        await db.queue_notification(
            campaign['merchant_id'],
            f"⏳ New stamp request from {query.from_user.first_name}"
        )
        
        await query.edit_message_text(
            "✅ *Request Sent!*\n\n"
            "The merchant will review it soon!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    # View request
    elif data.startswith("viewreq_"):
        request_id = int(data.split("_")[1])
        
        async with db.pool.acquire() as conn:
            req = await conn.fetchrow('''
                SELECT sr.id, sr.campaign_id, sr.customer_id,
                       ca.name as campaign_name, ca.stamps_needed,
                       u.username, u.first_name,
                       e.stamps as current_stamps
                FROM stamp_requests sr
                JOIN campaigns ca ON sr.campaign_id = ca.id
                JOIN users u ON sr.customer_id = u.id
                JOIN enrollments e ON sr.enrollment_id = e.id
                WHERE sr.id = $1
            ''', request_id)
        
        if not req:
            await query.edit_message_text("Request not found" + BRAND_FOOTER)
            return
        
        customer_name = req['username'] or req['first_name']
        progress_bar = generate_progress_bar(req['current_stamps'], req['stamps_needed'], 20)
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{request_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{request_id}")
            ],
            [InlineKeyboardButton("« Back", callback_data="show_pending")]
        ]
        
        await query.edit_message_text(
            f"👤 *{customer_name}*\n"
            f"📋 {req['campaign_name']}\n\n"
            f"{progress_bar}\n"
            f"{req['current_stamps']}/{req['stamps_needed']} stamps" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Approve request
    elif data.startswith("approve_"):
        request_id = int(data.split("_")[1])
        result = await db.approve_stamp_request(request_id)
        
        if not result:
            await query.edit_message_text("Request already processed" + BRAND_FOOTER)
            return
        
        campaign = result['campaign']
        progress_bar = generate_progress_bar(result['new_stamps'], campaign['stamps_needed'], 20)
        
        if result['completed']:
            await db.queue_notification(
                result['customer_id'],
                f"🎉 *REWARD EARNED!*\n\nYou completed {campaign['name']}!" + BRAND_FOOTER
            )
            await query.edit_message_text(
                f"🎉 *Approved - Reward Earned!*\n\n{progress_bar}" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
        else:
            remaining = campaign['stamps_needed'] - result['new_stamps']
            await db.queue_notification(
                result['customer_id'],
                f"⭐ *New Stamp!*\n\n{campaign['name']}\n{progress_bar}\n{result['new_stamps']}/{campaign['stamps_needed']}" + BRAND_FOOTER
            )
            await query.edit_message_text(
                f"✅ *Approved!*\n\n{progress_bar}\n{result['new_stamps']}/{campaign['stamps_needed']}" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
        return
    
    # Reject request
    elif data.startswith("reject_"):
        request_id = int(data.split("_")[1])
        result = await db.reject_stamp_request(request_id)
        
        if result:
            await db.queue_notification(
                result['customer_id'],
                "Your stamp request was not approved"
            )
        
        await query.edit_message_text("❌ Request rejected" + BRAND_FOOTER)
        return
    
    # Approve all
    elif data == "approve_all":
        requests = await db.get_pending_requests(user_id)
        count = 0
        
        for req in requests:
            result = await db.approve_stamp_request(req['id'])
            if result:
                count += 1
        
        await query.edit_message_text(
            f"✅ Approved {count} requests!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    # Show pending
    elif data == "show_pending":
        requests = await db.get_pending_requests(user_id)
        
        if not requests:
            await query.message.reply_text(
                "📭 No pending requests!" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
            return
        
        keyboard = []
        for req in requests[:15]:
            customer_name = req['username'] or req['first_name']
            progress = f"{req['current_stamps']}/{req['stamps_needed']}"
            button_text = f"{customer_name} - {req['campaign_name']} ({progress})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"viewreq_{req['id']}")])
        
        if len(requests) > 1:
            keyboard.append([InlineKeyboardButton(f"✅ Approve All", callback_data="approve_all")])
        
        await query.message.reply_text(
            f"⏳ *Pending Requests ({len(requests)})*" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Quick stamp
    elif data.startswith("quickstamp_"):
        customer_id = int(data.split("_")[1])
        campaigns = await db.get_merchant_campaigns(user_id)
        
        keyboard = []
        for campaign in campaigns:
            enrollment = await db.get_enrollment(campaign['id'], customer_id)
            if enrollment and not enrollment['completed']:
                keyboard.append([InlineKeyboardButton(
                    f"⭐ {campaign['name']} ({enrollment['stamps']}/{campaign['stamps_needed']})",
                    callback_data=f"addstamp_{campaign['id']}_{customer_id}"
                )])
        
        if not keyboard:
            await query.edit_message_text("No active cards for this customer" + BRAND_FOOTER)
            return
        
        await query.edit_message_text(
            "⭐ *Add Stamp*\n\nSelect program:" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Add stamp
    elif data.startswith("addstamp_"):
        parts = data.split("_")
        campaign_id = int(parts[1])
        customer_id = int(parts[2])
        
        campaign = await db.get_campaign(campaign_id)
        enrollment = await db.get_enrollment(campaign_id, customer_id)
        
        async with db.pool.acquire() as conn:
            new_stamps = enrollment['stamps'] + 1
            completed = new_stamps >= campaign['stamps_needed']
            
            await conn.execute('''
                UPDATE enrollments 
                SET stamps = $1, completed = $2, updated_at = NOW()
                WHERE id = $3
            ''', new_stamps, completed, enrollment['id'])
            
            await conn.execute('''
                INSERT INTO stamp_requests (campaign_id, customer_id, merchant_id, enrollment_id, status, created_at, processed_at)
                VALUES ($1, $2, $3, $4, 'approved', NOW(), NOW())
            ''', campaign_id, customer_id, user_id, enrollment['id'])
        
        progress_bar = generate_progress_bar(new_stamps, campaign['stamps_needed'], 20)
        percentage = int((new_stamps / campaign['stamps_needed']) * 100) if campaign['stamps_needed'] > 0 else 0
        
        if completed:
            await query.edit_message_text(
                f"🎉 *STAMP ADDED - REWARD EARNED!*\n\n"
                f"{progress_bar} 100%\n\n"
                f"Customer can claim their reward!" + BRAND_FOOTER,
parse_mode="Markdown"
)
            await db.queue_notification(
                customer_id,
                f"🎉 *CONGRATULATIONS!*\n\nYou earned a reward at {campaign['name']}!" + BRAND_FOOTER
            )
        else:
            remaining = campaign['stamps_needed'] - new_stamps
            await query.edit_message_text(
                f"✅ *STAMP ADDED!*\n\n"
                f"{progress_bar} {percentage}%\n\n"
                f"{new_stamps}/{campaign['stamps_needed']} stamps\n"
                f"{remaining} more to go!" + BRAND_FOOTER,
                parse_mode="Markdown"
            )
            
            await db.queue_notification(
                customer_id,
                f"⭐ *NEW STAMP!*\n\n{campaign['name']}\n{progress_bar} {percentage}%\n{new_stamps}/{campaign['stamps_needed']}" + BRAND_FOOTER
            )
        return
    
    # Quick reward
    elif data.startswith("quickreward_"):
        customer_id = int(data.split("_")[1])
        
        async with db.pool.acquire() as conn:
            completed_campaigns = await conn.fetch("""
                SELECT c.id, c.name
                FROM enrollments e
                JOIN campaigns c ON e.campaign_id = c.id
                WHERE e.customer_id = $1 
                AND c.merchant_id = $2 
                AND e.completed = true
            """, customer_id, user_id)
        
        if not completed_campaigns:
            await query.edit_message_text("No rewards ready!" + BRAND_FOOTER)
            return
        
        keyboard = []
        for campaign in completed_campaigns:
            keyboard.append([InlineKeyboardButton(
                f"🎁 {campaign['name']}",
                callback_data=f"clearrew_{campaign['id']}_{customer_id}"
            )])
        
        await query.edit_message_text(
            "🎁 *Clear Reward*\n\nWhich reward?" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Clear reward
    elif data.startswith("clearrew_"):
        parts = data.split("_")
        campaign_id = int(parts[1])
        customer_id = int(parts[2])
        
        campaign = await db.get_campaign(campaign_id)
        
        async with db.pool.acquire() as conn:
            await conn.execute('''
                UPDATE enrollments 
                SET stamps = 0, completed = FALSE, updated_at = NOW()
                WHERE campaign_id = $1 AND customer_id = $2
            ''', campaign_id, customer_id)
            
            await conn.execute('''
                INSERT INTO reward_claims (campaign_id, customer_id, merchant_id, claimed_at)
                VALUES ($1, $2, $3, NOW())
            ''', campaign_id, customer_id, user_id)
        
        await query.edit_message_text(
            f"✅ *REWARD CLEARED!*\n\n"
            f"Card reset for {campaign['name']}" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        
        await db.queue_notification(
            customer_id,
            f"🎉 *REWARD CLAIMED!*\n\n{campaign['name']}\n\nYour card has been reset!" + BRAND_FOOTER
        )
        return
    
    # Wizard step 1
    elif data == "wizard_step1":
        context.user_data['wizard_step'] = 1
        
        keyboard = [
            [InlineKeyboardButton("☕ Coffee Rewards", callback_data="preset_Coffee Rewards")],
            [InlineKeyboardButton("🍕 Pizza Lovers", callback_data="preset_Pizza Lovers")],
            [InlineKeyboardButton("💇 Salon VIP", callback_data="preset_Salon VIP")],
            [InlineKeyboardButton("✏️ Custom Name", callback_data="wizard_custom_name")]
        ]
        
        await query.edit_message_text(
            "📝 *Step 1: Program Name*\n\n"
            "Choose a preset or create your own:" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Preset name
    elif data.startswith("preset_"):
        program_name = data.replace("preset_", "")
        context.user_data['program_name'] = program_name
        
        keyboard = [
            [InlineKeyboardButton("5️⃣ stamps", callback_data="stamps_5")],
            [InlineKeyboardButton("🔟 stamps", callback_data="stamps_10")],
            [InlineKeyboardButton("1️⃣5️⃣ stamps", callback_data="stamps_15")],
            [InlineKeyboardButton("2️⃣0️⃣ stamps", callback_data="stamps_20")]
        ]
        
        await query.edit_message_text(
            f"✅ Name: *{program_name}*\n\n"
            f"🎯 *Step 2: How Many Stamps?*" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Select stamps
    elif data.startswith("stamps_"):
        stamps_needed = int(data.split("_")[1])
        program_name = context.user_data.get('program_name', 'My Program')
        
        campaign_id = await db.create_campaign(user_id, program_name, stamps_needed)
        
        link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        await query.message.reply_photo(
            photo=bio,
            caption=(
                f"🎉 *PROGRAM CREATED!*\n\n"
                f"📋 *{program_name}*\n"
                f"🎯 {stamps_needed} stamps\n"
                f"🆔 ID: `{campaign_id}`\n\n"
                f"✅ Display this QR at your store!\n\n"
                f"Link: `{link}`" + BRAND_FOOTER
            ),
            parse_mode="Markdown"
        )
        
        context.user_data.clear()
        return
    
    # Get QR
    elif data.startswith("getqr_"):
        campaign_id = int(data.split("_")[1])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign or campaign['merchant_id'] != user_id:
            await query.message.reply_text("Campaign not found" + BRAND_FOOTER)
            return
        
        link = f"https://t.me/{BOT_USERNAME}?start=join_{campaign_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        await query.message.reply_photo(
            photo=bio,
            caption=f"📱 *{campaign['name']}*\n\n🎯 {campaign['stamps_needed']} stamps\n\nLink: `{link}`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
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
            f"✅ {campaign.get('total_completions', 0)} completed"
        )
        
        keyboard = [
            [InlineKeyboardButton("📱 Get QR", callback_data=f"getqr_{campaign_id}")],
            [InlineKeyboardButton("« Back", callback_data="my_campaigns")]
        ]
        
        await query.edit_message_text(
            message + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Admin approve
    elif data.startswith("admin_approve_"):
        if user_id not in ADMIN_IDS:
            return
        
        merchant_id = int(data.split("_")[2])
        await db.approve_merchant(merchant_id, user_id)
        
        await db.queue_notification(
            merchant_id,
            "🎉 *Congratulations!*\n\nYour merchant account has been approved!" + BRAND_FOOTER
        )
        
        await query.edit_message_text(f"✅ Merchant approved!" + BRAND_FOOTER, parse_mode="Markdown")
        return
    
    # Help sections
    elif data == "help_customer_stamps":
        await query.edit_message_text(
            "⭐ *How to Collect Stamps*\n\n"
            "*Step 1:* Tap '📍 Find Stores'\n"
            "*Step 2:* Join a program\n"
            "*Step 3:* Make a purchase\n"
            "*Step 4:* Show your ID or request stamp\n"
            "*Step 5:* Earn rewards!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    elif data == "help_rewards":
        await query.edit_message_text(
            "🎁 *How to Claim Rewards*\n\n"
            "When you complete a card:\n"
            "1️⃣ Visit the store\n"
            "2️⃣ Open your wallet\n"
            "3️⃣ Show completed card\n"
            "4️⃣ Get your reward!\n"
            "5️⃣ Card resets automatically" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    elif data == "help_merchant_start":
        await query.edit_message_text(
            "📖 *Getting Started*\n\n"
            "1. Tap '➕ New Program'\n"
            "2. Follow the wizard\n"
            "3. Display your QR code\n"
            "4. Manage stamps via menu\n"
            "5. Track your analytics!" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    # Start tutorial
    elif data == "start_tutorial":
        keyboard = [
            [InlineKeyboardButton("Next ▶️", callback_data="tutorial_2")],
            [InlineKeyboardButton("Skip", callback_data="skip_tutorial")]
        ]
        
        await query.edit_message_text(
            "🎓 *Tutorial - Lesson 1*\n\n"
            "*Finding Stores*\n\n"
            "Tap '📍 Find Stores' to see all participating stores near you!\n\n"
            "Each store offers different rewards 🎯" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    elif data == "tutorial_2":
        keyboard = [[InlineKeyboardButton("✅ Finish", callback_data="skip_tutorial")]]
        
        await query.edit_message_text(
            "🎓 *Tutorial - Lesson 2*\n\n"
            "*Your ID Card*\n\n"
            "Tap '🆔 Show My ID' to see your QR code.\n\n"
            "Show it to cashiers for instant stamps! ⚡" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    elif data == "skip_tutorial":
        await query.edit_message_text(
            "✅ *You're All Set!*\n\n"
            "Use the menu buttons below to get started!\n\n"
            "Need help? Tap '❓ Help' anytime! 💙" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    # Unknown callback
    else:
        logger.warning(f"Unknown callback: {data}")
        await query.answer("Unknown action")
        return

except Exception as e:
    logger.error(f"❌ Callback error for '{data}': {e}")
    import traceback
    traceback.print_exc()
    
    try:
        keyboard = [
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_menu")],
            [InlineKeyboardButton("❓ Help", callback_data="back_to_help")]
        ]
        
        await query.message.reply_text(
            "😕 *Oops! Something went wrong*\n\n"
            "Try going back to the main menu!" + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
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
logger.error(f"Failed to send notification: {e}")
await asyncio.sleep(5)
except Exception as e:
logger.error(f"Notification task error: {e}")
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
                f"⭐ Stamps: {stats['stamps_given']}\n"
                f"🎁 Rewards: {stats['rewards_claimed']}\n"
            )
            
            if pending > 0:
                message += f"⏳ Pending: {pending}\n"
            
            message += f"\n💡 *Tip:* {tip}"
            
            await db.queue_notification(merchant['id'], message + BRAND_FOOTER)
        except Exception as e:
            logger.error(f"Error sending summary to {merchant['id']}: {e}")
except Exception as e:
    logger.error(f"Error in daily summaries: {e}")
# ==================== MAIN ====================
async def main():
"""Start the bot with auto-migration"""
print("🚀 Starting StampMe Bot...")
# Clear webhook
for attempt in range(3):
    try:
        temp_app = ApplicationBuilder().token(TOKEN).build()
        await temp_app.initialize()
        await temp_app.bot.delete_webhook(drop_pending_updates=True)
        print(f"  ✓ Attempt {attempt + 1}: Webhook cleared")
        await temp_app.shutdown()
        await asyncio.sleep(3)
        break
    except Exception as e:
        print(f"  ⚠️ Attempt {attempt + 1} failed: {e}")
        if attempt < 2:
            await asyncio.sleep(2)

# Connect database
try:
    await db.connect()
    print("✅ Database connected")
    
    # ==================== AUTO-MIGRATION ====================
    print("\n🔄 Running database migrations...")
    await run_migrations(db.pool)
    print("✅ Migrations complete!\n")
    # ==================== END AUTO-MIGRATION ====================
    
except Exception as e:
    print(f"❌ Database error: {e}")
    return

# Start health server
await start_web_server()

# Build application
print("🤖 Building bot application...")
app = ApplicationBuilder().token(TOKEN).build()

# Add handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("wallet", wallet))
app.add_handler(CommandHandler("myid", myid))
app.add_handler(CommandHandler("pending", pending))
app.add_handler(CommandHandler("dashboard", dashboard))
app.add_handler(CommandHandler("newcampaign", newcampaign))
app.add_handler(CommandHandler("mycampaigns", mycampaigns))
app.add_handler(CommandHandler("getqr", getqr))
app.add_handler(CommandHandler("givestamp", givestamp))
app.add_handler(CommandHandler("clearreward", clearreward))
app.add_handler(CommandHandler("addreward", addreward))
app.add_handler(CommandHandler("stats", stats_command))
app.add_handler(CommandHandler("share", share))
app.add_handler(CommandHandler("admin", admin_panel))

# Text message handler for keyboard buttons
app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    handle_text_message
))

# Callback handler
app.add_handler(CallbackQueryHandler(button_callback))

# Initialize and start
await app.initialize()
await app.start()

print("📡 Starting to poll for updates...")
await app.updater.start_polling(
    drop_pending_updates=True,
    allowed_updates=Update.ALL_TYPES
)

print("✅ Bot is running!")
print(f"📱 Bot: @{BOT_USERNAME}")
print(f"🔧 Admin IDs: {ADMIN_IDS}")

# Background tasks
asyncio.create_task(send_notifications(app))
print("✅ Notification sender started")

scheduler.add_job(send_daily_summaries, 'cron', hour=18, minute=0)
scheduler.start()
print("✅ Daily summary scheduler started")

await asyncio.Event().wait()
if name == "main":
try:
asyncio.run(main())
except KeyboardInterrupt:
print("\n👋 Bot stopped by user")
except Exception as e:
print(f"\n❌ Fatal error: {e}")
import traceback
traceback.print_exc()
                
            

