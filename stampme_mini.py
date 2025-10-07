import os
import asyncio
import io
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import qrcode
from PIL import Image, ImageDraw, ImageFont
from database import Database

# Configuration
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
BOT_USERNAME = os.getenv("BOT_USERNAME", "stampmebot")

# Database instance
db = Database()

# Health check
async def health_check(request):
    return web.Response(text="StampMe Bot Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/healthz', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"Health check server started on port {PORT}")

# Generate visual stamp card
def generate_card_image(campaign_name, current_stamps, needed_stamps):
    """Generate a beautiful stamp card image"""
    width, height = 800, 400
    img = Image.new('RGB', (width, height), color='#6366f1')
    draw = ImageDraw.Draw(img)
    
    # Try to use a nice font, fallback to default
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
    
    # Title
    draw.text((50, 40), campaign_name, fill='white', font=title_font)
    
    # Stamps grid
    stamp_size = 60
    spacing = 20
    start_x = 50
    start_y = 150
    cols = 5
    
    for i in range(needed_stamps):
        row = i // cols
        col = i % cols
        x = start_x + col * (stamp_size + spacing)
        y = start_y + row * (stamp_size + spacing)
        
        if i < current_stamps:
            draw.ellipse([x, y, x + stamp_size, y + stamp_size], fill='#fbbf24', outline='white', width=3)
            draw.text((x + 20, y + 15), "*", fill='white', font=text_font)
        else:
            draw.ellipse([x, y, x + stamp_size, y + stamp_size], fill='none', outline='white', width=3)
    
    # Progress text
    progress_text = f"{current_stamps}/{needed_stamps} Stamps"
    draw.text((50, height - 80), progress_text, fill='white', font=text_font)
    
    return img

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    
    await db.create_customer(user_id, username, update.effective_user.first_name)
    
    # Handle deep links (QR scan or referral)
    if context.args:
        arg = context.args[0]
        
        # Referral link
        if arg.startswith("ref_"):
            try:
                parts = arg.split("_")
                referrer_id = int(parts[1])
                campaign_id = int(parts[2])
                
                if referrer_id != user_id:
                    await db.create_referral(referrer_id, user_id, campaign_id)
                    await db.give_referral_bonus(referrer_id, campaign_id)
                    
                    await update.message.reply_text(
                        "Welcome! You were referred by a friend.\nYou both get a bonus stamp!"
                    )
            except:
                pass
        
        # Campaign join
        elif arg.startswith("join_"):
            try:
                campaign_id = int(arg.split("_")[1])
                campaign = await db.get_campaign(campaign_id)
                
                if not campaign:
                    await update.message.reply_text("Campaign not found.")
                    return
                
                # Check expiration
                if campaign['expires_at'] and campaign['expires_at'] < datetime.now():
                    await update.message.reply_text("This campaign has expired.")
                    return
                
                enrollment = await db.get_enrollment(campaign_id, user_id)
                
                if not enrollment:
                    await db.enroll_customer(campaign_id, user_id)
                    
                    # Get reward tiers
                    rewards = await db.get_campaign_rewards(campaign_id)
                    reward_text = ""
                    if rewards:
                        reward_text = "\n\nRewards:\n" + "\n".join(
                            f"• {r['stamps_required']} stamps: {r['reward_name']}"
                            for r in rewards
                        )
                    
                    await update.message.reply_text(
                        f"Welcome to {campaign['name']}!\n\n"
                        f"Collect {campaign['stamps_needed']} stamps to earn rewards."
                        f"{reward_text}\n\n"
                        f"Use /wallet to track progress!"
                    )
                else:
                    await update.message.reply_text(
                        f"Welcome back to {campaign['name']}!\n"
                        f"Progress: {enrollment['stamps']}/{campaign['stamps_needed']}"
                    )
            except Exception as e:
                print(f"Error joining campaign: {e}")
            return
    
    # Normal start
    keyboard = [
        [InlineKeyboardButton("My Wallet", callback_data="show_wallet")],
        [InlineKeyboardButton("Help", callback_data="show_help")],
        [InlineKeyboardButton("Create Campaign", callback_data="create_campaign_help")]
    ]
    
    await update.message.reply_text(
        "Welcome to StampMe!\n\n"
        "Digital stamp cards for businesses and customers.\n\n"
        "Customers: Scan QR codes to collect stamps\n"
        "Merchants: Create campaigns and reward loyalty",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /newcampaign <name> <stamps>\n"
            "Example: /newcampaign Coffee 5"
        )
        return
    
    try:
        stamps_needed = int(context.args[-1])
        name = " ".join(context.args[:-1])
        
        if not (1 <= stamps_needed <= 50):
            await update.message.reply_text("Stamps must be between 1 and 50")
            return
        
        user_id = update.effective_user.id
        await db.create_merchant(user_id, update.effective_user.username, update.effective_user.first_name)
        
        campaign_id = await db.create_campaign(user_id, name, stamps_needed)
        
        keyboard = [
            [InlineKeyboardButton("Get QR Code", callback_data=f"getqr_{campaign_id}")],
            [InlineKeyboardButton("Add Rewards", callback_data=f"addreward_{campaign_id}")],
            [InlineKeyboardButton("Share Link", callback_data=f"share_{campaign_id}")]
        ]
        
        await update.message.reply_text(
            f"Campaign '{name}' created!\n"
            f"ID: {campaign_id}\n"
            f"Stamps needed: {stamps_needed}\n\n"
            f"What's next?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except ValueError:
        await update.message.reply_text("Last argument must be a number")
    except Exception as e:
        print(f"Error creating campaign: {e}")
        await update.message.reply_text("Error creating campaign")

async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add reward tier: /addreward <campaign_id> <stamps> <reward_name>"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /addreward <campaign_id> <stamps> <reward>\n"
            "Example: /addreward 1 5 Free Coffee"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        stamps_req = int(context.args[1])
        reward = " ".join(context.args[2:])
        
        await db.add_reward_tier(campaign_id, stamps_req, reward)
        await update.message.reply_text(f"Reward added: {stamps_req} stamps = {reward}")
    except Exception as e:
        print(f"Error adding reward: {e}")
        await update.message.reply_text("Error adding reward")

async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /getqr <campaign_id>")
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign:
            await update.message.reply_text("Campaign not found")
            return
        
        # Generate QR
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
            caption=f"QR Code for: {campaign['name']}\n\nCustomers scan this to join!\n\nLink: {link}"
        )
    except Exception as e:
        print(f"Error generating QR: {e}")
        await update.message.reply_text("Error generating QR code")

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        campaigns = await db.get_merchant_campaigns(update.effective_user.id)
        
        if not campaigns:
            await update.message.reply_text("You haven't created campaigns yet.\n\nUse: /newcampaign <name> <stamps>")
            return
        
        message = "Your Campaigns:\n\n"
        for c in campaigns:
            customers = await db.get_campaign_customers(c['id'])
            message += f"• {c['name']} (ID: {c['id']})\n"
            message += f"  Stamps: {c['stamps_needed']}\n"
            message += f"  Customers: {len(customers)}\n\n"
        
        await update.message.reply_text(message)
    except Exception as e:
        print(f"Error listing campaigns: {e}")
        await update.message.reply_text("Error loading campaigns")

async def stamp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /stamp <campaign_id>")
        return
    
    try:
        campaign_id = int(context.args[0])
        customers = await db.get_campaign_customers(campaign_id)
        
        if not customers:
            await update.message.reply_text("No customers enrolled yet")
            return
        
        keyboard = []
        campaign = await db.get_campaign(campaign_id)
        for c in customers:
            name = c['username'] or c['first_name']
            text = f"{name} ({c['stamps']}/{campaign['stamps_needed']})"
            keyboard.append([InlineKeyboardButton(text, callback_data=f"dostamp_{c['id']}")])
        
        await update.message.reply_text(
            "Select customer to stamp:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        print(f"Error stamping: {e}")
        await update.message.reply_text("Error loading customers")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        enrollments = await db.get_customer_enrollments(update.effective_user.id)
        
        if not enrollments:
            await update.message.reply_text("No stamp cards yet!\n\nScan a QR code to join a campaign.")
            return
        
        for e in enrollments:
            # Generate visual card
            img = generate_card_image(e['name'], e['stamps'], e['stamps_needed'])
            bio = io.BytesIO()
            img.save(bio, 'PNG')
            bio.seek(0)
            
            status = "COMPLETED!" if e['completed'] else f"{e['stamps']}/{e['stamps_needed']}"
            
            await update.message.reply_photo(
                photo=bio,
                caption=f"{e['name']}\nStatus: {status}"
            )
    except Exception as e:
        print(f"Error showing wallet: {e}")
        await update.message.reply_text("Error loading wallet")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analytics for merchants"""
    if not context.args:
        await update.message.reply_text("Usage: /stats <campaign_id> [days]")
        return
    
    try:
        campaign_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) > 1 else 30
        
        campaign = await db.get_campaign(campaign_id)
        if not campaign:
            await update.message.reply_text("Campaign not found")
            return
        
        stats = await db.get_campaign_stats(campaign_id, days)
        
        completion_rate = 0
        if stats['total_customers'] > 0:
            completion_rate = (stats['completed_customers'] / stats['total_customers']) * 100
        
        message = f"Analytics: {campaign['name']}\n\n"
        message += f"Total Customers: {stats['total_customers']}\n"
        message += f"Completed: {stats['completed_customers']}\n"
        message += f"Completion Rate: {completion_rate:.1f}%\n"
        message += f"Total Stamps Given: {stats['total_stamps']}\n"
        message += f"Recent Activity ({days}d): {stats['recent_stamps']} stamps\n"
        
        await update.message.reply_text(message)
    except Exception as e:
        print(f"Error getting stats: {e}")
        await update.message.reply_text("Error loading statistics")

async def share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate referral link"""
    if not context.args:
        await update.message.reply_text("Usage: /share <campaign_id>")
        return
    
    try:
        campaign_id = int(context.args[0])
        user_id = update.effective_user.id
        
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}_{campaign_id}"
        
        await update.message.reply_text(
            f"Share this link with friends!\n\n"
            f"{link}\n\n"
            f"You both get a bonus stamp when they join!"
        )
    except Exception as e:
        print(f"Error generating share link: {e}")
        await update.message.reply_text("Error generating link")

# Button callbacks
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    try:
        if data == "show_wallet":
            user_id = query.from_user.id
            enrollments = await db.get_customer_enrollments(user_id)
            
            if not enrollments:
                await query.edit_message_text("No stamp cards yet!\n\nScan a QR code to get started!")
                return
            
            message = "Your Stamp Cards:\n\n"
            for e in enrollments:
                status = "COMPLETED" if e['completed'] else f"{e['stamps']}/{e['stamps_needed']}"
                message += f"• {e['name']}: {status}\n"
            
            await query.edit_message_text(message)
            return
        
        if data == "show_help":
            await query.edit_message_text(
                "Commands:\n\n"
                "Customers:\n"
                "/wallet - View stamp cards\n\n"
                "Merchants:\n"
                "/newcampaign <name> <stamps>\n"
                "/mycampaigns - List campaigns\n"
                "/getqr <id> - Get QR code\n"
                "/stamp <id> - Add stamps\n"
                "/stats <id> - View analytics\n"
                "/addreward <id> <stamps> <reward>\n"
                "/share <id> - Get referral link"
            )
            return
        
        if data == "create_campaign_help":
            await query.edit_message_text(
                "Create a Campaign:\n\n"
                "Use: /newcampaign <name> <stamps>\n\n"
                "Examples:\n"
                "/newcampaign Coffee 5\n"
                "/newcampaign Pizza 8\n"
                "/newcampaign Haircut 3"
            )
            return
        
        if data.startswith("getqr_"):
            campaign_id = int(data.split("_")[1])
            context.args = [str(campaign_id)]
            await query.message.delete()
            await getqr(update, context)
            return
        
        if data.startswith("share_"):
            campaign_id = int(data.split("_")[1])
            user_id = query.from_user.id
            link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}_{campaign_id}"
            await query.edit_message_text(
                f"Share this referral link:\n\n{link}\n\n"
                f"You both get a bonus stamp!"
            )
            return
        
        if data.startswith("addreward_"):
            campaign_id = int(data.split("_")[1])
            await query.edit_message_text(
                f"To add rewards, use:\n\n"
                f"/addreward {campaign_id} <stamps> <reward>\n\n"
                f"Example:\n"
                f"/addreward {campaign_id} 5 Free Coffee\n"
                f"/addreward {campaign_id} 10 Free Meal"
            )
            return
        
        if data.startswith("dostamp_"):
            enrollment_id = int(data.split("_")[1])
            
            # Get enrollment details
            async with db.pool.acquire() as conn:
                enrollment = await conn.fetchrow(
                    'SELECT * FROM enrollments WHERE id = $1', enrollment_id
                )
                campaign = await db.get_campaign(enrollment['campaign_id'])
                customer = await conn.fetchrow(
                    'SELECT * FROM customers WHERE id = $1', enrollment['customer_id']
                )
            
            # Add stamp
            new_stamps = await db.add_stamp(enrollment_id, query.from_user.id)
            
            # Check completion
            if new_stamps >= campaign['stamps_needed']:
                await db.mark_completed(enrollment_id)
                status = "COMPLETED!"
            else:
                status = f"{new_stamps}/{campaign['stamps_needed']}"
            
            await query.edit_message_text(
                f"Stamp added to {customer['username'] or customer['first_name']}!\n"
                f"Progress: {status}"
            )
            
            # Notify customer
            try:
                await context.bot.send_message(
                    customer['id'],
                    f"New stamp received!\n{campaign['name']}: {status}"
                )
            except:
                pass
    
    except Exception as e:
        print(f"Button callback error: {e}")
        await query.edit_message_text("Error processing request")

async def main():
    print("Starting StampMe Bot...")
    
    try:
        # Connect to database
        await db.connect()
        print("Database connected")
    except Exception as e:
        print(f"Database connection error: {e}")
        print("Make sure DATABASE_URL environment variable is set")
        return
    
    # Start health server
    await start_web_server()
    
    # Build bot
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newcampaign", newcampaign))
    app.add_handler(CommandHandler("addreward", addreward))
    app.add_handler(CommandHandler("getqr", getqr))
    app.add_handler(CommandHandler("mycampaigns", mycampaigns))
    app.add_handler(CommandHandler("stamp", stamp_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("share", share))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    await app.initialize()
    await app.start()
    
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(2)
        print("Webhook cleared")
    except Exception as e:
        print(f"Webhook clear warning: {e}")
    
    try:
        await app.updater.start_polling(
            drop_pending_updates=True, 
            allowed_updates=Update.ALL_TYPES,
            timeout=30
        )
        print("Bot is running!")
        print(f"Bot username: @{BOT_USERNAME}")
    except Exception as e:
        print(f"Polling error: {e}")
        raise
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
    except Exception as e:
        print(f"Fatal error: {e}")
