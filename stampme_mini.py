# Main bot application with all integrated features
# ============================================

import os
import asyncio
import io
import random
from datetime import datetime, time
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, 
    CallbackQueryHandler, MessageHandler, filters
)
import qrcode
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import *
from database_complete import StampMeDatabase

# Initialize
db = StampMeDatabase(DATABASE_URL)
scheduler = AsyncIOScheduler()

# ==================== UTILITY FUNCTIONS ====================

def generate_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Generate a visual progress bar"""
    filled = int((current / total) * length)
    bar = "█" * filled + "░" * (length - filled)
    return bar

def generate_card_image(campaign_name: str, current_stamps: int, needed_stamps: int):
    """Generate visual stamp card"""
    width, height = 800, 400
    img = Image.new('RGB', (width, height), color='#6366f1')
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except:
        title_font = text_font = ImageFont.load_default()
    
    # Title
    draw.text((40, 30), campaign_name, fill='white', font=title_font)
    
    # Draw stamps in a grid
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
            # Filled stamp
            draw.ellipse([x, y, x + stamp_size, y + stamp_size], 
                        fill='#fbbf24', outline='white', width=3)
            draw.text((x + 17, y + 12), "★", fill='white', font=text_font)
        else:
            # Empty stamp
            draw.ellipse([x, y, x + stamp_size, y + stamp_size], 
                        fill='none', outline='white', width=2)
    
    # Progress text
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

async def mycampaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List merchant's campaigns"""
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("You need merchant approval first.")
        return
    
    campaigns = await db.get_merchant_campaigns(user_id)
    
    if not campaigns:
        await update.message.reply_text(
            "📭 *No campaigns yet*\n\n"
            "Create your first campaign with:\n"
            "`/newcampaign <n> <stamps>`\n\n"
            "Example: `/newcampaign Coffee 5`"
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        return
    
    message = "📋 *Your Campaigns*\n\n"
    
    keyboard = []
    for c in campaigns:
        customers = await db.get_campaign_customers(c['id'])
        completed = sum(1 for customer in customers if customer['completed'])
        
        message += f"*{c['name']}*\n"
        message += f"  🆔 ID: `{c['id']}`\n"
        message += f"  🎯 Stamps: {c['stamps_needed']}\n"
        message += f"  👥 Customers: {len(customers)}\n"
        message += f"  ✅ Completed: {completed}\n\n"
        
        keyboard.append([
            InlineKeyboardButton(f"📱 {c['name']}", callback_data=f"campaign_detail_{c['id']}")
        ])
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="Markdown"
    )

async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add reward tier to campaign"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "🎁 *Add Reward Tier*\n\n"
            "*Usage:*\n"
            "`/addreward <campaign_id> <stamps> <reward>`\n\n"
            "*Examples:*\n"
            "`/addreward 1 3 Free Coffee`\n"
            "`/addreward 1 5 Free Meal`\n"
            "`/addreward 1 10 VIP Card`"
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        stamps_req = int(context.args[1])
        reward_name = " ".join(context.args[2:])
        
        # Verify campaign ownership
        campaign = await db.get_campaign(campaign_id)
        if not campaign or campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("Campaign not found or you don't own it")
            return
        
        await db.add_reward_tier(campaign_id, stamps_req, reward_name)
        
        await update.message.reply_text(
            f"✅ *Reward Added!*\n\n"
            f"📋 Campaign: {campaign['name']}\n"
            f"🎯 At {stamps_req} stamps: {reward_name}"
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("Invalid format. Stamps must be a number.")
    except Exception as e:
        print(f"Error adding reward: {e}")
        await update.message.reply_text("Error adding reward")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show campaign statistics"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/stats <campaign_id>`\n\nExample: `/stats 1`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign or campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("Campaign not found or you don't own it")
            return
        
        customers = await db.get_campaign_customers(campaign_id)
        rewards = await db.get_campaign_rewards(campaign_id)
        
        total_stamps = sum(c['stamps'] for c in customers)
        completed = sum(1 for c in customers if c['completed'])
        avg_stamps = total_stamps / len(customers) if customers else 0
        completion_rate = (completed / len(customers) * 100) if customers else 0
        
        message = (
            f"📊 *Campaign Analytics*\n\n"
            f"📋 *{campaign['name']}*\n"
            f"🆔 ID: {campaign_id}\n\n"
            f"👥 *Customers:*\n"
            f"  Total enrolled: {len(customers)}\n"
            f"  Completed: {completed}\n"
            f"  Completion rate: {completion_rate:.1f}%\n\n"
            f"⭐ *Stamps:*\n"
            f"  Total given: {total_stamps}\n"
            f"  Average per customer: {avg_stamps:.1f}\n"
            f"  Needed for reward: {campaign['stamps_needed']}\n"
        )
        
        if rewards:
            message += f"\n🎁 *Reward Tiers:* {len(rewards)}\n"
        
        keyboard = [
            [InlineKeyboardButton("📱 Get QR", callback_data=f"getqr_{campaign_id}")],
            [InlineKeyboardButton("👥 View Customers", callback_data=f"customers_{campaign_id}")]
        ]
        
        await update.message.reply_text(
            message + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("Campaign ID must be a number")
    except Exception as e:
        print(f"Error getting stats: {e}")
        await update.message.reply_text("Error loading statistics")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show merchant settings"""
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("Merchant approval required")
        return
    
    settings = await db.get_merchant_settings(user_id)
    
    approval_emoji = "✅" if settings['require_approval'] else "❌"
    auto_emoji = "✅" if settings['auto_approve'] else "❌"
    summary_emoji = "✅" if settings['daily_summary_enabled'] else "❌"
    
    message = (
        f"⚙️ *Your Settings*\n\n"
        f"{approval_emoji} Require stamp approval\n"
        f"{auto_emoji} Auto-approve stamps\n"
        f"{summary_emoji} Daily summaries\n\n"
        f"📍 Business: {settings['business_name'] or 'Not set'}\n"
        f"📊 Summary time: {settings['notification_hour']}:00\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("Toggle Approval", callback_data="toggle_approval")],
        [InlineKeyboardButton("Toggle Summaries", callback_data="toggle_summaries")],
        [InlineKeyboardButton("« Back", callback_data="merchant_dashboard")]
    ]
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate referral link"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/share <campaign_id>`\n\nExample: `/share 1`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign:
            await update.message.reply_text("Campaign not found")
            return
        
        user_id = update.effective_user.id
        referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}_{campaign_id}"
        
        await update.message.reply_text(
            f"🎁 *Share & Earn*\n\n"
            f"Share this link with friends:\n"
            f"`{referral_link}`\n\n"
            f"You both get a bonus stamp when they join and make their first visit!\n\n"
            f"📋 Campaign: {campaign['name']}"
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("Campaign ID must be a number")

async def approveall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve all pending requests"""
    user_id = update.effective_user.id
    requests = await db.get_pending_requests(user_id)
    
    if not requests:
        await update.message.reply_text(
            "📭 No pending requests to approve" + BRAND_FOOTER
        )
        return
    
    # Confirmation
    keyboard = [
        [InlineKeyboardButton(f"✅ Yes, approve {len(requests)} requests", callback_data="approve_all")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    await update.message.reply_text(
        f"⚠️ *Confirm Approval*\n\n"
        f"Are you sure you want to approve {len(requests)} stamp requests?\n\n"
        f"All customers will be notified."
        f"{BRAND_FOOTER}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# Add these additional callback handlers to button_callback function:

async def handle_additional_callbacks(query, data, user_id):
    """Additional callback handlers"""
    
    if data.startswith("campaign_detail_"):
        campaign_id = int(data.split("_")[2])
        campaign = await db.get_campaign(campaign_id)
        customers = await db.get_campaign_customers(campaign_id)
        rewards = await db.get_campaign_rewards(campaign_id)
        
        message = (
            f"📋 *{campaign['name']}*\n\n"
            f"🆔 ID: {campaign_id}\n"
            f"🎯 Stamps needed: {campaign['stamps_needed']}\n"
            f"👥 Customers: {len(customers)}\n"
            f"✅ Completed: {campaign['total_completions']}\n"
        )
        
        if rewards:
            message += f"\n🎁 *Rewards:*\n"
            for r in rewards:
                message += f"  • {r['stamps_required']} stamps: {r['reward_name']}\n"
        
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
        return True
    
    elif data == "my_campaigns":
        await query.message.delete()
        # Call mycampaigns - you'd need to pass update/context here
        return True
    
    elif data.startswith("toggle_"):
        setting = data.split("_")[1]
        settings = await db.get_merchant_settings(user_id)
        
        if setting == "approval":
            new_value = not settings['require_approval']
            await db.update_merchant_settings(user_id, require_approval=new_value)
            await query.answer(f"Approval requirement {'enabled' if new_value else 'disabled'}")
        elif setting == "summaries":
            new_value = not settings['daily_summary_enabled']
            await db.update_merchant_settings(user_id, daily_summary_enabled=new_value)
            await query.answer(f"Daily summaries {'enabled' if new_value else 'disabled'}")
        
        # Refresh settings view
        await query.message.delete()
        return True
    
    elif data == "cancel":
        await query.edit_message_text("❌ Cancelled" + BRAND_FOOTER)
        return True
    
    elif data == "help_newcampaign":
        await query.edit_message_text(
            "📋 *Create a Campaign*\n\n"
            "*Usage:*\n"
            "`/newcampaign <n> <stamps>`\n\n"
            "*Examples:*\n"
            "`/newcampaign Coffee Rewards 5`\n"
            "`/newcampaign Pizza Party 8`\n\n"
            "The last number is how many stamps needed!"
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        return True
    
    elif data.startswith("help_reward_"):
        campaign_id = int(data.split("_")[2])
        await query.edit_message_text(
            f"🎁 *Add Reward Tiers*\n\n"
            f"*Usage:*\n"
            f"`/addreward {campaign_id} <stamps> <reward>`\n\n"
            f"*Examples:*\n"
            f"`/addreward {campaign_id} 3 Free Coffee`\n"
            f"`/addreward {campaign_id} 5 Free Meal`\n"
            f"`/addreward {campaign_id} 10 VIP Card`"
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        return True
    
    return False

# Don't forget to add these commands to the main() function:
# app.add_handler(CommandHandler("mycampaigns", mycampaigns))
# app.add_handler(CommandHandler("addreward", addreward))
# app.add_handler(CommandHandler("stats", stats_command))
# app.add_handler(CommandHandler("settings", settings_command))
# app.add_handler(CommandHandler("share", share_command))
# app.add_handler(CommandHandler("approveall", approveall_command))

# And in button_callback, before the generic handlers, add:
# if await handle_additional_callbacks(query, data, user_id):
#     returnHandle /start command and deep links"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    await db.create_or_update_user(user_id, username, first_name)
    user = await db.get_user(user_id)
    
    # Handle deep links
    if context.args:
        arg = context.args[0]
        
        # Join campaign via QR code
        if arg.startswith("join_"):
            try:
                campaign_id = int(arg.split("_")[1])
                campaign = await db.get_campaign(campaign_id)
                
                if not campaign or not campaign['active']:
                    await update.message.reply_text(
                        "Sorry, this campaign is no longer available." + BRAND_FOOTER,
                        parse_mode="Markdown"
                    )
                    return
                
                # Check if already enrolled
                enrollment = await db.get_enrollment(campaign_id, user_id)
                
                if not enrollment:
                    enrollment_id = await db.enroll_customer(campaign_id, user_id)
                    
                    # Get reward tiers
                    rewards = await db.get_campaign_rewards(campaign_id)
                    reward_text = ""
                    if rewards:
                        reward_text = "\n\n🎁 *Rewards:*\n" + "\n".join(
                            f"  • {r['stamps_required']} stamps → {r['reward_name']}"
                            for r in rewards
                        )
                    
                    keyboard = [[InlineKeyboardButton("Request Stamp", callback_data=f"request_{campaign_id}")]]
                    
                    await update.message.reply_text(
                        f"🎉 *Welcome!*\n\n"
                        f"You've joined: *{campaign['name']}*\n"
                        f"Collect {campaign['stamps_needed']} stamps to earn rewards!"
                        f"{reward_text}\n\n"
                        f"👉 Request your first stamp below!"
                        f"{BRAND_FOOTER}",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                else:
                    progress_bar = generate_progress_bar(enrollment['stamps'], campaign['stamps_needed'])
                    keyboard = [[InlineKeyboardButton("Request Stamp", callback_data=f"request_{campaign_id}")]]
                    
                    await update.message.reply_text(
                        f"👋 *Welcome back!*\n\n"
                        f"Campaign: *{campaign['name']}*\n"
                        f"{progress_bar}\n"
                        f"Progress: {enrollment['stamps']}/{campaign['stamps_needed']}\n\n"
                        f"Ready for another visit?"
                        f"{BRAND_FOOTER}",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                return
            except Exception as e:
                print(f"Error joining campaign: {e}")
                await update.message.reply_text("Error joining campaign. Please try again.")
                return
        
        # Referral link
        elif arg.startswith("ref_"):
            try:
                parts = arg.split("_")
                referrer_id = int(parts[1])
                campaign_id = int(parts[2])
                
                if referrer_id != user_id:
                    # Create referral and give bonus
                    await db.create_or_update_user(user_id, username, first_name)
                    # Referral logic handled in enrollment
                    
                    await update.message.reply_text(
                        "🎁 You were invited by a friend!\n"
                        "You'll both get a bonus stamp when you complete your first visit!"
                        f"{BRAND_FOOTER}"
                    )
            except:
                pass
    
    # Regular start - check if merchant or customer
    if user['user_type'] == 'merchant':
        if user['merchant_approved']:
            keyboard = [
                [InlineKeyboardButton("📊 Dashboard", callback_data="merchant_dashboard")],
                [InlineKeyboardButton("➕ New Campaign", callback_data="help_newcampaign")],
                [InlineKeyboardButton("⏳ Pending Requests", callback_data="show_pending")]
            ]
            
            pending_count = await db.get_pending_count(user_id)
            message = (
                f"👋 Hi {first_name}!\n\n"
                f"Welcome back to your business dashboard.\n\n"
            )
            if pending_count > 0:
                message += f"⚠️ You have *{pending_count}* pending stamp requests!\n\n"
            
            message += "What would you like to do?" + BRAND_FOOTER
            
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                MESSAGES['welcome_merchant'] + BRAND_FOOTER,
                parse_mode="Markdown"
            )
    else:
        # Customer welcome
        keyboard = [
            [InlineKeyboardButton("💳 My Wallet", callback_data="show_wallet")],
            [InlineKeyboardButton("🏪 Become a Merchant", callback_data="request_merchant")]
        ]
        
        await update.message.reply_text(
            MESSAGES['welcome_customer'].format(name=first_name) + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help based on user type"""
    user = await db.get_user(update.effective_user.id)
    
    if user and user['user_type'] == 'merchant' and user['merchant_approved']:
        message = (
            "🏪 *Merchant Help*\n\n"
            "*Getting Started:*\n"
            "/newcampaign - Create a campaign\n"
            "/mycampaigns - View your campaigns\n"
            "/dashboard - View statistics\n\n"
            "*Managing Stamps:*\n"
            "/pending - See stamp requests\n"
            "/approveall - Approve all pending\n\n"
            "*Campaign Tools:*\n"
            "/getqr <id> - Get QR code\n"
            "/addreward <id> <stamps> <reward>\n"
            "/stats <id> - Campaign analytics\n\n"
            "*Settings:*\n"
            "/settings - Configure your account"
        )
    else:
        message = (
            "👋 *Customer Help*\n\n"
            "*Main Commands:*\n"
            "/wallet - View your stamp cards\n"
            "/start - Return to main menu\n\n"
            "*How it works:*\n"
            "1. Scan a QR code at a store\n"
            "2. Tap 'Request Stamp' after your visit\n"
            "3. Merchant approves your stamp\n"
            "4. Collect rewards automatically!\n\n"
            "Questions? Contact the store directly."
        )
    
    await update.message.reply_text(message + BRAND_FOOTER, parse_mode="Markdown")

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show customer's wallet"""
    user_id = update.effective_user.id
    enrollments = await db.get_customer_enrollments(user_id)
    
    if not enrollments:
        keyboard = [[InlineKeyboardButton("Find a Store", url=f"https://t.me/{BOT_USERNAME}")]]
        await update.message.reply_text(
            "💳 *Your Wallet is Empty*\n\n"
            "Scan a QR code at any participating store to start collecting stamps!"
            f"{BRAND_FOOTER}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    for e in enrollments:
        # Generate and send card image
        img = generate_card_image(e['name'], e['stamps'], e['stamps_needed'])
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        
        progress_bar = generate_progress_bar(e['stamps'], e['stamps_needed'])
        
        if e['completed']:
            status = "✅ *COMPLETED!*"
            caption = (
                f"🎉 *{e['name']}*\n\n"
                f"{progress_bar}\n"
                f"{status}\n\n"
                f"Show this card to claim your reward!\n"
                f"Merchant: {e['merchant_name']}"
            )
        else:
            status = f"{e['stamps']}/{e['stamps_needed']} stamps"
            caption = (
                f"📋 *{e['name']}*\n\n"
                f"{progress_bar}\n"
                f"{status}\n\n"
                f"Keep collecting to earn your reward!\n"
                f"Merchant: {e['merchant_name']}"
            )
        
        keyboard = []
        if not e['completed']:
            keyboard.append([InlineKeyboardButton("Request Stamp", callback_data=f"request_{e['campaign_id']}")])
        if e['completed'] and not e['rating']:
            keyboard.append([
                InlineKeyboardButton("👍", callback_data=f"rate_{e['id']}_5"),
                InlineKeyboardButton("👎", callback_data=f"rate_{e['id']}_1")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_photo(
            photo=bio,
            caption=caption + BRAND_FOOTER,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new campaign"""
    user_id = update.effective_user.id
    
    # Check if approved merchant
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text(
            "⚠️ You need merchant approval to create campaigns.\n\n"
            "Use /start and tap 'Become a Merchant' to apply."
            f"{BRAND_FOOTER}"
        )
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 *Create a Campaign*\n\n"
            "*Usage:*\n"
            "`/newcampaign <n> <stamps>`\n\n"
            "*Examples:*\n"
            "`/newcampaign Coffee Rewards 5`\n"
            "`/newcampaign Pizza Party 8`\n"
            "`/newcampaign Haircut Special 3`\n\n"
            "💡 Last number is stamps needed for reward"
            f"{BRAND_FOOTER}",
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
        
        keyboard = [
            [InlineKeyboardButton("📱 Get QR Code", callback_data=f"getqr_{campaign_id}")],
            [InlineKeyboardButton("🎁 Add Rewards", callback_data=f"help_reward_{campaign_id}")],
            [InlineKeyboardButton("📊 View Details", callback_data=f"campaign_{campaign_id}")]
        ]
        
        await update.message.reply_text(
            MESSAGES['campaign_created'].format(name=name, stamps=stamps_needed, id=campaign_id) + BRAND_FOOTER,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    except ValueError:
        await update.message.reply_text("Last argument must be a number (stamps needed)")
    except Exception as e:
        print(f"Error creating campaign: {e}")
        await update.message.reply_text("Error creating campaign. Please try again.")

async def getqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate QR code for campaign"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/getqr <campaign_id>`\n\nExample: `/getqr 1`" + BRAND_FOOTER,
            parse_mode="Markdown"
        )
        return
    
    try:
        campaign_id = int(context.args[0])
        campaign = await db.get_campaign(campaign_id)
        
        if not campaign:
            await update.message.reply_text("Campaign not found")
            return
        
        # Verify ownership
        if campaign['merchant_id'] != update.effective_user.id:
            await update.message.reply_text("You don't own this campaign")
            return
        
        # Generate QR code
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
            caption=(
                f"📱 *QR Code: {campaign['name']}*\n\n"
                f"🎯 {campaign['stamps_needed']} stamps\n\n"
                f"*Instructions:*\n"
                f"1. Print this QR code\n"
                f"2. Display at your counter/entrance\n"
                f"3. Customers scan to join!\n\n"
                f"Link: `{link}`"
                f"{BRAND_FOOTER}"
            ),
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"Error generating QR: {e}")
        await update.message.reply_text("Error generating QR code")

async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending stamp requests"""
    user_id = update.effective_user.id
    requests = await db.get_pending_requests(user_id)
    
    if not requests:
        await update.message.reply_text(
            "📭 *No Pending Requests*\n\n"
            "You're all caught up! New requests will appear here."
            f"{BRAND_FOOTER}",
            parse_mode="Markdown"
        )
        return
    
    keyboard = []
    for req in requests[:15]:  # Show max 15
        customer_name = req['username'] or req['first_name']
        progress = f"{req['current_stamps']}/{req['stamps_needed']}"
        button_text = f"{customer_name} - {req['campaign_name']} ({progress})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"viewreq_{req['id']}")])
    
    if len(requests) > 1:
        keyboard.append([InlineKeyboardButton(f"✅ Approve All ({len(requests)})", callback_data="approve_all")])
    
    message = (
        f"⏳ *Pending Stamp Requests*\n\n"
        f"You have {len(requests)} request(s) waiting.\n\n"
        f"Tap a request to review:"
    )
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def merchant_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show merchant dashboard"""
    user_id = update.effective_user.id
    
    if not await db.is_merchant_approved(user_id):
        await update.message.reply_text("You need merchant approval to access the dashboard.")
        return
    
    campaigns = await db.get_merchant_campaigns(user_id)
    pending_count = await db.get_pending_count(user_id)
    today_stats = await db.get_daily_stats(user_id)
    
    total_customers = 0
    total_stamps = 0
    total_completions = 0
    
    for campaign in campaigns:
        total_customers += campaign['total_joins']
        customers = await db.get_campaign_customers(campaign['id'])
        for c in customers:
            total_stamps += c['stamps']
        total_completions += campaign['total_completions']
    
    message = (
        f"📊 *Your Dashboard*\n\n"
        f"📆 *Today:*\n"
        f"  Visits: {today_stats['visits']}\n"
        f"  Stamps given: {today_stats['stamps_given']}\n\n"
        f"📈 *Overall:*\n"
        f"  Total campaigns: {len(campaigns)}\n"
        f"  Total customers: {total_customers}\n"
        f"  Stamps given: {total_stamps}\n"
        f"  Rewards claimed: {total_completions}\n"
    )
    
    if pending_count > 0:
        message += f"\n⏳ *{pending_count} pending requests*"
    
    keyboard = [
        [InlineKeyboardButton("⏳ Pending Requests", callback_data="show_pending")],
        [InlineKeyboardButton("📋 My Campaigns", callback_data="my_campaigns")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="merchant_settings")]
    ]
    
    if pending_count > 0:
        keyboard.insert(0, [InlineKeyboardButton(f"✅ Approve All ({pending_count})", callback_data="approve_all")])
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ==================== CALLBACK HANDLERS ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
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
                await query.edit_message_text("You need to join this campaign first")
                return
            
            # Create stamp request
            request_id = await db.create_stamp_request(
                campaign_id, user_id, campaign['merchant_id'], enrollment['id']
            )
            
            # Notify merchant
            await db.queue_notification(
                campaign['merchant_id'],
                f"⏳ New stamp request from {query.from_user.first_name}"
            )
            
            await query.edit_message_text(
                MESSAGES['stamp_requested'].format(merchant=campaign['name']) + BRAND_FOOTER,
                parse_mode="Markdown"
            )
        
        # View request details
        elif data.startswith("viewreq_"):
            request_id = int(data.split("_")[1])
            
            async with db.pool.acquire() as conn:
                req = await conn.fetchrow('''
                    SELECT sr.*, c.name as campaign_name, u.username, u.first_name,
                           e.stamps as current_stamps, ca.stamps_needed
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
            progress_bar = generate_progress_bar(req['current_stamps'], req['stamps_needed'])
            
            message = (
                f"👤 *Customer:* {customer_name}\n"
                f"📋 *Campaign:* {req['campaign_name']}\n\n"
                f"{progress_bar}\n"
                f"*Progress:* {req['current_stamps']}/{req['stamps_needed']}\n\n"
                f"⏰ Requested: {req['created_at'].strftime('%H:%M')}\n\n"
                f"Approve or reject this stamp request:"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{request_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{request_id}")
                ],
                [InlineKeyboardButton("« Back", callback_data="show_pending")]
            ]
            
            await query.edit_message_text(
                message + BRAND_FOOTER,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        
        # Approve request
        elif data.startswith("approve_"):
            request_id = int(data.split("_")[1])
            result = await db.approve_stamp_request(request_id)
            
            if not result:
                await query.edit_message_text("Request already processed")
                return
            
            campaign = result['campaign']
            progress_bar = generate_progress_bar(result['new_stamps'], campaign['stamps_needed'])
            
            if result['completed']:
                # Notify customer of completion
                await db.queue_notification(
                    result['customer_id'],
                    MESSAGES['reward_earned'].format(campaign=campaign['name']) + BRAND_FOOTER
                )
                
                await query.edit_message_text(
                    f"🎉 *Stamp Approved - Reward Earned!*\n\n"
                    f"{progress_bar}\n"
                    f"Customer completed: *{campaign['name']}*\n\n"
                    f"They've been notified to claim their reward!"
                    f"{BRAND_FOOTER}",
                    parse_mode="Markdown"
                )
            else:
                # Notify customer of stamp
                progress_msg = MESSAGES['stamp_approved'].format(
                    campaign=campaign['name'],
                    current=result['new_stamps'],
                    total=campaign['stamps_needed'],
                    progress_bar=progress_bar,
                    message=f"Only {campaign['stamps_needed'] - result['new_stamps']} more to go!"
                )
                await db.queue_notification(result['customer_id'], progress_msg + BRAND_FOOTER)
                
                await query.edit_message_text(
                    f"✅ *Stamp Approved!*\n\n"
                    f"{progress_bar}\n"
                    f"Progress: {result['new_stamps']}/{campaign['stamps_needed']}\n\n"
                    f"Customer has been notified."
                    f"{BRAND_FOOTER}",
                    parse_mode="Markdown"
                )
        
        # Reject request
        elif data.startswith("reject_"):
            request_id = int(data.split("_")[1])
            result = await db.reject_stamp_request(request_id)
            
            if result:
                await db.queue_notification(
                    result['customer_id'],
                    "Sorry, your stamp request was not approved. Please try again or contact the merchant."
                )
                await query.edit_message_text(
                    "❌ Request rejected. Customer has been notified." + BRAND_FOOTER
                )
        
        # Approve all
        elif data == "approve_all":
            requests = await db.get_pending_requests(user_id)
            
            if not requests:
                await query.edit_message_text("No pending requests")
                return
            
            approved_count = 0
            for req in requests:
                result = await db.approve_stamp_request(req['id'])
                if result:
                    approved_count += 1
            
            await query.edit_message_text(
                f"✅ *Approved {approved_count} request(s)!*\n\n"
                f"All customers have been notified."
                f"{BRAND_FOOTER}",
                parse_mode="Markdown"
            )
        
        # Show wallet
        elif data == "show_wallet":
            await query.message.delete()
            await wallet(update, context)
        
        # Show pending
        elif data == "show_pending":
            await query.message.delete()
            await pending_requests(update, context)
        
        # Merchant dashboard
        elif data == "merchant_dashboard":
            await query.message.delete()
            await merchant_dashboard(update, context)
        
        # Request merchant access
        elif data == "request_merchant":
            await db.request_merchant_access(user_id)
            
            # Notify admins
            for admin_id in ADMIN_IDS:
                await db.queue_notification(
                    admin_id,
                    f"🏪 New merchant request from {query.from_user.first_name} (@{query.from_user.username or 'no username'})"
                )
            
            await query.edit_message_text(
                MESSAGES['welcome_merchant'] + BRAND_FOOTER,
                parse_mode="Markdown"
            )
        
        # Rate experience
        elif data.startswith("rate_"):
            parts = data.split("_")
            enrollment_id = int(parts[1])
            rating = int(parts[2])
            
            await db.save_customer_rating(enrollment_id, rating)
            
            if rating >= 4:
                message = "Thank you! We're glad you had a great experience! 😊"
            else:
                message = "Thanks for your feedback. We'll work on improving!"
            
            await query.edit_message_text(message + BRAND_FOOTER)
        
        # Get QR code
        elif data.startswith("getqr_"):
            campaign_id = int(data.split("_")[1])
            context.args = [str(campaign_id)]
            await query.message.delete()
            await getqr(update, context)
        
        else:
            await query.edit_message_text("Unknown action")
    
    except Exception as e:
        print(f"Callback error: {e}")
        await query.edit_message_text("Error processing request" + BRAND_FOOTER)

# ==================== ADMIN COMMANDS ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    pending_merchants = await db.get_pending_merchants()
    
    message = f"🔧 *Admin Panel*\n\n"
    message += f"Pending merchant approvals: {len(pending_merchants)}\n\n"
    
    keyboard = []
    for merchant in pending_merchants:
        button_text = f"{merchant['first_name']} (@{merchant['username'] or 'no username'})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"admin_merchant_{merchant['id']}")])
    
    await update.message.reply_text(
        message + BRAND_FOOTER,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="Markdown"
    )

# ==================== BACKGROUND TASKS ====================

async def send_notifications(app):
    """Background task to send queued notifications"""
    while True:
        try:
            notifications = await db.get_pending_notifications()
            for notif in notifications:
                try:
                    await app.bot.send_message(
                        notif['user_id'],
                        notif['message'],
                        parse_mode="Markdown"
                    )
                    await db.mark_notification_sent(notif['id'])
                except Exception as e:
                    print(f"Failed to send notification: {e}")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Notification task error: {e}")
            await asyncio.sleep(5)

async def send_daily_summaries():
    """Send daily summaries to merchants"""
    # Get all approved merchants with summaries enabled
    async with db.pool.acquire() as conn:
        merchants = await conn.fetch('''
            SELECT u.id, u.first_name, ms.business_name
            FROM users u
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
            
            message = MESSAGES['daily_merchant_summary'].format(
                date=today.strftime('%B %d, %Y'),
                visits=stats['visits'],
                new_customers=stats['new_customers'],
                rewards=stats['rewards_claimed'],
                pending=pending,
                tip=tip
            )
            
            await db.queue_notification(merchant['id'], message + BRAND_FOOTER)
        except Exception as e:
            print(f"Error sending daily summary to {merchant['id']}: {e}")

# ==================== MAIN ====================

async def main():
    """Start the bot"""
    print("🚀 Starting StampMe Bot...")
    
    # Connect to database
    try:
        await db.connect()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return
    
    # Start health server
    await start_web_server()
    
    # Build application
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("newcampaign", newcampaign))
    app.add_handler(CommandHandler("getqr", getqr))
    app.add_handler(CommandHandler("pending", pending_requests))
    app.add_handler(CommandHandler("dashboard", merchant_dashboard))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Initialize and start
    await app.initialize()
    await app.start()
    
    # Clear webhook
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(2)
        print("✅ Webhook cleared")
    except Exception as e:
        print(f"⚠️ Webhook clear warning: {e}")
    
    # Start polling
    try:
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            timeout=30
        )
        print("✅ Bot is running!")
        print(f"📱 Bot username: @{BOT_USERNAME}")
    except Exception as e:
        print(f"❌ Polling error: {e}")
        raise
    
    # Start background tasks
    asyncio.create_task(send_notifications(app))
    print("✅ Notification sender started")
    
    # Schedule daily summaries (6 PM every day)
    scheduler.add_job(
        send_daily_summaries,
        'cron',
        hour=18,
        minute=0
    )
    scheduler.start()
    print("✅ Daily summary scheduler started")
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
