import asyncio
import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def migrate():
    """Drop all tables and recreate fresh schema"""
    print("🔄 Starting database migration...")
    
    # Connect to database
    conn = await asyncpg.connect(DATABASE_URL)
    
    print("🗑️  Dropping existing tables...")
    
    # Drop all tables in correct order (reverse of dependencies)
    tables_to_drop = [
        'daily_stats',
        'notifications',
        'merchant_settings',
        'referrals',
        'transactions',
        'stamp_requests',
        'enrollments',
        'reward_tiers',
        'campaigns',
        'users'
    ]
    
    for table in tables_to_drop:
        try:
            await conn.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
            print(f"  ✓ Dropped {table}")
        except Exception as e:
            print(f"  ⚠️  Could not drop {table}: {e}")
    
    print("\n✨ Creating fresh tables...")
    
    # Users
    await conn.execute('''
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            user_type TEXT DEFAULT 'customer',
            merchant_approved BOOLEAN DEFAULT FALSE,
            merchant_approved_at TIMESTAMP,
            merchant_approved_by BIGINT,
            total_stamps_earned INTEGER DEFAULT 0,
            total_rewards_claimed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            last_active TIMESTAMP DEFAULT NOW(),
            CHECK (user_type IN ('customer', 'merchant', 'admin'))
        )
    ''')
    print("  ✓ Created users")
    
    # Campaigns
    await conn.execute('''
        CREATE TABLE campaigns (
            id SERIAL PRIMARY KEY,
            merchant_id BIGINT REFERENCES users(id),
            name TEXT NOT NULL,
            description TEXT,
            stamps_needed INTEGER NOT NULL,
            reward_description TEXT,
            expires_at TIMESTAMP,
            active BOOLEAN DEFAULT TRUE,
            total_joins INTEGER DEFAULT 0,
            total_completions INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    print("  ✓ Created campaigns")
    
    # Reward tiers
    await conn.execute('''
        CREATE TABLE reward_tiers (
            id SERIAL PRIMARY KEY,
            campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
            stamps_required INTEGER NOT NULL,
            reward_name TEXT NOT NULL,
            reward_description TEXT
        )
    ''')
    print("  ✓ Created reward_tiers")
    
    # Enrollments
    await conn.execute('''
        CREATE TABLE enrollments (
            id SERIAL PRIMARY KEY,
            campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
            customer_id BIGINT REFERENCES users(id),
            stamps INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT NOW(),
            last_stamp_at TIMESTAMP,
            completed BOOLEAN DEFAULT FALSE,
            completed_at TIMESTAMP,
            rating INTEGER,
            feedback TEXT,
            UNIQUE(campaign_id, customer_id)
        )
    ''')
    print("  ✓ Created enrollments")
    
    # Stamp requests
    await conn.execute('''
        CREATE TABLE stamp_requests (
            id SERIAL PRIMARY KEY,
            campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
            customer_id BIGINT REFERENCES users(id),
            merchant_id BIGINT REFERENCES users(id),
            enrollment_id INTEGER REFERENCES enrollments(id),
            status TEXT DEFAULT 'pending',
            customer_message TEXT,
            rejection_reason TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            processed_at TIMESTAMP,
            CHECK (status IN ('pending', 'approved', 'rejected'))
        )
    ''')
    print("  ✓ Created stamp_requests")
    
    # Transactions
    await conn.execute('''
        CREATE TABLE transactions (
            id SERIAL PRIMARY KEY,
            enrollment_id INTEGER REFERENCES enrollments(id),
            merchant_id BIGINT,
            action_type TEXT,
            stamps_change INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    print("  ✓ Created transactions")
    
    # Referrals
    await conn.execute('''
        CREATE TABLE referrals (
            id SERIAL PRIMARY KEY,
            referrer_id BIGINT REFERENCES users(id),
            referred_id BIGINT REFERENCES users(id),
            campaign_id INTEGER REFERENCES campaigns(id),
            bonus_given BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    print("  ✓ Created referrals")
    
    # Merchant settings
    await conn.execute('''
        CREATE TABLE merchant_settings (
            merchant_id BIGINT PRIMARY KEY REFERENCES users(id),
            require_approval BOOLEAN DEFAULT TRUE,
            auto_approve BOOLEAN DEFAULT FALSE,
            daily_summary_enabled BOOLEAN DEFAULT TRUE,
            notification_hour INTEGER DEFAULT 18,
            business_name TEXT,
            business_type TEXT,
            location TEXT
        )
    ''')
    print("  ✓ Created merchant_settings")
    
    # Notifications
    await conn.execute('''
        CREATE TABLE notifications (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            message TEXT,
            sent BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    print("  ✓ Created notifications")
    
    # Daily stats
    await conn.execute('''
        CREATE TABLE daily_stats (
            id SERIAL PRIMARY KEY,
            merchant_id BIGINT REFERENCES users(id),
            date DATE DEFAULT CURRENT_DATE,
            visits INTEGER DEFAULT 0,
            new_customers INTEGER DEFAULT 0,
            stamps_given INTEGER DEFAULT 0,
            rewards_claimed INTEGER DEFAULT 0,
            UNIQUE(merchant_id, date)
        )
    ''')
    print("  ✓ Created daily_stats")
    
    await conn.close()
    
    print("\n✅ Migration completed successfully!")
    print("🚀 You can now start the bot")

if __name__ == "__main__":
    asyncio.run(migrate())
