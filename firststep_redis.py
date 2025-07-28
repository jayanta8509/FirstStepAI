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
            # print("✅ Redis connection established successfully")
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
    def store_conversation(self, user_id: str, conversation_data: Dict[str, Any], user_tier: str = "wanderer") -> bool:
        """Store conversation history with tier-based limits"""
        if not self.is_connected():
            return False
        
        timestamp = datetime.now().isoformat()
        key = f"firststep:conversations:{user_id}"
        
        try:
            # Add timestamp and thread_id to conversation data
            conversation_data["timestamp"] = timestamp
            conversation_data["thread_id"] = f"{user_id}_jarvis_convo"
            
            # Store as list with recent conversations first
            self.redis_client.lpush(key, json.dumps(conversation_data))
            
            # Tier-based memory limits
            tier_limits = {
                "wanderer": 5,    # Free tier gets basic memory
                "builder": 5,     # Last 5 chats
                "architect": 25,  # Last 25 chats  
                "awakener": -1    # Unlimited
            }
            
            limit = tier_limits.get(user_tier, 5)
            
            if limit > 0:
                # Keep only the specified number of conversations
                self.redis_client.ltrim(key, 0, limit - 1)
            # If limit is -1 (unlimited), don't trim
            
            # Set expiry based on tier
            expiry_days = 90 if user_tier == "awakener" else 30
            self.redis_client.expire(key, expiry_days * 24 * 3600)
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

    # Conversation Organization Features
    def name_conversation(self, user_id: str, conversation_id: str, name: str) -> bool:
        """Name a conversation for better organization"""
        if not self.is_connected():
            return False
        
        key = f"firststep:conversation:name:{user_id}:{conversation_id}"
        
        try:
            self.redis_client.setex(key, 90 * 24 * 3600, name)  # 90 days expiry
            return True
        except Exception as e:
            print(f"Error naming conversation: {e}")
            return False

    def create_conversation_folder(self, user_id: str, folder_name: str, user_tier: str) -> bool:
        """Create conversation folder (Architect/Awakener only)"""
        if not self.is_connected():
            return False
        
        # Check if user has folder access
        if user_tier not in ["architect", "awakener"]:
            return False
        
        key = f"firststep:folders:{user_id}"
        
        try:
            folder_data = {
                "name": folder_name,
                "created_at": datetime.now().isoformat(),
                "conversation_ids": []
            }
            
            # Get existing folders
            folders = self.redis_client.get(key)
            if folders:
                folders_list = json.loads(folders)
            else:
                folders_list = []
            
            # Add new folder
            folders_list.append(folder_data)
            
            self.redis_client.setex(key, 90 * 24 * 3600, json.dumps(folders_list))
            return True
        except Exception as e:
            print(f"Error creating folder: {e}")
            return False

    def organize_conversation_to_folder(self, user_id: str, conversation_id: str, folder_name: str) -> bool:
        """Add conversation to a folder"""
        if not self.is_connected():
            return False
        
        key = f"firststep:folders:{user_id}"
        
        try:
            folders = self.redis_client.get(key)
            if not folders:
                return False
            
            folders_list = json.loads(folders)
            
            # Find the folder and add conversation
            for folder in folders_list:
                if folder["name"] == folder_name:
                    if conversation_id not in folder["conversation_ids"]:
                        folder["conversation_ids"].append(conversation_id)
                    break
            
            self.redis_client.setex(key, 90 * 24 * 3600, json.dumps(folders_list))
            return True
        except Exception as e:
            print(f"Error organizing conversation: {e}")
            return False

    def get_user_folders(self, user_id: str) -> list:
        """Get user's conversation folders"""
        if not self.is_connected():
            return []
        
        key = f"firststep:folders:{user_id}"
        
        try:
            folders = self.redis_client.get(key)
            return json.loads(folders) if folders else []
        except Exception as e:
            print(f"Error getting folders: {e}")
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

    # User Profile Management Functions
    def store_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> bool:
        """Store or update user profile information
        
        Args:
            user_id: Unique user identifier
            profile_data: Dictionary containing profile fields (nickname, life_goal, etc.)
            
        Returns:
            bool: Success status
        """
        if not self.is_connected():
            return False
            
        try:
            profile_key = f"firststep:profile:{user_id}"
            
            # Get existing profile if any
            existing_profile = self.get_user_profile(user_id)
            
            # Merge with new data (new data takes precedence)
            if existing_profile:
                existing_profile.update(profile_data)
                merged_profile = existing_profile
            else:
                merged_profile = profile_data.copy()
            
            # Add metadata
            merged_profile["last_updated"] = datetime.utcnow().isoformat()
            merged_profile["user_id"] = user_id
            
            # Store with 30-day expiration
            self.redis_client.setex(
                profile_key, 
                timedelta(days=30), 
                json.dumps(merged_profile)
            )
            
            return True
            
        except Exception as e:
            print(f"❌ Error storing user profile: {e}")
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve user profile information
        
        Args:
            user_id: Unique user identifier
            
        Returns:
            Dict containing profile data or None if not found
        """
        if not self.is_connected():
            return None
            
        try:
            profile_key = f"firststep:profile:{user_id}"
            profile_data = self.redis_client.get(profile_key)
            
            if profile_data:
                return json.loads(profile_data)
            return None
            
        except Exception as e:
            print(f"❌ Error retrieving user profile: {e}")
            return None
    
    def update_user_profile_field(self, user_id: str, field: str, value: Any) -> bool:
        """Update a specific field in user profile
        
        Args:
            user_id: Unique user identifier
            field: Profile field to update
            value: New value for the field
            
        Returns:
            bool: Success status
        """
        if not self.is_connected():
            return False
            
        try:
            # Get existing profile
            profile = self.get_user_profile(user_id)
            if not profile:
                profile = {}
            
            # Update specific field
            profile[field] = value
            
            # Store updated profile
            return self.store_user_profile(user_id, profile)
            
        except Exception as e:
            print(f"❌ Error updating user profile field: {e}")
            return False
    
    def delete_user_profile(self, user_id: str) -> bool:
        """Delete user profile
        
        Args:
            user_id: Unique user identifier
            
        Returns:
            bool: Success status
        """
        if not self.is_connected():
            return False
            
        try:
            profile_key = f"firststep:profile:{user_id}"
            self.redis_client.delete(profile_key)
            return True
            
        except Exception as e:
            print(f"❌ Error deleting user profile: {e}")
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

def store_conversation(user_id: str, conversation_data: Dict[str, Any], user_tier: str = "wanderer") -> bool:
    """Store conversation history with tier-based limits"""
    return redis_manager.store_conversation(user_id, conversation_data, user_tier)

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

# User Profile Management Functions
def store_user_profile(user_id: str, profile_data: Dict[str, Any]) -> bool:
    """Store or update user profile information"""
    return redis_manager.store_user_profile(user_id, profile_data)

def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve user profile information"""
    return redis_manager.get_user_profile(user_id)

def update_user_profile_field(user_id: str, field: str, value: Any) -> bool:
    """Update a specific field in user profile"""
    return redis_manager.update_user_profile_field(user_id, field, value)

def delete_user_profile(user_id: str) -> bool:
    """Delete user profile"""
    return redis_manager.delete_user_profile(user_id) 