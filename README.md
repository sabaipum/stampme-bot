# Project documentation
# ============================================

"""
# StampMe - Digital Loyalty Cards for Telegram

A complete digital stamp card system built for Telegram, allowing businesses to reward customer loyalty through an intuitive, conversational interface.

## Features

### For Customers 👥
- **Easy Enrollment**: Scan QR codes to join campaigns instantly
- **Visual Wallet**: Beautiful stamp cards with progress tracking
- **Smart Notifications**: Get notified when stamps are approved
- **Reward Tracking**: See exactly how close you are to rewards
- **Rate & Review**: Share feedback about your experience

### For Merchants 🏪
- **Simple Setup**: Create campaigns in seconds
- **QR Code Generation**: Print-ready QR codes for your store
- **Approval Workflow**: Review and approve stamp requests
- **Real-time Dashboard**: See visits, stamps, and rewards
- **Daily Summaries**: Automated reports with business tips
- **Multi-tier Rewards**: Create multiple reward levels
- **Settings Control**: Customize approval requirements

### For Admins 🔧
- **Merchant Approval**: Review and approve business accounts
- **System Monitoring**: Oversee platform activity
- **Quality Control**: Ensure merchant legitimacy

## Technology Stack

- **Python 3.11**: Core application
- **python-telegram-bot 21.9**: Telegram Bot API
- **PostgreSQL**: Database with asyncpg
- **aiohttp**: Async web server
- **APScheduler**: Background task scheduling
- **Pillow**: Image generation
- **qrcode**: QR code generation

## Quick Start

### 1. Prerequisites
- Telegram Bot Token (from @BotFather)
- PostgreSQL database
- Python 3.11+

### 2. Environment Variables
```bash
BOT_TOKEN=your_bot_token
BOT_USERNAME=your_bot_username
DATABASE_URL=postgresql://...
ADMIN_IDS=123456789,987654321
PORT=10000
```

### 3. Installation
```bash
pip install -r requirements.txt
python stampme_bot.py
```

### 4. Database Setup
Tables are created automatically on first run:
- users
- campaigns
- reward_tiers
- enrollments
- stamp_requests
- transactions
- referrals
- merchant_settings
- notifications
- daily_stats

## User Flows

### Customer Flow
1. User scans QR code → Opens Telegram
2. Taps "Start" → Joins campaign automatically
3. Makes a purchase → Taps "Request Stamp"
4. Merchant approves → Customer gets notification
5. Completes stamps → Earns reward!

### Merchant Flow
1. Requests merchant access
2. Admin approves account
3. Creates campaign with /newcampaign
4. Generates QR code with /getqr
5. Displays QR at store
6. Reviews stamp requests with /pending
7. Approves/rejects with one tap
8. Receives daily summary at 6 PM

### Admin Flow
1. Receives merchant request notification
2. Uses /admin to view pending requests
3. Reviews merchant profile
4. Approves or rejects application
5. Merchant gets notified

## Commands

### Customer Commands
- `/start` - Welcome & main menu
- `/wallet` - View all stamp cards
- `/help` - Get help

### Merchant Commands
- `/newcampaign <n> <stamps>` - Create campaign
- `/getqr <id>` - Generate QR code
- `/pending` - View stamp requests
- `/dashboard` - View statistics
- `/mycampaigns` - List campaigns
- `/addreward <id> <stamps> <reward>` - Add reward tier
- `/settings` - Merchant settings

### Admin Commands
- `/admin` - Admin panel

## Architecture

### Database Schema
```
users (customers & merchants & admins)
  ├── campaigns (merchant's loyalty programs)
  │     ├── reward_tiers (multi-level rewards)
  │     └── enrollments (customer participation)
  │           ├── stamp_requests (approval workflow)
  │           └── transactions (stamp history)
  ├── referrals (viral growth)
  └── merchant_settings (configuration)
```

### Background Tasks
1. **Notification Sender**: Processes queued notifications every 5 seconds
2. **Daily Summaries**: Sends merchant reports at 6 PM daily
3. **Database Cleanup**: (Can be added) Remove old completed campaigns

## Design Philosophy

### Conversational Interface
- Natural language, not robotic
- Friendly, encouraging tone
- Clear, concise messages
- Emoji for visual clarity

### Visual Experience
- Progress bars for all stamps
- Beautiful generated stamp cards
- QR codes embedded in messages
- Consistent branding

### Simplicity First
- One primary action per message
- Inline buttons for quick actions
- No complex forms or menus
- Guided workflows

## Message Templates

All messages follow a pattern:
```
[Emoji] Title

Body with clear information

[Call to action]

💙 Powered by StampMe
```

## Deployment

### Render.com (Recommended)
1. Create PostgreSQL database
2. Create Web Service
3. Set environment variables
4. Deploy from GitHub

### Heroku
1. Create app
2. Add PostgreSQL addon
3. Set config vars
4. Deploy with Git

### VPS/Docker
1. Install PostgreSQL
2. Clone repository
3. Set environment variables
4. Run with systemd/docker

## Testing

### Manual Testing
1. Create test merchant account
2. Approve via admin
3. Create test campaign
4. Scan QR with second account
5. Request stamp
6. Approve as merchant
7. Check notifications

### Load Testing
- Create multiple campaigns
- Simulate concurrent requests
- Monitor database performance
- Check notification queue

## Security

- ✅ Admin-only merchant approval
- ✅ Campaign ownership verification
- ✅ SQL injection prevention (parameterized queries)
- ✅ Rate limiting (via Telegram)
- ✅ Input validation
- ✅ Environment variables for secrets

## Performance

- Async/await throughout
- Connection pooling (2-10)
- Efficient database queries
- Background task processing
- Message queuing

## Monitoring

### Health Checks
- HTTP endpoint at `/` and `/health`
- Database connection status
- Bot polling status

### Logs
- Structured logging
- Error tracking
- Performance metrics

## Future Enhancements

### Phase 3 (Optional)
- Web dashboard for merchants
- Advanced analytics & charts
- Email notifications
- SMS integration
- Payment processing
- Multi-language support
- Mobile app companion
- API for POS integration
- Franchise management
- Customer segments

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create feature branch
3. Make changes
4. Test thoroughly
5. Submit pull request

## License

MIT License - See LICENSE file

## Support

For issues and questions:
- GitHub Issues
- Email: support@stampme.example
- Telegram: @stampme_support

## Changelog

### v2.0.0 (Current)
- Complete rewrite with approval workflow
- Admin merchant approval system
- Visual stamp cards
- Daily summaries
- Rating system
- Background tasks
- Refined UX

### v1.0.0
- Initial release
- Basic stamp tracking
- QR code generation
- Simple dashboard

---

Built with ❤️ for businesses and their customers

💙 Powered by StampMe
"""
    # ============================================

    # StampMe Bot - Complete Testing & User Guide

## 🔧 STEP 0: Fix Bot Conflict (REQUIRED!)

**Before any testing, you MUST clear the webhook:**

1. Go to Render → Your Service → Environment
2. Copy your `BOT_TOKEN` value
3. Visit this URL in browser: `https://api.telegram.org/bot<YOUR_TOKEN>/deleteWebhook?drop_pending_updates=true`
4. You should see: `{"ok":true,"result":true}`
5. Wait 30 seconds
6. Restart your Render service

**Without this step, NOTHING will work!**

---

## 👥 Testing Accounts You'll Need

1. **Your Personal Account** (Admin & Merchant)
2. **Test Account 1** (Customer)
3. **Test Account 2** (Another merchant - optional)

---

## 🎯 WORKFLOW 1: Admin Approves Merchant

### Step 1: Set Admin ID
In Render environment variables, set:
```
ADMIN_IDS=YOUR_TELEGRAM_USER_ID
```

**Find your Telegram User ID:**
- Message @userinfobot on Telegram
- It will reply with your ID (e.g., `123456789`)

### Step 2: Request Merchant Access
**Using Test Account or Your Account:**

1. Open bot: `@your_bot_username`
2. Send: `/start`
3. Click: **"🏪 Become a Merchant"** button
4. You'll see: "⏳ Request Sent! Your merchant application is being reviewed..."

### Step 3: Admin Approves
**Using Your Admin Account:**

1. You'll receive notification: "🏪 New merchant request from [name]"
2. Send: `/admin`
3. You'll see list of pending merchants
4. Click on the merchant name to approve
5. They'll get notified: "🎉 Congratulations! Your merchant account has been approved!"

**Result:** Merchant can now create campaigns

---

## 🏪 WORKFLOW 2: Merchant Creates Campaign

**Using Approved Merchant Account:**

### Step 1: Create Campaign
```
/newcampaign Coffee Rewards 5
```

Response:
```
✅ Campaign Created!

📋 Coffee Rewards
🎯 5 stamps needed
🆔 Campaign ID: 1

👉 Get your QR code below!
[📱 Get QR Code] button
```

### Step 2: Get QR Code
- Click the **"📱 Get QR Code"** button, OR
- Send: `/getqr 1`

You'll receive:
- QR code image
- Link: `https://t.me/your_bot?start=join_1`

### Step 3: Add Rewards (Optional)
```
/addreward 1 3 Free Coffee
/addreward 1 5 Free Meal
```

### Step 4: View Campaigns
```
/mycampaigns
```

Shows:
```
📋 Your Campaigns

Coffee Rewards (ID: 1)
  🎯 5 stamps
  👥 0 customers
  ✅ 0 completed
```

---

## 👤 WORKFLOW 3: Customer Joins Campaign

**Using Customer Test Account:**

### Step 1: Scan QR Code
- Click the link from QR code, OR
- Visit: `https://t.me/your_bot?start=join_1`

Response:
```
🎉 Welcome!

You've joined: Coffee Rewards

Collect 5 stamps to earn rewards!

👉 Request your first stamp below!
[Request Stamp] button
```

### Step 2: Check Wallet
```
/wallet
```

You'll see:
- Visual stamp card image
- Progress: 0/5 stamps
- [Request Stamp] button

---

## ⭐ WORKFLOW 4: Customer Requests Stamp

**After customer visits store:**

### Customer Side:
1. Open bot
2. Send: `/wallet`
3. Click: **"Request Stamp"** button

Response:
```
⏳ Stamp Request Sent!

The merchant will review it soon. You'll get notified!
```

### Merchant Side:
Merchant receives notification:
```
⏳ New stamp request from [customer name]
```

---

## ✅ WORKFLOW 5: Merchant Approves Stamp

**Using Merchant Account:**

### Step 1: View Pending Requests
```
/pending
```

OR

```
/stamp
```

Shows:
```
⏳ Pending Requests (1)

Tap to review:
[Customer Name - Coffee Rewards (0/5)]
```

### Step 2: Review Request
- Click on customer name

Shows:
```
👤 Customer Name
📋 Coffee Rewards

█░░░░░░░░░
0/5 stamps

Approve or reject?
[✅ Approve] [❌ Reject]
```

### Step 3: Approve
- Click: **"✅ Approve"**

Response to Merchant:
```
✅ Approved!

█░░░░░░░░░
1/5 stamps
```

Response to Customer:
```
⭐ New Stamp!

Coffee Rewards
█░░░░░░░░░
Progress: 1/5

🎯 Only 4 more stamps to earn your reward!
```

---

## 🎉 WORKFLOW 6: Complete Campaign

**Repeat WORKFLOW 4 & 5 until customer reaches 5 stamps**

### When 5th Stamp Approved:

**Customer receives:**
```
🎉 REWARD EARNED!

You've completed Coffee Rewards!

█████████
✅ 5/5 stamps collected

🎁 Show this message at the store to claim your reward!
```

**Merchant sees:**
```
🎉 Approved - Reward Earned!

██████████
Customer completed the campaign!
```

---

## 📊 WORKFLOW 7: View Statistics

**Merchant Commands:**

### Dashboard
```
/dashboard
```

Shows:
```
📊 Your Dashboard

📆 Today:
  Visits: 5
  Stamps given: 5

📈 Overall:
  Campaigns: 1
  Customers: 3
  Rewards: 1

⏳ 2 pending requests
```

### Campaign Stats
```
/stats 1
```

Shows:
```
📊 Campaign Analytics

📋 Coffee Rewards
🆔 ID: 1

👥 Customers:
  Total: 3
  Completed: 1
  Rate: 33.3%

⭐ Stamps:
  Total given: 8
  Needed: 5
```

---

## 🔗 WORKFLOW 8: Referral System

**Customer shares with friend:**

### Step 1: Get Referral Link
```
/share 1
```

Receives:
```
🎁 Share & Earn

Share this link:
https://t.me/your_bot?start=ref_123456_1

You both get a bonus stamp when they join!
```

### Step 2: Friend Joins
Friend clicks link and joins campaign

### Result:
- Both get 1 bonus stamp
- Referrer notified: "You got a referral bonus!"

---

## 🎯 WORKFLOW 9: Multi-Tier Rewards

**Merchant adds reward tiers:**

```
/addreward 1 3 Free Cookie
/addreward 1 5 Free Coffee
/addreward 1 10 VIP Card
```

**When customer joins:**
```
🎉 Welcome!

You've joined: Coffee Rewards

🎁 Rewards:
  • 3 stamps → Free Cookie
  • 5 stamps → Free Coffee
  • 10 stamps → VIP Card
```

---

## 📱 ALL COMMANDS REFERENCE

### Customer Commands
| Command | Description |
|---------|-------------|
| `/start` | Open main menu |
| `/wallet` | View stamp cards |
| `/help` | Get help |

### Merchant Commands (After Approval)
| Command | Description | Example |
|---------|-------------|---------|
| `/newcampaign` | Create campaign | `/newcampaign Pizza 8` |
| `/getqr <id>` | Get QR code | `/getqr 1` |
| `/mycampaigns` | List campaigns | `/mycampaigns` |
| `/pending` | View requests | `/pending` |
| `/stamp` | Same as pending | `/stamp` |
| `/dashboard` | View stats | `/dashboard` |
| `/stats <id>` | Campaign analytics | `/stats 1` |
| `/addreward` | Add reward tier | `/addreward 1 5 Free Coffee` |
| `/share <id>` | Get referral link | `/share 1` |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/admin` | View pending merchants |

---

## 🧪 COMPLETE TEST SCRIPT

Follow this exact sequence to test everything:

### 1. Setup (5 minutes)
```
✓ Set ADMIN_IDS in Render
✓ Clear webhook (URL method)
✓ Restart service
✓ Wait 30 seconds
```

### 2. Admin Flow (2 minutes)
```
Account: Your admin account

✓ /start
✓ Click "Become a Merchant"
✓ /admin (should see your request)
✓ Click your name to approve
✓ Confirm approval message
```

### 3. Merchant Flow (5 minutes)
```
Account: Your merchant account (now approved)

✓ /start (should see merchant dashboard)
✓ /newcampaign TestCafe 5
✓ /getqr 1 (save QR code)
✓ /addreward 1 3 Free Coffee
✓ /mycampaigns (verify campaign exists)
✓ /dashboard (check stats)
```

### 4. Customer Flow (5 minutes)
```
Account: Test customer account

✓ Click QR link or visit: https://t.me/bot?start=join_1
✓ Verify welcome message
✓ /wallet (check card appears)
✓ Click "Request Stamp"
✓ Verify confirmation message
```

### 5. Approval Flow (3 minutes)
```
Account: Switch back to merchant

✓ Check for notification
✓ /pending (see request)
✓ Click customer name
✓ Click "✅ Approve"
✓ Verify approval message

Account: Switch to customer
✓ Check for stamp notification
✓ /wallet (verify stamp added)
```

### 6. Completion Flow (5 minutes)
```
Repeat steps 4-5 four more times until 5/5 stamps

Final approval should show:
Merchant: "🎉 Approved - Reward Earned!"
Customer: "🎉 REWARD EARNED!"
```

### 7. Analytics (2 minutes)
```
Account: Merchant

✓ /dashboard (verify updated stats)
✓ /stats 1 (check campaign details)
✓ Verify completion count = 1
```

### 8. Referral Test (3 minutes)
```
Account: Customer

✓ /share 1 (get link)

Account: Another test customer
✓ Click referral link
✓ Verify both got bonus stamp
```

---

## 🐛 TROUBLESHOOTING

### Bot Not Responding
**Problem:** Commands don't work
**Fix:** Clear webhook: `https://api.telegram.org/bot<TOKEN>/deleteWebhook?drop_pending_updates=true`

### "Error processing request"
**Problem:** Buttons crash
**Fix:** Check Render logs for specific error

### Commands Show Usage Only
**Problem:** Commands work but don't execute
**Fix:** Check database is connected (see Render logs)

### Inline Buttons Disappear
**Problem:** Buttons vanish when clicked
**Fix:** This is fixed in latest code - update `button_callback` function

### "Campaign not found"
**Problem:** QR link doesn't work
**Fix:** Campaign ID might be wrong - use `/mycampaigns` to verify

### "Merchant approval required"
**Problem:** Can't create campaigns
**Fix:** Admin must approve via `/admin` command

---

## 📊 SUCCESS METRICS

After testing, verify:
- ✅ Merchants can be approved
- ✅ Campaigns can be created
- ✅ QR codes work
- ✅ Customers can join
- ✅ Stamp requests work
- ✅ Approvals work
- ✅ Notifications sent
- ✅ Rewards tracked
- ✅ Dashboard shows correct stats
- ✅ Wallet displays cards
- ✅ Referrals work

---

## 🎬 VIDEO TEST SCENARIO

**Title:** "Coffee Shop Loyalty Program"

**Characters:**
- Admin (You)
- Merchant: "Joe's Coffee Shop"
- Customer: "Sarah"

**Script:**

1. **Setup (Admin)**
   - Approve Joe's Coffee Shop as merchant
   
2. **Campaign Creation (Joe)**
   - Creates "Coffee Lovers" campaign
   - 5 stamps = Free Coffee
   - Generates QR code
   - Prints and displays at counter

3. **Customer Journey (Sarah)**
   - Day 1: Scans QR, joins, orders coffee, requests stamp
   - Joe approves immediately
   - Sarah sees: 1/5 stamps
   
4. **Repeat Visits**
   - Day 2-5: Same process
   
5. **Reward**
   - Day 5: Sarah gets 5th stamp
   - Notification: "REWARD EARNED!"
   - Shows phone to Joe
   - Gets free coffee

6. **Referral**
   - Sarah shares link with friend Tom
   - Both get bonus stamp
   - Tom starts collecting

**Result:** Complete end-to-end demonstration

---

## 💡 TIPS FOR TESTING

1. **Use Real Telegram Accounts** - Don't use bot testing environments
2. **Test on Mobile** - Most users will use phones
3. **Take Screenshots** - Document each step
4. **Check Notifications** - Verify they arrive
5. **Test Edge Cases** - What if user joins twice? Requests stamp twice?
6. **Time It** - How long does each workflow take?
7. **Get Feedback** - Ask real users to test

---

## 🚀 GO LIVE CHECKLIST

Before launching:
- [ ] All workflows tested successfully
- [ ] Admin approval process working
- [ ] QR codes generating correctly
- [ ] Notifications delivering
- [ ] Database persisting data
- [ ] No bot conflicts
- [ ] Error messages are user-friendly
- [ ] Help documentation ready
- [ ] Support contact available
- [ ] Backup strategy in place

---

## 📞 SUPPORT COMMANDS

If users need help:
```
/help - Show all commands
/start - Reset to main menu
/wallet - View stamp cards
```

Admin support:
```
/admin - Review pending merchants
Check Render logs for errors
Monitor database size
```

---

**Your bot is ready when all workflows complete successfully!** 🎉
