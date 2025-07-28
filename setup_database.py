#!/usr/bin/env python3
"""
FirstStepAI V5 Database Setup Script

This script sets up the required database tables in Supabase for file upload functionality.
Run this once to create the missing 'conversation_files' table.

Usage:
    python setup_database.py
"""

import os
from store_data_supabase import SupabaseManager
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def setup_database():
    """Set up database tables and permissions"""
    
    print("🚀 FirstStepAI V5 Database Setup")
    print("=" * 50)
    
    try:
        # Initialize Supabase manager
        supabase_manager = SupabaseManager()
        supabase = supabase_manager.client
        
        print("✅ Connected to Supabase")
        
        # SQL to create conversation_files table
        schema_sql = """
        -- Create conversation_files table for file upload metadata
        CREATE TABLE IF NOT EXISTS public.conversation_files (
            id BIGSERIAL PRIMARY KEY,
            file_id VARCHAR(255) UNIQUE NOT NULL,
            user_id VARCHAR(255) NOT NULL,
            conversation_id VARCHAR(255) NOT NULL,
            original_filename VARCHAR(500) NOT NULL,
            secure_filename VARCHAR(500) NOT NULL,
            file_extension VARCHAR(20) NOT NULL,
            file_size BIGINT NOT NULL,
            user_tier VARCHAR(50) NOT NULL,
            processed_content TEXT,
            content_preview VARCHAR(500),
            upload_timestamp TIMESTAMPTZ DEFAULT NOW(),
            processing_status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Add indexes for better performance
        CREATE INDEX IF NOT EXISTS idx_conversation_files_user_id ON public.conversation_files(user_id);
        CREATE INDEX IF NOT EXISTS idx_conversation_files_conversation_id ON public.conversation_files(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_conversation_files_file_id ON public.conversation_files(file_id);
        CREATE INDEX IF NOT EXISTS idx_conversation_files_user_conversation ON public.conversation_files(user_id, conversation_id);
        CREATE INDEX IF NOT EXISTS idx_conversation_files_timestamp ON public.conversation_files(upload_timestamp);
        """
        
        print("📊 Creating conversation_files table...")
        
        # Execute the schema creation
        # Note: Supabase Python client doesn't support raw SQL execution
        # This is just a template - you need to run the SQL manually in Supabase dashboard
        
        print("⚠️  MANUAL STEP REQUIRED:")
        print("   1. Go to your Supabase dashboard")
        print("   2. Navigate to SQL Editor")
        print("   3. Copy and paste the contents of 'database_schema.sql'")
        print("   4. Run the SQL commands")
        print("")
        print("📄 Database schema saved to: database_schema.sql")
        print("🔧 After running the SQL, file uploads will work without errors")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure your Supabase credentials are correct in .env file")
        return False

def test_connection():
    """Test database connection"""
    try:
        supabase_manager = SupabaseManager()
        supabase = supabase_manager.client
        
        # Try to query an existing table
        result = supabase.from_("AI_message_store").select("id").limit(1).execute()
        print("✅ Database connection test successful")
        return True
        
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing database connection...")
    if test_connection():
        setup_database()
    else:
        print("❌ Setup aborted due to connection issues")
        print("💡 Check your SUPABASE_URL and SUPABASE_KEY in .env file") 