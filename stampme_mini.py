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
    
    allowed, remaining = rate_limiter.check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            "⚠️ Please slow down! Wait a moment.",
            reply_markup=get_customer_keyboard() if user and user['user_type'] == 'customer' else get_merchant_keyboard()
        )
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
    """Handle /start command"""
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
                    await update.message.reply_text(
                        "😕 Program not available" + BRAND_FOOTER,
                        reply_markup=get_customer_keyboard()
                    )
                    return
                
                enrollment = await db.get_enrollment(campaign_id, user_id)
                
                if not enrollment:
                    await db.enroll_customer(campaign_id, user_id)
                    await update.message.reply_text(
                        f"🎉 *Welcome!*\n\nYou joined: *{campaign['name']}*\n\n"
                        f"Collect {campaign['stamps_needed']} stamps!" + BRAND_FOOTER,
                        reply_markup=get_customer_keyboard(),
                        parse_mode="Markdown"
                    )
                    if not user.get('onboarded'):
                        await db.mark_user_onboarded(user_id)
                else:
                    await update.message.reply_text(
                        f"👋 Welcome back!" + BRAND_FOOTER,
                        reply_markup=get_customer_keyboard()
                    )
                return
            except Exception as e:
                logger.error(f"Error: {e}")
                return
    
    if user and user['user_type'] == 'merchant' and user['merchant_approved']:
        await update.message.reply_text(
            f"👋 Welcome back, {first_name}!" + BRAND_FOOTER,
            reply_markup=get_merchant_keyboard()
        )
    else:
        await update.message.reply_text(
            f"👋 Hi {first_name}!\n\nWelcome to *StampMe* 💙" + BRAND_FOOTER,
            reply_markup=get_customer_keyboard(),
            parse_mode="Markdown"
        )
        if not user.get('onboarded'):
            await db.mark_user_onboarded(user_id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    await update.message.reply_text(
        "❓ *Help Center*\n\nUse the menu buttons below!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show wallet"""
    user_id = update.effective_user.id
    enrollments = await db.get_customer_enrollments(user_id)
    
    if not enrollments:
        await update.message.reply_text(
            "💳 *Your Wallet is Empty*\n\nFind stores to start!" + BRAND_FOOTER,
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
            
            if e['completed']:
                caption = f"🎉 *{e['name']}*\n\n{progress_bar}\n✅ REWARD READY!"
            else:
                caption = f"📋 *{e['name']}*\n\n{progress_bar}\n{e['stamps']}/{e['stamps_needed']} stamps"
            
            await update.message.reply_photo(photo=bio, caption=caption + BRAND_FOOTER, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error: {e}")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show ID"""
    user_id = update.effective_user.id
    
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(str(user_id))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    
    await update.message.reply_photo(
        photo=bio,
        caption=f"🆔 Your ID: `{user_id}`\n\nShow this to merchants!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def find_stores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find stores"""
    await update.message.reply_text(
        "🔍 *Find Stores*\n\nNo stores yet. Check back soon!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show rewards"""
    await update.message.reply_text(
        "🎁 *No rewards ready yet*\n\nKeep collecting!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Settings"""
    await update.message.reply_text(
        "⚙️ *Settings*\n\nComing soon!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dashboard"""
    await update.message.reply_text(
        "📊 *Dashboard*\n\nYour stats will appear here!" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pending requests"""
    await update.message.reply_text(
        "⏳ *No pending requests*" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def scan_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan customer"""
    await update.message.reply_text(
        "👥 *Scan Customer*\n\nNo recent customers" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """My campaigns"""
    await update.message.reply_text(
        "📋 *Your Programs*\n\nNo programs yet" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def new_program_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """New program"""
    await update.message.reply_text(
        "➕ *Create Program*\n\nUse: /newcampaign <name> <stamps>" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create campaign"""
    await update.message.reply_text(
        "Use: /newcampaign <name> <stamps>" + BRAND_FOOTER
    )

async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get QR"""
    await update.message.reply_text(
        "Use: /getqr <id>" + BRAND_FOOTER
    )

async def givestamp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give stamp"""
    await update.message.reply_text(
        "Use the menu!" + BRAND_FOOTER,
        reply_markup=get_merchant_keyboard()
    )

async def clearreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear reward"""
    await update.message.reply_text(
        "Use the menu!" + BRAND_FOOTER,
        reply_markup=get_merchant_keyboard()
    )

async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add reward"""
    await update.message.reply_text(
        "Use: /addreward <id> <stamps> <reward>" + BRAND_FOOTER
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stats"""
    await update.message.reply_text(
        "Check dashboard!" + BRAND_FOOTER,
        reply_markup=get_merchant_keyboard()
    )

async def share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Share"""
    await update.message.reply_text(
        "Use: /share <id>" + BRAND_FOOTER
    )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "🔧 *Admin Panel*" + BRAND_FOOTER,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callbacks"""
    query = update.callback_query
    
    try:
        await query.answer()
    except:
        pass
    
    await query.message.reply_text("Action processed!" + BRAND_FOOTER)

async def send_notifications(app):
    """Send notifications"""
    while True:
        try:
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error: {e}")
            await asyncio.sleep(5)

async def send_daily_summaries():
    """Daily summaries"""
    pass

async def main():
    """Start bot"""
    print("🚀 Starting StampMe Bot...")
    
    for attempt in range(3):
        try:
            temp_app = ApplicationBuilder().token(TOKEN).build()
            await temp_app.initialize()
            await temp_app.bot.delete_webhook(drop_pending_updates=True)
            print(f"  ✓ Webhook cleared")
            await temp_app.shutdown()
            await asyncio.sleep(3)
            break
        except Exception as e:
            print(f"  ⚠️ Attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
    
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
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    await app.initialize()
    await app.start()
    
    print("📡 Starting polling...")
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    
    print("✅ Bot is running!")
    print(f"📱 Bot: @{BOT_USERNAME}")
    
    asyncio.create_task(send_notifications(app))
    scheduler.add_job(send_daily_summaries, 'cron', hour=18, minute=0)
    scheduler.start()
    
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
