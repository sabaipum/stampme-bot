import os

# Bot Configuration
TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "stampmebot")
PORT = int(os.getenv("PORT", 10000))
DATABASE_URL = os.getenv("DATABASE_URL")

# Admin Configuration
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

# Brand Footer
BRAND_FOOTER = "\n\n💙 _Powered by StampMe_"

# Message Templates
MESSAGES = {
    'welcome_customer': (
        "👋 Hi {name}!\n\n"
        "Welcome to StampMe! We help you collect stamps "
        "and earn rewards at your favorite stores.\n\n"
        "🎯 *How it works:*\n"
        "1. Scan a QR code at any store\n"
        "2. Request a stamp after your visit\n"
        "3. Collect rewards automatically!\n\n"
        "Try /wallet to see your cards."
    ),
    'welcome_merchant': (
        "🏪 Welcome to StampMe for Business!\n\n"
        "You're almost ready to start rewarding your customers.\n\n"
        "⏳ *Next step:*\n"
        "Your account is pending approval by our team. "
        "You'll be notified within 24 hours.\n\n"
        "Questions? Contact our support team."
    ),
    'merchant_approved': (
        "🎉 *Congratulations!*\n\n"
        "Your merchant account has been approved!\n\n"
        "🚀 *Get started:*\n"
        "1. Create your first campaign: /newcampaign\n"
        "2. Generate a QR code: /getqr\n"
        "3. Display it at your store\n\n"
        "Need help? Use /help anytime!"
    ),
    'campaign_created': (
        "✅ *Campaign Created!*\n\n"
        "📋 {name}\n"
        "🎯 {stamps} stamps to reward\n"
        "🆔 Campaign ID: {id}\n\n"
        "👉 *Next steps:*\n"
        "Get your QR code: /getqr {id}"
    ),
    'stamp_requested': (
        "⏳ *Stamp request sent!*\n\n"
        "We've notified {merchant} about your visit.\n"
        "You'll get a notification when it's approved.\n\n"
        "👀 Check progress: /wallet"
    ),
    'stamp_approved': (
        "⭐ *New stamp added!*\n\n"
        "📋 {campaign}\n"
        "Progress: {current}/{total}\n\n"
        "{progress_bar}\n\n"
        "{message}"
    ),
    'reward_earned': (
        "🎉 *REWARD EARNED!*\n\n"
        "Congratulations! You've completed:\n"
        "📋 {campaign}\n\n"
        "🎁 Show this message to claim your reward!\n\n"
        "👏 Keep collecting more stamps at other stores!"
    ),
    'daily_merchant_summary': (
        "📆 *Daily Summary - {date}*\n\n"
        "👥 Visits today: {visits}\n"
        "✨ New customers: {new_customers}\n"
        "🎁 Rewards claimed: {rewards}\n"
        "⏳ Pending requests: {pending}\n\n"
        "💡 *Tip:* {tip}"
    ),
}

# Tips for merchants
MERCHANT_TIPS = [
    "Post your QR code near the counter to boost engagement!",
    "Respond to stamp requests quickly to keep customers happy.",
    "Add multiple reward tiers to encourage repeat visits.",
    "Share your referral link on social media to attract new customers.",
    "Update your campaign description to make it more appealing.",
    "Check your analytics weekly to understand customer behavior.",
    "Consider running a limited-time bonus stamp promotion!",
]


# ============================================



