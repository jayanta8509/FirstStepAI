import os
from supabase import create_client, Client
import uuid
from dotenv import load_dotenv
import asyncio
load_dotenv()


url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")


async def store_data_supabase(assistant_name,model_used,AI_response,user_query,user_id,task_category):
    supabase: Client = create_client(url, key)
    responce_id  = f"responce_{str(uuid.uuid4())}"
    try:
        resp = (
            supabase
            .from_("AI_message_store")  
            .insert({"assistant_name": assistant_name, "model_used": model_used, "AI_response": AI_response, "user_message": user_query, "user_id": user_id, "task_category": task_category, "responce_id": responce_id}) 
            .execute()
        )
        print("Single insert successful:")
        return responce_id
    except Exception as e:
        print(f"Error in single insert: {e}")