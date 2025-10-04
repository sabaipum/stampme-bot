import asyncpg
import os
from datetime import datetime, timedelta

class Database:
    def __init__(self):
        self.pool = None
        self.db_url = os.getenv('DATABASE_URL')
    
    async def connect(self):
        """Connect to PostgreSQL database"""
        self.pool = await asyncpg.create_pool(
            self.db_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        await self.create_tables()
    
    async def create_tables(self):
        """Create all necessary tables"""
        async with self.pool.acquire() as conn:
            # Merchants table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS merchants (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Campaigns table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS campaigns (
                    id SERIAL PRIMARY KEY,
                    merchant_id BIGINT REFERENCES merchants(id),
                    name TEXT NOT NULL,
                    stamps_needed INTEGER NOT NULL,
                    description TEXT,
                    image_url TEXT,
                    expires_at TIMESTAMP,
                    terms TEXT,
                    locations TEXT[],
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Rewards table (multi-tier)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rewards (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
                    stamps_required INTEGER NOT NULL,
                    reward_name TEXT NOT NULL,
                    reward_description TEXT
                )
            ''')
            
            # Customers table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    referred_by BIGINT,
                    total_stamps INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Campaign enrollments
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS enrollments (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
                    customer_id BIGINT REFERENCES customers(id),
                    stamps INTEGER DEFAULT 0,
                    joined_at TIMESTAMP DEFAULT NOW(),
                    last_stamp_at TIMESTAMP,
                    completed BOOLEAN DEFAULT FALSE,
                    UNIQUE(campaign_id, customer_id)
                )
            ''')
            
            # Stamps/transactions
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    enrollment_id INTEGER REFERENCES enrollments(id) ON DELETE CASCADE,
                    merchant_id BIGINT,
                    location TEXT,
                    stamps_added INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Referrals
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT REFERENCES customers(id),
                    referred_id BIGINT REFERENCES customers(id),
                    campaign_id INTEGER REFERENCES campaigns(id),
                    bonus_given BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
    
    async def close(self):
        """Close database connection"""
        if self.pool:
            await self.pool.close()
    
    # Merchant operations
    async def create_merchant(self, user_id, username, first_name):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO merchants (id, username, first_name) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING',
                user_id, username, first_name
            )
    
    # Campaign operations
    async def create_campaign(self, merchant_id, name, stamps_needed, description=None, expires_days=None, terms=None, locations=None):
        async with self.pool.acquire() as conn:
            expires_at = None
            if expires_days:
                expires_at = datetime.now() + timedelta(days=expires_days)
            
            campaign_id = await conn.fetchval(
                '''INSERT INTO campaigns (merchant_id, name, stamps_needed, description, expires_at, terms, locations)
                   VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id''',
                merchant_id, name, stamps_needed, description, expires_at, terms, locations or []
            )
            return campaign_id
    
    async def get_campaign(self, campaign_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM campaigns WHERE id = $1', campaign_id)
            return dict(row) if row else None
    
    async def get_merchant_campaigns(self, merchant_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM campaigns WHERE merchant_id = $1 AND active = TRUE ORDER BY created_at DESC',
                merchant_id
            )
            return [dict(row) for row in rows]
    
    async def add_reward_tier(self, campaign_id, stamps_required, reward_name, description=None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO rewards (campaign_id, stamps_required, reward_name, reward_description) VALUES ($1, $2, $3, $4)',
                campaign_id, stamps_required, reward_name, description
            )
    
    async def get_campaign_rewards(self, campaign_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM rewards WHERE campaign_id = $1 ORDER BY stamps_required',
                campaign_id
            )
            return [dict(row) for row in rows]
    
    # Customer operations
    async def create_customer(self, user_id, username, first_name, referred_by=None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO customers (id, username, first_name, referred_by) VALUES ($1, $2, $3, $4) ON CONFLICT (id) DO NOTHING',
                user_id, username, first_name, referred_by
            )
    
    async def enroll_customer(self, campaign_id, customer_id):
        async with self.pool.acquire() as conn:
            enrollment_id = await conn.fetchval(
                '''INSERT INTO enrollments (campaign_id, customer_id)
                   VALUES ($1, $2)
                   ON CONFLICT (campaign_id, customer_id) DO UPDATE SET joined_at = enrollments.joined_at
                   RETURNING id''',
                campaign_id, customer_id
            )
            return enrollment_id
    
    async def get_enrollment(self, campaign_id, customer_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM enrollments WHERE campaign_id = $1 AND customer_id = $2',
                campaign_id, customer_id
            )
            return dict(row) if row else None
    
    async def get_customer_enrollments(self, customer_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT e.*, c.name, c.stamps_needed, c.expires_at
                   FROM enrollments e
                   JOIN campaigns c ON e.campaign_id = c.id
                   WHERE e.customer_id = $1 AND c.active = TRUE
                   ORDER BY e.joined_at DESC''',
                customer_id
            )
            return [dict(row) for row in rows]
    
    async def get_campaign_customers(self, campaign_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                '''SELECT e.*, c.username, c.first_name
                   FROM enrollments e
                   JOIN customers c ON e.customer_id = c.id
                   WHERE e.campaign_id = $1
                   ORDER BY e.stamps DESC, e.joined_at''',
                campaign_id
            )
            return [dict(row) for row in rows]
    
    async def add_stamp(self, enrollment_id, merchant_id, location=None):
        async with self.pool.acquire() as conn:
            # Add transaction
            await conn.execute(
                'INSERT INTO transactions (enrollment_id, merchant_id, location) VALUES ($1, $2, $3)',
                enrollment_id, merchant_id, location
            )
            
            # Update enrollment
            await conn.execute(
                '''UPDATE enrollments 
                   SET stamps = stamps + 1, last_stamp_at = NOW()
                   WHERE id = $1''',
                enrollment_id
            )
            
            # Get updated stamps
            stamps = await conn.fetchval('SELECT stamps FROM enrollments WHERE id = $1', enrollment_id)
            return stamps
    
    async def mark_completed(self, enrollment_id):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE enrollments SET completed = TRUE WHERE id = $1', enrollment_id)
    
    # Referral operations
    async def create_referral(self, referrer_id, referred_id, campaign_id):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO referrals (referrer_id, referred_id, campaign_id) VALUES ($1, $2, $3)',
                referrer_id, referred_id, campaign_id
            )
    
    async def give_referral_bonus(self, referrer_id, campaign_id):
        async with self.pool.acquire() as conn:
            # Get enrollment
            enrollment = await conn.fetchrow(
                'SELECT id FROM enrollments WHERE customer_id = $1 AND campaign_id = $2',
                referrer_id, campaign_id
            )
            if enrollment:
                await conn.execute(
                    'UPDATE enrollments SET stamps = stamps + 1 WHERE id = $1',
                    enrollment['id']
                )
    
    # Analytics
    async def get_campaign_stats(self, campaign_id, days=30):
        async with self.pool.acquire() as conn:
            since = datetime.now() - timedelta(days=days)
            
            stats = await conn.fetchrow('''
                SELECT 
                    COUNT(DISTINCT e.customer_id) as total_customers,
                    COUNT(DISTINCT CASE WHEN e.completed THEN e.customer_id END) as completed_customers,
                    COALESCE(SUM(e.stamps), 0) as total_stamps,
                    COUNT(DISTINCT CASE WHEN t.created_at >= $2 THEN t.id END) as recent_stamps
                FROM enrollments e
                LEFT JOIN transactions t ON t.enrollment_id = e.id
                WHERE e.campaign_id = $1
            ''', campaign_id, since)
            
            return dict(stats) if stats else {}
