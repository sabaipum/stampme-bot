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
