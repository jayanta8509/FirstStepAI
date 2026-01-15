import os
import uuid
import logging
import warnings
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Suppress Supabase deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="supabase")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class DatabaseResponse:
    """Structured response for database operations"""
    success: bool
    response_id: Optional[str] = None
    error: Optional[str] = None
    retry_after: Optional[int] = None
    timestamp: Optional[datetime] = None

class SupabaseManager:
    """Singleton Supabase client manager"""
    _instance = None
    _client = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_client()
        return cls._instance
    
    def _initialize_client(self):
        """Initialize Supabase client with error handling"""
        try:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            
            if not url or not key:
                raise ValueError("Missing Supabase credentials in environment variables")
            
            self._client = create_client(url, key)
            logger.info("Supabase client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise
    
    @property
    def client(self) -> Client:
        """Get Supabase client instance"""
        if self._client is None:
            self._initialize_client()
        return self._client



async def store_data_supabase_v2(
    assistant_name: str,
    model_used: str,
    ai_response: str,
    user_query: str,
    user_id: str,
    task_category: str,
    chat_session_id: str,
    client_id: str
) -> DatabaseResponse:
    """
    Store AI interaction data in Supabase with comprehensive error handling
    
    Args:
        assistant_name: Name of the AI assistant (jarvis, elonix, optimus, celine)
        model_used: AI model used for the response
        ai_response: The AI's response text
        user_query: The user's original query
        user_id: Unique identifier for the user
        task_category: Category of the task/query
        conversation_id: Optional conversation identifier
        metadata: Optional additional metadata
    
    Returns:
        DatabaseResponse: Structured response with success status and details
    """
    start_time = datetime.now(timezone.utc)
    response_id = f"response_{uuid.uuid4()}"
    
    try:
        # Get Supabase client
        supabase_manager = SupabaseManager()
        supabase = supabase_manager.client
        
        # Prepare data for insertion
        insert_data = {
            "assistant_name": assistant_name, 
            "model_used": model_used, 
            "AI_response": ai_response, 
            "user_message": user_query, 
            "user_id": user_id, 
            "task_category": task_category,
            "responce_id": response_id,
            "ai_response_length": len(ai_response),
            "user_query_length": len(user_query),
            "chat_session_id" : chat_session_id,
            "client_id":client_id
        }
        
        # Perform database insertion
        result = (
            supabase
            .from_("AI_message_store")
            .insert(insert_data)
            .execute()
        )
        
        # Log successful insertion
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"Successfully stored data for user {user_id}", extra={
            'response_id': response_id,
            'assistant_name': assistant_name,
            'processing_time_ms': processing_time * 1000,
            'response_length': len(ai_response)
        })
        
        return DatabaseResponse(
            success=True,
            response_id=response_id,
            timestamp=start_time
        )
        
    except Exception as e:
        # Database or other errors
        error_type = type(e).__name__
        logger.error(f"Database insertion failed for user {user_id}: {e}", extra={
            'error_type': error_type,
            'assistant_name': assistant_name,
            'task_category': task_category
        })
        
        # Determine retry strategy based on error type
        retry_after = 30 if "rate" in str(e).lower() else None
        
        return DatabaseResponse(
            success=False,
            error=f"{error_type}: {str(e)}",
            retry_after=retry_after,
            timestamp=start_time
        )

# Backward compatible wrapper for existing code
async def store_data_supabase(
    assistant_name: str,
    model_used: str,
    AI_response: str,
    user_query: str,
    user_id: str,
    task_category: str,
    chat_session_id: str,
    client_id: str
) -> Optional[str]:
    """
    Backward compatible wrapper for the original function
    Returns response_id on success, None on failure
    """
    result = await store_data_supabase_v2(
        assistant_name, model_used, AI_response, 
        user_query, user_id, task_category, chat_session_id, client_id
    )
    
    return result.response_id if result.success else None