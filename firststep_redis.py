import redis
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dotenv import load_dotenv

load_dotenv()

class RedisManager:
    def __init__(self):
        """Initialize Redis connection for FirstStepAI token management"""
        self.redis_host = os.getenv('REDIS_HOST', 'redis-10936.c91.us-east-1-3.ec2.redns.redis-cloud.com')
        self.redis_port = int(os.getenv('REDIS_PORT', 10936))
        self.redis_username = os.getenv('REDIS_USERNAME', 'default')
        self.redis_password = os.getenv('REDIS_PASSWORD', '')
        self.redis_db = int(os.getenv('REDIS_DB', 0))
        
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                username=self.redis_username,
                password=self.redis_password,
                db=self.redis_db,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            self.redis_client.ping()
            print("✅ Redis connection established successfully")
        except redis.ConnectionError as e:
            print(f"❌ Redis connection failed: {e}")
            self.redis_client = None
        except Exception as e:
            print(f"❌ Redis initialization error: {e}")
            self.redis_client = None

    def is_connected(self) -> bool:
        """Check if Redis is connected and available"""
        if not self.redis_client:
            return False
        try:
            self.redis_client.ping()
            return True
        except:
            return False

    # Token Usage Management
    def get_daily_token_usage(self, user_id: str) -> int:
        """Get user's daily token usage"""
        if not self.is_connected():
            return 0
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        key = f"firststep:tokens:daily:{user_id}:{current_date}"
        
        try:
            usage = self.redis_client.get(key)
            return int(usage) if usage else 0
        except Exception as e:
            print(f"Error getting daily token usage: {e}")
            return 0

    def update_daily_token_usage(self, user_id: str, tokens_used: int) -> bool:
        """Update user's daily token usage"""
        if not self.is_connected():
            return False
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        key = f"firststep:tokens:daily:{user_id}:{current_date}"
        
        try:
            # Increment token usage
            self.redis_client.incrby(key, tokens_used)
            # Set expiry for next day midnight
            tomorrow = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            self.redis_client.expireat(key, int(tomorrow.timestamp()))
            return True
        except Exception as e:
            print(f"Error updating daily token usage: {e}")
            return False

    def reset_daily_tokens(self, user_id: str) -> bool:
        """Reset user's daily token usage"""
        if not self.is_connected():
            return False
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        key = f"firststep:tokens:daily:{user_id}:{current_date}"
        
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Error resetting daily tokens: {e}")
            return False

    # Teaser Mode Management
    def get_teaser_usage(self, user_id: str) -> Dict[str, Any]:
        """Get user's teaser mode usage"""
        if not self.is_connected():
            return {"queries_used": 0, "date": datetime.now().strftime("%Y-%m-%d")}
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        key = f"firststep:teaser:{user_id}"
        
        try:
            data = self.redis_client.get(key)
            if data:
                teaser_data = json.loads(data)
                # Reset if different date
                if teaser_data.get("date") != current_date:
                    return {"queries_used": 0, "date": current_date}
                return teaser_data
            else:
                return {"queries_used": 0, "date": current_date}
        except Exception as e:
            print(f"Error getting teaser usage: {e}")
            return {"queries_used": 0, "date": current_date}

    def update_teaser_usage(self, user_id: str) -> bool:
        """Increment user's teaser mode usage"""
        if not self.is_connected():
            return False
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        key = f"firststep:teaser:{user_id}"
        
        try:
            teaser_data = self.get_teaser_usage(user_id)
            teaser_data["queries_used"] += 1
            teaser_data["date"] = current_date
            
            self.redis_client.set(key, json.dumps(teaser_data))
            # Set expiry for next day midnight
            tomorrow = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            self.redis_client.expireat(key, int(tomorrow.timestamp()))
            return True
        except Exception as e:
            print(f"Error updating teaser usage: {e}")
            return False

    # User Session Management
    def get_user_session(self, user_id: str) -> Dict[str, Any]:
        """Get user session data"""
        if not self.is_connected():
            return {}
        
        key = f"firststep:session:{user_id}"
        
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else {}
        except Exception as e:
            print(f"Error getting user session: {e}")
            return {}

    def update_user_session(self, user_id: str, session_data: Dict[str, Any], ttl: int = 3600) -> bool:
        """Update user session data with TTL"""
        if not self.is_connected():
            return False
        
        key = f"firststep:session:{user_id}"
        
        try:
            self.redis_client.setex(key, ttl, json.dumps(session_data))
            return True
        except Exception as e:
            print(f"Error updating user session: {e}")
            return False

    # Conversation History Management
    def store_conversation(self, user_id: str, conversation_data: Dict[str, Any]) -> bool:
        """Store conversation history"""
        if not self.is_connected():
            return False
        
        timestamp = datetime.now().isoformat()
        key = f"firststep:conversations:{user_id}"
        
        try:
            # Add timestamp to conversation data
            conversation_data["timestamp"] = timestamp
            
            # Store as list with recent conversations first
            self.redis_client.lpush(key, json.dumps(conversation_data))
            
            # Keep only last 50 conversations
            self.redis_client.ltrim(key, 0, 49)
            
            # Set expiry for 30 days
            self.redis_client.expire(key, 30 * 24 * 3600)
            return True
        except Exception as e:
            print(f"Error storing conversation: {e}")
            return False

    def get_conversation_history(self, user_id: str, limit: int = 10) -> list:
        """Get user's conversation history"""
        if not self.is_connected():
            return []
        
        key = f"firststep:conversations:{user_id}"
        
        try:
            conversations = self.redis_client.lrange(key, 0, limit - 1)
            return [json.loads(conv) for conv in conversations]
        except Exception as e:
            print(f"Error getting conversation history: {e}")
            return []

    # Crisis Mode Tracking
    def set_crisis_mode(self, user_id: str, crisis_data: Dict[str, Any], ttl: int = 86400) -> bool:
        """Set crisis mode for user with tracking data"""
        if not self.is_connected():
            return False
        
        key = f"firststep:crisis:{user_id}"
        
        try:
            crisis_data["timestamp"] = datetime.now().isoformat()
            self.redis_client.setex(key, ttl, json.dumps(crisis_data))
            return True
        except Exception as e:
            print(f"Error setting crisis mode: {e}")
            return False

    def get_crisis_mode(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get crisis mode data for user"""
        if not self.is_connected():
            return None
        
        key = f"firststep:crisis:{user_id}"
        
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"Error getting crisis mode: {e}")
            return None

    def clear_crisis_mode(self, user_id: str) -> bool:
        """Clear crisis mode for user"""
        if not self.is_connected():
            return False
        
        key = f"firststep:crisis:{user_id}"
        
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Error clearing crisis mode: {e}")
            return False

    # Analytics and Metrics
    def increment_metric(self, metric_name: str, value: int = 1) -> bool:
        """Increment a metric counter"""
        if not self.is_connected():
            return False
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        key = f"firststep:metrics:{metric_name}:{current_date}"
        
        try:
            self.redis_client.incrby(key, value)
            # Set expiry for 90 days
            self.redis_client.expire(key, 90 * 24 * 3600)
            return True
        except Exception as e:
            print(f"Error incrementing metric: {e}")
            return False

    def get_metric(self, metric_name: str, date: str = None) -> int:
        """Get metric value for a specific date"""
        if not self.is_connected():
            return 0
        
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        key = f"firststep:metrics:{metric_name}:{date}"
        
        try:
            value = self.redis_client.get(key)
            return int(value) if value else 0
        except Exception as e:
            print(f"Error getting metric: {e}")
            return 0

    # Cache Management
    def set_cache(self, cache_key: str, data: Any, ttl: int = 3600) -> bool:
        """Set cache data with TTL"""
        if not self.is_connected():
            return False
        
        key = f"firststep:cache:{cache_key}"
        
        try:
            self.redis_client.setex(key, ttl, json.dumps(data))
            return True
        except Exception as e:
            print(f"Error setting cache: {e}")
            return False

    def get_cache(self, cache_key: str) -> Any:
        """Get cache data"""
        if not self.is_connected():
            return None
        
        key = f"firststep:cache:{cache_key}"
        
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"Error getting cache: {e}")
            return None

    def clear_cache(self, cache_key: str) -> bool:
        """Clear specific cache"""
        if not self.is_connected():
            return False
        
        key = f"firststep:cache:{cache_key}"
        
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            print(f"Error clearing cache: {e}")
            return False

    # Utility Functions
    def health_check(self) -> Dict[str, Any]:
        """Perform Redis health check"""
        try:
            if not self.redis_client:
                return {"status": "disconnected", "error": "No Redis connection"}
            
            info = self.redis_client.info()
            ping_response = self.redis_client.ping()
            
            return {
                "status": "healthy" if ping_response else "unhealthy",
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "redis_version": info.get("redis_version", "unknown"),
                "ping": ping_response
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_all_user_keys(self, pattern: str = "firststep:*") -> list:
        """Get all keys matching pattern (use carefully in production)"""
        if not self.is_connected():
            return []
        
        try:
            return self.redis_client.keys(pattern)
        except Exception as e:
            print(f"Error getting keys: {e}")
            return []

    def cleanup_expired_data(self) -> bool:
        """Cleanup expired data (run periodically)"""
        if not self.is_connected():
            return False
        
        try:
            # This is handled automatically by Redis TTL, but we can add custom logic here
            # For now, just return True as Redis handles expiration automatically
            return True
        except Exception as e:
            print(f"Error during cleanup: {e}")
            return False

# Global Redis manager instance
redis_manager = RedisManager()

# Convenience functions for easy import
def get_daily_token_usage(user_id: str) -> int:
    """Get user's daily token usage"""
    return redis_manager.get_daily_token_usage(user_id)

def update_daily_token_usage(user_id: str, tokens_used: int) -> bool:
    """Update user's daily token usage"""
    return redis_manager.update_daily_token_usage(user_id, tokens_used)

def get_teaser_usage(user_id: str) -> Dict[str, Any]:
    """Get user's teaser mode usage"""
    return redis_manager.get_teaser_usage(user_id)

def update_teaser_usage(user_id: str) -> bool:
    """Update user's teaser mode usage"""
    return redis_manager.update_teaser_usage(user_id)

def store_conversation(user_id: str, conversation_data: Dict[str, Any]) -> bool:
    """Store conversation history"""
    return redis_manager.store_conversation(user_id, conversation_data)

def get_conversation_history(user_id: str, limit: int = 10) -> list:
    """Get conversation history"""
    return redis_manager.get_conversation_history(user_id, limit)

def set_crisis_mode(user_id: str, crisis_data: Dict[str, Any]) -> bool:
    """Set crisis mode for user"""
    return redis_manager.set_crisis_mode(user_id, crisis_data)

def get_crisis_mode(user_id: str) -> Optional[Dict[str, Any]]:
    """Get crisis mode data"""
    return redis_manager.get_crisis_mode(user_id)

def increment_metric(metric_name: str, value: int = 1) -> bool:
    """Increment a metric"""
    return redis_manager.increment_metric(metric_name, value)

def redis_health_check() -> Dict[str, Any]:
    """Redis health check"""
    return redis_manager.health_check() 