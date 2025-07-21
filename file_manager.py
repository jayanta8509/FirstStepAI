import os
import uuid
import tempfile
import shutil
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from werkzeug.utils import secure_filename
from markitdwon import process_any_input
from store_data_supabase import SupabaseManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tier-based file upload configuration
TIER_CONFIG = {
    "builder": {
        "max_file_size": 5 * 1024 * 1024,  # 5MB
        "allowed_extensions": {'.pdf', '.txt', '.docx', '.png', '.jpg', '.jpeg'},
        "max_files_per_conversation": 10
    },
    "architect": {
        "max_file_size": 20 * 1024 * 1024,  # 20MB
        "allowed_extensions": {'.pdf', '.txt', '.docx', '.png', '.jpg', '.jpeg'},
        "max_files_per_conversation": 25
    },
    "awakener": {
        "max_file_size": 50 * 1024 * 1024,  # 50MB
        "allowed_extensions": {'.pdf', '.txt', '.docx', '.png', '.jpg', '.jpeg', '.mp4', '.mov'},
        "max_files_per_conversation": -1  # Unlimited
    },
    "wanderer": {
        "max_file_size": 0,  # No file uploads for free tier
        "allowed_extensions": set(),
        "max_files_per_conversation": 0
    }
}

class FileUploadError(Exception):
    """Custom exception for file upload errors"""
    pass

class FileManager:
    """Manages file uploads with tier-based restrictions"""
    
    def __init__(self):
        self.supabase_manager = SupabaseManager()
        self.upload_dir = Path("uploads")
        self.upload_dir.mkdir(exist_ok=True)
    
    def validate_file_upload(self, file_size: int, file_extension: str, user_tier: str, 
                           conversation_id: str, user_id: str) -> Dict[str, Any]:
        """Validate file upload against tier restrictions"""
        
        # Check if tier allows file uploads
        if user_tier == "wanderer":
            return {
                "allowed": False,
                "error": "File uploads not available for Wanderer tier",
                "upgrade_message": "Upgrade to Builder tier to unlock file uploads",
                "upgrade_url": "https://www.firststepai.tech/pricing"
            }
        
        tier_config = TIER_CONFIG.get(user_tier, TIER_CONFIG["builder"])
        
        # Check file size
        if file_size > tier_config["max_file_size"]:
            return {
                "allowed": False,
                "error": f"File size exceeds limit for {user_tier} tier",
                "max_size": tier_config["max_file_size"],
                "file_size": file_size,
                "size_limit_mb": tier_config["max_file_size"] / (1024 * 1024)
            }
        
        # Check file extension
        if file_extension.lower() not in tier_config["allowed_extensions"]:
            return {
                "allowed": False,
                "error": f"File type not supported for {user_tier} tier",
                "allowed_extensions": list(tier_config["allowed_extensions"]),
                "provided_extension": file_extension
            }
        
        # Check per-conversation file limit
        if tier_config["max_files_per_conversation"] > 0:
            try:
                current_file_count = self.get_conversation_file_count(conversation_id, user_id)
                if current_file_count >= tier_config["max_files_per_conversation"]:
                    return {
                        "allowed": False,
                        "error": f"File limit reached for {user_tier} tier",
                        "max_files": tier_config["max_files_per_conversation"],
                        "current_files": current_file_count
                    }
            except Exception as count_error:
                # Continue anyway - don't block upload due to count check failure
                logger.error(f"Error checking file count: {count_error}")
        
        return {"allowed": True}
    
    def get_conversation_file_count(self, conversation_id: str, user_id: str) -> int:
        """Get current file count for a conversation"""
        try:
            supabase = self.supabase_manager.client
            result = supabase.from_("conversation_files").select("id").eq("conversation_id", conversation_id).eq("user_id", user_id).execute()
            return len(result.data) if result.data else 0
        except Exception as e:
            logger.error(f"Error getting file count: {e}")
            return 0
    
    def process_uploaded_file(self, file_content: bytes, filename: str, user_tier: str, 
                            user_id: str, conversation_id: str) -> Dict[str, Any]:
        """Process uploaded file using existing process_any_input function"""
        
        file_id = f"file_{uuid.uuid4()}"
        secure_name = secure_filename(filename)
        file_extension = Path(filename).suffix
        
        # Validate upload
        validation = self.validate_file_upload(
            len(file_content), file_extension, user_tier, conversation_id, user_id
        )
        
        if not validation["allowed"]:
            return {"success": False, "error": validation}
        
        try:
            # Create temporary file for processing
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            
            try:
                # Process file using existing markitdwon functionality
                processed_content = process_any_input(temp_file_path)
                
                # Store file metadata in Supabase
                file_metadata = {
                    "file_id": file_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "original_filename": filename,
                    "secure_filename": secure_name,
                    "file_extension": file_extension,
                    "file_size": len(file_content),
                    "user_tier": user_tier,
                    "processed_content": processed_content,
                    "content_preview": processed_content[:500] if processed_content else None,  # First 500 chars
                    "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                    "processing_status": "completed"
                }
                
                # Save to Supabase
                supabase = self.supabase_manager.client
                try:
                    result = supabase.from_("conversation_files").insert(file_metadata).execute()
                except Exception as supabase_error:
                    logger.error(f"Supabase insert error: {supabase_error}")
                    # Continue anyway, file processing worked
                
                # Clean up temp file
                os.unlink(temp_file_path)
                
                return {
                    "success": True,
                    "file_id": file_id,
                    "processed_content": processed_content,
                    "metadata": {
                        "filename": filename,
                        "size": len(file_content),
                        "type": file_extension,
                        "conversation_id": conversation_id
                    }
                }
                
            except Exception as processing_error:
                # Clean up temp file on error
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                
                return {
                    "success": False,
                    "error": f"File processing failed: {str(processing_error)}",
                    "file_id": file_id
                }
                
        except Exception as e:
            logger.error(f"File upload error: {e}")
            return {
                "success": False,
                "error": f"Upload failed: {str(e)}"
            }
    


# Global file manager instance
file_manager = FileManager()

def upload_file(file_content: bytes, filename: str, user_tier: str, 
               user_id: str, conversation_id: str) -> Dict[str, Any]:
    """Convenience function for file upload"""
    return file_manager.process_uploaded_file(file_content, filename, user_tier, user_id, conversation_id)

 