import asyncpg
from datetime import datetime, timedelta

class StampMeDatabase:
    def __init__(self, database_url: str):
        self.pool = None
        self.db_url = database_url
    
    async def connect(self):
        self.pool = await asyncpg.create_pool(
            self.db_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        await self.create_all_tables()
        print("✅ Database connected and tables created")
    
    async def create_all_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
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
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS campaigns (
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
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS reward_tiers (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
                    stamps_required INTEGER NOT NULL,
                    reward_name TEXT NOT NULL,
                    reward_description TEXT
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS enrollments (
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
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS stamp_requests (
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
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    enrollment_id INTEGER REFERENCES enrollments(id),
                    merchant_id BIGINT,
                    action_type TEXT,
                    stamps_change INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id BIGINT REFERENCES users(id),
                    referred_id BIGINT REFERENCES users(id),
                    campaign_id INTEGER REFERENCES campaigns(id),
                    bonus_given BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS merchant_settings (
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
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    message TEXT,
                    sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS daily_stats (
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
    
    async def close(self):
        if self.pool:
            await self.pool.close()
    
    async def create_or_update_user(self, user_id: int, username: str, first_name: str, user_type: str = 'customer'):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO users (id, username, first_name, user_type, last_active)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_active = NOW()
            ''', user_id, username, first_name, user_type)
    
    async def get_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM users WHERE id = $1', user_id)
            return dict(row) if row else None
    
    async def request_merchant_access(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET user_type = 'merchant' WHERE id = $1", user_id)
    
    async def approve_merchant(self, user_id: int, admin_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE users SET 
                    merchant_approved = TRUE,
                    merchant_approved_at = NOW(),
                    merchant_approved_by = $2
                WHERE id = $1
            ''', user_id, admin_id)
            
            await conn.execute('''
                INSERT INTO merchant_settings (merchant_id)
                VALUES ($1)
                ON CONFLICT (merchant_id) DO NOTHING
            ''', user_id)
    
    async def get_pending_merchants(self):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM users 
                WHERE user_type = 'merchant' AND merchant_approved = FALSE
                ORDER BY created_at
            ''')
            return [dict(row) for row in rows]
    
    async def is_merchant_approved(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.fetchval('''
                SELECT merchant_approved FROM users 
                WHERE id = $1 AND user_type = 'merchant'
            ''', user_id)
            return result or False
    
    async def create_campaign(self, merchant_id: int, name: str, stamps_needed: int, 
                            description: str = None, reward_description: str = None,
                            expires_days: int = None):
        async with self.pool.acquire() as conn:
            expires_at = None
            if expires_days:
                expires_at = datetime.now() + timedelta(days=expires_days)
            
            campaign_id = await conn.fetchval('''
                INSERT INTO campaigns (merchant_id, name, description, stamps_needed, reward_description, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            ''', merchant_id, name, description, stamps_needed, reward_description, expires_at)
            
            return campaign_id
    
    async def get_campaign(self, campaign_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM campaigns WHERE id = $1', campaign_id)
            return dict(row) if row else None
    
    async def get_merchant_campaigns(self, merchant_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM campaigns 
                WHERE merchant_id = $1 AND active = TRUE 
                ORDER BY created_at DESC
            ''', merchant_id)
            return [dict(row) for row in rows]
    
    async def add_reward_tier(self, campaign_id: int, stamps_required: int, reward_name: str, description: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO reward_tiers (campaign_id, stamps_required, reward_name, reward_description)
                VALUES ($1, $2, $3, $4)
            ''', campaign_id, stamps_required, reward_name, description)
    
    async def get_campaign_rewards(self, campaign_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM reward_tiers 
                WHERE campaign_id = $1 
                ORDER BY stamps_required
            ''', campaign_id)
            return [dict(row) for row in rows]
    
    async def enroll_customer(self, campaign_id: int, customer_id: int):
        async with self.pool.acquire() as conn:
            enrollment_id = await conn.fetchval('''
                INSERT INTO enrollments (campaign_id, customer_id)
                VALUES ($1, $2)
                ON CONFLICT (campaign_id, customer_id) 
                DO UPDATE SET joined_at = enrollments.joined_at
                RETURNING id
            ''', campaign_id, customer_id)
            
            await conn.execute('UPDATE campaigns SET total_joins = total_joins + 1 WHERE id = $1', campaign_id)
            
            return enrollment_id
    
    async def get_enrollment(self, campaign_id: int, customer_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM enrollments 
                WHERE campaign_id = $1 AND customer_id = $2
            ''', campaign_id, customer_id)
            return dict(row) if row else None
    
    async def get_customer_enrollments(self, customer_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT e.id, e.campaign_id, e.customer_id, e.stamps, e.joined_at, 
                       e.last_stamp_at, e.completed, e.completed_at, e.rating, e.feedback,
                       ca.name, ca.stamps_needed, ca.expires_at,
                       u.first_name as merchant_name
                FROM enrollments e
                JOIN campaigns ca ON e.campaign_id = ca.id
                JOIN users u ON ca.merchant_id = u.id
                WHERE e.customer_id = $1 AND ca.active = TRUE
                ORDER BY e.last_stamp_at DESC NULLS LAST, e.joined_at DESC
            ''', customer_id)
            return [dict(row) for row in rows]
    
    async def get_campaign_customers(self, campaign_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT e.*, u.username, u.first_name
                FROM enrollments e
                JOIN users u ON e.customer_id = u.id
                WHERE e.campaign_id = $1
                ORDER BY e.stamps DESC, e.joined_at
            ''', campaign_id)
            return [dict(row) for row in rows]
    
    async def create_stamp_request(self, campaign_id: int, customer_id: int, 
                                  merchant_id: int, enrollment_id: int, message: str = None):
        async with self.pool.acquire() as conn:
            request_id = await conn.fetchval('''
                INSERT INTO stamp_requests 
                (campaign_id, customer_id, merchant_id, enrollment_id, customer_message)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            ''', campaign_id, customer_id, merchant_id, enrollment_id, message)
            
            return request_id
    
    async def get_pending_requests(self, merchant_id: int):
        """FIXED: Proper table aliases"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT sr.id, sr.campaign_id, sr.customer_id, sr.merchant_id, 
                       sr.enrollment_id, sr.status, sr.customer_message, sr.created_at,
                       ca.name as campaign_name, ca.stamps_needed,
                       u.username, u.first_name,
                       e.stamps as current_stamps
                FROM stamp_requests sr
                JOIN campaigns ca ON sr.campaign_id = ca.id
                JOIN users u ON sr.customer_id = u.id
                JOIN enrollments e ON sr.enrollment_id = e.id
                WHERE sr.merchant_id = $1 AND sr.status = 'pending'
                ORDER BY sr.created_at ASC
            ''', merchant_id)
            return [dict(row) for row in rows]
    
    async def approve_stamp_request(self, request_id: int):
        async with self.pool.acquire() as conn:
            request = await conn.fetchrow(
                'SELECT * FROM stamp_requests WHERE id = $1 AND status = $2',
                request_id, 'pending'
            )
            
            if not request:
                return None
            
            new_stamps = await conn.fetchval('''
                UPDATE enrollments 
                SET stamps = stamps + 1, last_stamp_at = NOW()
                WHERE id = $1
                RETURNING stamps
            ''', request['enrollment_id'])
            
            campaign = await conn.fetchrow('SELECT * FROM campaigns WHERE id = $1', request['campaign_id'])
            
            completed = new_stamps >= campaign['stamps_needed']
            
            if completed:
                await conn.execute('''
                    UPDATE enrollments 
                    SET completed = TRUE, completed_at = NOW()
                    WHERE id = $1
                ''', request['enrollment_id'])
                
                await conn.execute('UPDATE campaigns SET total_completions = total_completions + 1 WHERE id = $1', request['campaign_id'])
                await conn.execute('UPDATE users SET total_rewards_claimed = total_rewards_claimed + 1 WHERE id = $1', request['customer_id'])
            
            await conn.execute('''
                UPDATE stamp_requests 
                SET status = 'approved', processed_at = NOW()
                WHERE id = $1
            ''', request_id)
            
            await conn.execute('''
                INSERT INTO transactions (enrollment_id, merchant_id, action_type, stamps_change)
                VALUES ($1, $2, 'stamp_added', 1)
            ''', request['enrollment_id'], request['merchant_id'])
            
            await conn.execute('UPDATE users SET total_stamps_earned = total_stamps_earned + 1 WHERE id = $1', request['customer_id'])
            
            await conn.execute('''
                INSERT INTO daily_stats (merchant_id, date, visits, stamps_given)
                VALUES ($1, CURRENT_DATE, 1, 1)
                ON CONFLICT (merchant_id, date)
                DO UPDATE SET visits = daily_stats.visits + 1, 
                            stamps_given = daily_stats.stamps_given + 1
            ''', request['merchant_id'])
            
            return {
                'new_stamps': new_stamps,
                'completed': completed,
                'campaign': dict(campaign),
                'customer_id': request['customer_id']
            }
    
    async def reject_stamp_request(self, request_id: int, reason: str = None):
        async with self.pool.acquire() as conn:
            request = await conn.fetchrow(
                'SELECT * FROM stamp_requests WHERE id = $1 AND status = $2',
                request_id, 'pending'
            )
            
            if not request:
                return None
            
            await conn.execute('''
                UPDATE stamp_requests 
                SET status = 'rejected', rejection_reason = $2, processed_at = NOW()
                WHERE id = $1
            ''', request_id, reason)
            
            return dict(request)
    
    async def get_pending_count(self, merchant_id: int) -> int:
        async with self.pool.acquire() as conn:
            count = await conn.fetchval('''
                SELECT COUNT(*) FROM stamp_requests 
                WHERE merchant_id = $1 AND status = 'pending'
            ''', merchant_id)
            return count or 0
    
    async def queue_notification(self, user_id: int, message: str):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO notifications (user_id, message)
                VALUES ($1, $2)
            ''', user_id, message)
    
    async def get_pending_notifications(self, limit: int = 50):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM notifications 
                WHERE sent = FALSE 
                ORDER BY created_at
                LIMIT $1
            ''', limit)
            return [dict(row) for row in rows]
    
    async def mark_notification_sent(self, notification_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE notifications SET sent = TRUE WHERE id = $1', notification_id)
    
    async def get_daily_stats(self, merchant_id: int, date = None):
        async with self.pool.acquire() as conn:
            if not date:
                date = datetime.now().date()
            
            row = await conn.fetchrow('''
                SELECT * FROM daily_stats 
                WHERE merchant_id = $1 AND date = $2
            ''', merchant_id, date)
            
            return dict(row) if row else {
                'visits': 0, 'new_customers': 0, 
                'stamps_given': 0, 'rewards_claimed': 0
            }
    
    async def get_merchant_settings(self, merchant_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM merchant_settings WHERE merchant_id = $1
            ''', merchant_id)
            
            if not row:
                await conn.execute('''
                    INSERT INTO merchant_settings (merchant_id) VALUES ($1)
                ''', merchant_id)
                row = await conn.fetchrow('''
                    SELECT * FROM merchant_settings WHERE merchant_id = $1
                ''', merchant_id)
            
            return dict(row)
    
    async def update_merchant_settings(self, merchant_id: int, **kwargs):
        async with self.pool.acquire() as conn:
            set_clauses = []
            values = []
            idx = 2
            
            for key, value in kwargs.items():
                set_clauses.append(f"{key} = ${idx}")
                values.append(value)
                idx += 1
            
            if set_clauses:
                query = f"UPDATE merchant_settings SET {', '.join(set_clauses)} WHERE merchant_id = $1"
                await conn.execute(query, merchant_id, *values)
