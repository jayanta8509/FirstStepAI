#!/usr/bin/env python3
"""
Redis Connection Test Script for FirstStepAI
Run this script to test your Redis connection and basic functionality
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_redis_connection():
    """Test Redis connection and basic operations"""
    print("🔄 Testing Redis Connection for FirstStepAI...")
    print("=" * 50)
    
    try:
        # Import Redis manager
        from firststep_redis import redis_manager, get_daily_token_usage, update_daily_token_usage, get_teaser_usage, update_teaser_usage
        
        # Test basic connection
        health = redis_manager.health_check()
        print(f"📊 Redis Health: {health}")
        
        if health["status"] != "healthy":
            print("❌ Redis connection failed!")
            return False
        
        print("✅ Redis connection successful!")
        print()
        
        # Test token functions
        test_user_id = f"test_user_{datetime.now().strftime('%H%M%S')}"
        print(f"🧪 Testing with user ID: {test_user_id}")
        
        # Test daily token tracking
        print("\n📈 Testing Daily Token Tracking:")
        initial_usage = get_daily_token_usage(test_user_id)
        print(f"   Initial usage: {initial_usage} tokens")
        
        # Add some tokens
        update_daily_token_usage(test_user_id, 100)
        updated_usage = get_daily_token_usage(test_user_id)
        print(f"   After adding 100 tokens: {updated_usage} tokens")
        
        # Test teaser mode
        print("\n🎯 Testing Teaser Mode:")
        initial_teaser = get_teaser_usage(test_user_id)
        print(f"   Initial teaser usage: {initial_teaser}")
        
        # Update teaser usage
        update_teaser_usage(test_user_id)
        updated_teaser = get_teaser_usage(test_user_id)
        print(f"   After teaser query: {updated_teaser}")
        
        # Test conversation storage
        print("\n💬 Testing Conversation Storage:")
        conversation_data = {
            "query": "Test query for Redis",
            "response": "Test response from FirstStepAI",
            "assistant_name": "Jarvis",
            "tokens_used": 50,
            "crisis_detected": False
        }
        
        stored = redis_manager.store_conversation(test_user_id, conversation_data)
        print(f"   Conversation stored: {stored}")
        
        if stored:
            history = redis_manager.get_conversation_history(test_user_id, 1)
            print(f"   Retrieved conversation: {len(history)} items")
            if history:
                print(f"   Last conversation: {history[0]['query'][:50]}...")
        
        # Test metrics
        print("\n📊 Testing Metrics:")
        metric_result = redis_manager.increment_metric("test_requests")
        print(f"   Metric incremented: {metric_result}")
        
        if metric_result:
            metric_value = redis_manager.get_metric("test_requests")
            print(f"   Current metric value: {metric_value}")
        
        # Test caching
        print("\n🗄️ Testing Cache:")
        cache_data = {"test": "data", "timestamp": datetime.now().isoformat()}
        cache_set = redis_manager.set_cache("test_cache", cache_data, 60)
        print(f"   Cache set: {cache_set}")
        
        if cache_set:
            cached_data = redis_manager.get_cache("test_cache")
            print(f"   Cache retrieved: {cached_data is not None}")
        
        print("\n✅ All Redis tests passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Make sure to install redis: pip install redis==5.2.1")
        return False
        
    except Exception as e:
        print(f"❌ Redis test failed: {e}")
        print("\n🔧 Troubleshooting:")
        print("1. Check your Redis connection details in .env file")
        print("2. Ensure Redis server is running and accessible")
        print("3. Verify your Redis password and host/port")
        return False

def check_environment():
    """Check if required environment variables are set"""
    print("🔍 Checking Environment Variables...")
    print("=" * 50)
    
    required_vars = [
        "REDIS_HOST",
        "REDIS_PORT", 
        "REDIS_USERNAME",
        "REDIS_PASSWORD"
    ]
    
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask password for security
            display_value = value if var != "REDIS_PASSWORD" else "*" * len(value)
            print(f"✅ {var}: {display_value}")
        else:
            print(f"❌ {var}: Not set")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  Missing environment variables: {', '.join(missing_vars)}")
        print("📝 Add these to your .env file (see environment_config.txt for reference)")
        return False
    
    print("✅ All required environment variables are set!")
    return True

def show_redis_info():
    """Show Redis connection information"""
    print("📋 Redis Configuration:")
    print("=" * 50)
    print(f"Host: {os.getenv('REDIS_HOST', 'Not set')}")
    print(f"Port: {os.getenv('REDIS_PORT', 'Not set')}")
    print(f"Username: {os.getenv('REDIS_USERNAME', 'Not set')}")
    print(f"Database: {os.getenv('REDIS_DB', '0')}")
    print(f"Password: {'Set' if os.getenv('REDIS_PASSWORD') else 'Not set'}")
    print()

if __name__ == "__main__":
    print("🚀 FirstStepAI Redis Test Suite")
    print("=" * 50)
    
    # Check environment variables
    env_ok = check_environment()
    if not env_ok:
        sys.exit(1)
    
    print()
    show_redis_info()
    
    # Test Redis connection and functionality
    success = test_redis_connection()
    
    if success:
        print("\n🎉 Redis setup is working correctly!")
        print("🔗 Your FirstStepAI app is ready to use Redis for:")
        print("   • Token usage tracking")
        print("   • User session management") 
        print("   • Conversation history")
        print("   • Crisis mode tracking")
        print("   • Analytics and metrics")
        print("   • Caching")
    else:
        print("\n🚨 Redis setup needs attention!")
        print("📚 Check the redis_integration_example.py for integration guidance")
        sys.exit(1) 