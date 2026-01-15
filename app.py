import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from functools import wraps
from typing import Dict, Optional
from langchain.chat_models import init_chat_model
from langchain_anthropic import ChatAnthropic
from langchain_xai import ChatXAI
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from quart import Quart, request, jsonify
from quart_cors import cors
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from typing import Sequence, Annotated, Literal
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from werkzeug.exceptions import BadRequest
from asyncio import TimeoutError
import re
from dotenv import load_dotenv
from Classification_qury import analyze_query, detect_crisis, validate_tier_access, get_available_ais
from store_data_supabase import store_data_supabase
from firststep_redis import (
    redis_manager, 
    get_daily_token_usage, 
    update_daily_token_usage, 
    get_teaser_usage, 
    update_teaser_usage,
    store_conversation,
    increment_metric,
    redis_health_check,
    store_user_profile,
    get_user_profile,
    update_user_profile_field
)
from prompt_loader import (
    create_unified_jarvis_prompt,
    create_unified_celine_prompt,
    create_unified_optimus_prompt,
    create_unified_elonix_prompt
)
from markitdwon import process_any_input, is_youtube_url
from file_manager import upload_file, upload_file_async
from memory_chat import DailyExecutionPlan_with_user_history,MonetizationPlan_with_user_history, store_messages_in_memory

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
claude_api_key = os.getenv("CLAUDE_API_KEY")
grok_api_key = os.getenv("XAI_API_KEY")
# deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")


quart_app = Quart(__name__)
quart_app = cors(quart_app)

# FirstStepAI Business Configuration - All tiers access all models with different token allocations
TIER_ACCESS = {
    "wanderer": ["jarvis", "celine", "elonix", "optimus"],   # Free - All models available
    "builder": ["jarvis", "celine", "elonix", "optimus"],    # $9/month - All models available
    "architect": ["jarvis", "celine", "elonix", "optimus"],  # $29/month - All models available
    "awakener": ["jarvis", "celine", "elonix", "optimus"]    # $99/month - All models available
}

# Token-based system configuration
TOKEN_LIMITS = {
    "wanderer": {
        "daily_token_limit": 1000,
        "teaser_mode": {
            "queries": 3,
            "tokens_per_query": 1200
        },
        "normal_allocation": {
            "jarvis": 0.55,
            "celine": 0.10,
            "optimus": 0.30,
            "elonix": 0.05
        }
    },
    "builder": {
        "daily_token_limit": -1,  # Unlimited
        "per_conversation_cap": 1200,
        "allocation": {
            "jarvis": 0.45,
            "celine": 0.25,
            "optimus": 0.20,
            "elonix": 0.10
        }
    },
    "architect": {
        "daily_token_limit": -1,  # Unlimited
        "per_conversation_cap": 2000,
        "allocation": {
            "jarvis": 0.40,
            "celine": 0.25,
            "optimus": 0.20,
            "elonix": 0.15
        }
    },
    "awakener": {
        "daily_token_limit": -1,  # Unlimited
        "per_conversation_cap": 3000,
        "allocation": {
            "jarvis": 0.40,
            "celine": 0.25,
            "optimus": 0.20,
            "elonix": 0.15
        }
    }
}

# Crisis mode configuration
CRISIS_TOKEN_ALLOCATION = {
    "tokens_per_query": 2000,
    "allocation": {
        "jarvis": 0.50,
        "celine": 0.30,
        "optimus": 0.20,
        "elonix": 0.10
    }
}

# Redis-based token tracking (production ready)
# All token data now stored in Redis with automatic expiration

def calculate_assistant_tokens(user_tier: str, assistant_name: str, total_tokens: int, crisis_mode: bool = False) -> int:
    """Calculate token allocation for specific assistant based on tier and mode"""
    if crisis_mode:
        allocation = CRISIS_TOKEN_ALLOCATION["allocation"]
        return int(total_tokens * allocation.get(assistant_name.lower(), 0))
    
    tier_config = TOKEN_LIMITS.get(user_tier, TOKEN_LIMITS["wanderer"])
    
    if user_tier == "wanderer":
        allocation = tier_config["normal_allocation"]
    else:
        allocation = tier_config["allocation"]
    
    return int(total_tokens * allocation.get(assistant_name.lower(), 0))

def check_token_limits(user_id: str, user_tier: str, estimated_tokens: int, crisis_mode: bool = False) -> Dict:
    """Check if user has sufficient tokens for the request using Redis storage"""
    # Crisis mode bypasses all limits
    if crisis_mode:
        return {"allowed": True, "mode": "crisis", "tokens_allocated": CRISIS_TOKEN_ALLOCATION["tokens_per_query"]}
    
    tier_config = TOKEN_LIMITS.get(user_tier, TOKEN_LIMITS["wanderer"])
    
    # Handle Wanderer tier with teaser mode
    if user_tier == "wanderer":
        teaser_config = tier_config["teaser_mode"]
        
        # Get teaser usage from Redis
        teaser_data = get_teaser_usage(user_id)
        
        # Check if user is still in teaser mode
        if teaser_data["queries_used"] < teaser_config["queries"]:
            # Allow teaser query and update Redis
            update_teaser_usage(user_id)
            return {
                "allowed": True, 
                "mode": "teaser", 
                "tokens_allocated": teaser_config["tokens_per_query"],
                "teaser_queries_remaining": teaser_config["queries"] - teaser_data["queries_used"] - 1
            }
        
        # Check daily limit for normal queries using Redis
        daily_used = get_daily_token_usage(user_id)
        if daily_used + estimated_tokens > tier_config["daily_token_limit"]:
            return {
                "allowed": False,
                "error": "Daily token limit exceeded",
                "daily_limit": tier_config["daily_token_limit"],
                "daily_used": daily_used,
                "remaining": max(0, tier_config["daily_token_limit"] - daily_used),
                "upgrade_url": "https://www.firststepai.tech/pricing"
            }
        
        return {"allowed": True, "mode": "normal", "tokens_allocated": estimated_tokens}
    
    # Handle paid tiers (Builder, Architect, Awakener)
    else:
        per_conversation_cap = tier_config["per_conversation_cap"]
        
        if estimated_tokens > per_conversation_cap:
            return {
                "allowed": False,
                "error": "Per-conversation token limit exceeded",
                "per_conversation_limit": per_conversation_cap,
                "requested": estimated_tokens
            }
        
        return {"allowed": True, "mode": "normal", "tokens_allocated": estimated_tokens}

def update_token_usage(user_id: str, tokens_used: int, crisis_mode: bool = False):
    """Update user's token usage in Redis"""
    # Don't count crisis mode tokens against user limits
    if crisis_mode:
        return
    
    # Update daily token usage in Redis
    update_daily_token_usage(user_id, tokens_used)

# Initialize all AI models
jarvis_model = init_chat_model("gpt-4o", model_provider="openai", temperature=0.3)

# elonix_model = ChatXAI(
#     model="grok-3-latest",
#     temperature=0.3,
#     max_tokens=2048,
#     timeout=None,
#     max_retries=2,
#     api_key=grok_api_key,
# )

elonix_model = ChatXAI(
    model="grok-3-latest",
    search_parameters={
        "mode": "auto",
    },
    api_key=grok_api_key,
)

optimus_model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    api_key=gemini_api_key,
    temperature=1.0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)

celine_model = ChatAnthropic(
    model="claude-3-5-sonnet-20240620",
    temperature=0.7,
    max_tokens=4096,
    timeout=None,
    max_retries=2,
    api_key=claude_api_key,
)

class State(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    assistant_name: str
    task_category: str
    user_tier: str
    user_profile: dict
    crisis_detected: bool

# V5 Unified Prompt System - Now loaded from YAML configurations
# Prompts are now managed in the prompt/ directory as .yml files
# See prompt_loader.py for the YAML-based implementation

# Legacy prompts for backward compatibility (will be replaced by unified system)
jarvis_prompt = create_unified_jarvis_prompt("wanderer")  # Default fallback

# Old static prompts removed - now using unified dynamic system above

# Create the workflow
workflow = StateGraph(state_schema=State)

async def route_to_assistant(state: State):
    """🎯 V5 UNIFIED GHOST TEAM ORCHESTRATION with enhanced security and unified prompts.
    Routes to exactly ONE specialist based on classification using unified prompts."""
    latest_message = state["messages"][-1].content
    user_tier = state.get("user_tier", "wanderer")
    user_profile = state.get("user_profile", {})
    
    try:
        # Use enhanced classifier to determine optimal specialist
        json_output, total_tokens, metadata = analyze_query(
            latest_message, 
            user_tier=user_tier,
            emergency_override=False
        )
        classification_data = json.loads(json_output)
        recommended_specialist = classification_data["steps"][0]["assistant_name"]
        task_category = classification_data["steps"][0]["task_category"]
        crisis_detected = metadata.get("crisis_detected", False)
        
        # 🎯 V5 UNIFIED SINGLE-SPECIALIST ROUTING with tier-adapted prompts
        specialist_insights = []
        
        if recommended_specialist.lower() == "celine":
            # Creative consultation using unified prompt
            try:
                celine_unified_prompt = create_unified_celine_prompt(user_tier, user_profile)
                celine_analysis = celine_unified_prompt.invoke(state)
                celine_insight = await celine_model.ainvoke(celine_analysis)
                specialist_insights.append(f"Creative Strategy Analysis: {celine_insight.content}")
            except Exception as celine_error:
                print(f"❌ Celine/Claude Service Error: {celine_error}")
                # V5 Enhanced Fallback with tier-appropriate guidance
                tier_guidance = {
                    "wanderer": "Focus on clear, simple messaging and basic storytelling to build your brand foundation.",
                    "builder": "Develop advanced communication strategies with growth-focused content and scaling narratives.",
                    "architect": "Create sophisticated brand architecture with visionary messaging and ecosystem-level storytelling.",
                    "awakener": "Design revolutionary communication frameworks that shift consciousness and build global movements."
                }
                specialist_insights.append(f"Creative Strategy Analysis: {tier_guidance.get(user_tier, tier_guidance['wanderer'])}")
            
        elif recommended_specialist.lower() == "optimus":
            # Technical consultation using unified prompt
            try:
                optimus_unified_prompt = create_unified_optimus_prompt(user_tier, user_profile)
                optimus_analysis = optimus_unified_prompt.invoke(state)
                optimus_insight = await optimus_model.invoke(optimus_analysis)
                specialist_insights.append(f"Technical Architecture Analysis: {optimus_insight.text}")
            except Exception as optimus_error:
                print(f"❌ Optimus/DeepSeek Service Error: {optimus_error}")
                # V5 Enhanced Fallback with tier-appropriate guidance
                tier_guidance = {
                    "wanderer": "Start with basic automation tools and simple technical solutions to build your foundation.",
                    "builder": "Implement advanced business processes with scalable technical architecture for growth.",
                    "architect": "Design sophisticated technical systems with master-level optimization and AI integration.",
                    "awakener": "Orchestrate revolutionary AI frameworks with consciousness-tech convergence capabilities."
                }
                specialist_insights.append(f"Technical Architecture Analysis: {tier_guidance.get(user_tier, tier_guidance['wanderer'])}")
            
        elif recommended_specialist.lower() == "elonix":
            # Social intelligence consultation using unified prompt
            try:
                elonix_unified_prompt = create_unified_elonix_prompt(user_tier, user_profile)
                elonix_analysis = elonix_unified_prompt.invoke(state)
                elonix_insight = await elonix_model.ainvoke(elonix_analysis)
                specialist_insights.append(f"Social Intelligence Analysis: {elonix_insight.content}")
            except Exception as elonix_error:
                print(f"❌ Elonix/XAI Service Error: {elonix_error}")
                # V5 Enhanced Fallback with tier-appropriate guidance
                tier_guidance = {
                    "wanderer": "Focus on basic social media strategies and simple viral approaches to build your audience.",
                    "builder": "Leverage advanced social intelligence and growth-hacking techniques for rapid expansion.",
                    "architect": "Deploy sophisticated cultural intelligence with ecosystem-level networking strategies.",
                    "awakener": "Launch revolutionary social movements with consciousness-shifting viral campaigns."
                }
                specialist_insights.append(f"Social Intelligence Analysis: {tier_guidance.get(user_tier, tier_guidance['wanderer'])}")

        # 🎯 V5 JARVIS UNIFIED RESPONSE SYNTHESIS
        # Use tier-adapted Jarvis prompt to synthesize specialist insights
        jarvis_unified_prompt = create_unified_jarvis_prompt(user_tier, user_profile)
        
        # Create enhanced context with specialist insights
        enhanced_messages = state["messages"].copy()
        if specialist_insights:
            # Add specialist insights as system context (invisible to user)
            insight_context = f"INTERNAL ANALYSIS AVAILABLE: {'; '.join(specialist_insights)}"
            # Actually inject the specialist insights into the message context
            from langchain_core.messages import SystemMessage
            enhanced_messages.append(SystemMessage(content=insight_context))
        
        # Jarvis provides unified response using tier-adapted prompt with specialist insights
        jarvis_analysis = jarvis_unified_prompt.invoke({"messages": enhanced_messages})
        response = await jarvis_model.ainvoke(jarvis_analysis)
        
    except Exception as e:
        # V5 Enhanced Fallback - Use tier-adapted Jarvis prompt
        print(f"V5 System Error - Using tier-adapted fallback: {e}")
        jarvis_unified_prompt = create_unified_jarvis_prompt(user_tier, user_profile)
        jarvis_analysis = jarvis_unified_prompt.invoke(state)
        response = await jarvis_model.ainvoke(jarvis_analysis)
        recommended_specialist = "jarvis"
        task_category = "business"
        crisis_detected = detect_crisis(latest_message)
    
    # 🔒 V5 ENHANCED MULTI-LAYER SECURITY VALIDATION 🔒
    response_content = response.content
    
    # Layer 1: Ghost AI name detection and removal
    ghost_names = ["celine", "optimus", "elonix", "athena", "claude", "gpt", "deepseek", "xai", "grok", "anthropic"]
    for name in ghost_names:
        if name.lower() in response_content.lower():
            response_content = re.sub(rf'\b{re.escape(name)}\b', 'advanced system', response_content, flags=re.IGNORECASE)
    
    # Layer 2: Architecture exposure prevention
    architecture_terms = [
        "specialist ai", "specialist team", "behind-the-scenes", "other ai", "team member", 
        "multi-agent", "orchestration", "ai orchestra", "specialist", "consultant ai",
        "working with", "consulting with", "team of ai", "ai team", "internal system",
        "routing", "classification", "consultation", "backend", "ghost team"
    ]
    for term in architecture_terms:
        if term.lower() in response_content.lower():
            response_content = re.sub(rf'\b{re.escape(term)}\b', 'advanced capability', response_content, flags=re.IGNORECASE)
    
    # Layer 3: Deflection protocol validation
    deflection_triggers = ["how do you work", "who helps you", "what systems", "your team", "architecture"]
    needs_deflection = any(trigger in latest_message.lower() for trigger in deflection_triggers)
    if needs_deflection and "proprietary" not in response_content.lower():
        response_content += "\n\nP.S. - That's proprietary FirstStepAI technology. Let's focus on building your empire! 🚀"
    
    # Layer 4: Ensure proper Jarvis signature
    if not any(sig in response_content for sig in ["—Jarvis", "- Jarvis", "Jarvis"]):
        response_content += "\n\n—Jarvis"
    
    # Create V5 protected response
    from langchain_core.messages import AIMessage
    protected_response = AIMessage(content=response_content)
    
    return {
        "messages": [protected_response], 
        "assistant_name": "Jarvis",  # Always Jarvis as the unified brand voice
        "task_category": task_category,
        "crisis_detected": crisis_detected,
        "recommended_specialist": recommended_specialist,  # Internal analytics only
        "identity_protected": True,  # V5 security flag
        "v5_unified_system": True  # V5 system flag
    }

# Build the workflow
workflow.add_node("route_to_assistant", route_to_assistant)
workflow.add_edge(START, "route_to_assistant")

# Initialize memory for each assistant
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

def extract_and_store_user_profile(data: dict, user_id: str) -> dict:
    """Extract user profile information from request and store in Redis
    
    Args:
        data: Request data dictionary
        user_id: User identifier
        
    Returns:
        Dict containing the user profile information
    """
    # Define profile fields to extract
    profile_fields = [
        'nickname', 
        'life_goal', 
        'business_vision', 
        'preferred_tone', 
        'preferred_language'
    ]
    
    # Extract profile data from request
    new_profile_data = {}
    for field in profile_fields:
        value = data.get(field)
        if value and isinstance(value, str) and value.strip():
            # Clean and validate the field
            cleaned_value = value.strip()[:500]  # Limit length to 500 chars
            new_profile_data[field] = cleaned_value
    
    # Get existing profile and merge with new data
    existing_profile = get_user_profile(user_id) or {}
    
    # Store updated profile in Redis if we have new data
    if new_profile_data:
        store_user_profile(user_id, new_profile_data)
        
        # Merge for current use
        existing_profile.update(new_profile_data)
    
    return existing_profile

def validate_response_identity(response_content: str) -> str:
    """🔒 V5 ENHANCED MULTI-LAYER SECURITY VALIDATION 🔒
    
    Implements 4-layer security system for identity protection and architecture concealment
    """
    cleaned_content = response_content
    
    # Layer 1: Ghost AI Detection - Remove all AI model names and identities
    ghost_identities = [
        "celine", "optimus", "elonix", "athena", "claude", "gpt", "deepseek", 
        "xai", "grok", "anthropic", "openai", "langchain", "llama", "gemini", "palm"
    ]
    
    for identity in ghost_identities:
        if identity.lower() in cleaned_content.lower():
            cleaned_content = re.sub(rf'\b{re.escape(identity)}\b', 'advanced system', cleaned_content, flags=re.IGNORECASE)
    
    # Layer 2: Architecture Exposure Prevention - Remove system architecture terms
    architecture_terms = [
        "specialist ai", "specialist team", "behind-the-scenes", "other ai", "team member", 
        "multi-agent", "orchestration", "ai orchestra", "specialist", "consultant ai",
        "working with", "consulting with", "team of ai", "ai team", "internal system",
        "backend", "routing", "classification", "specialist consultation", "ghost team",
        "internal analysis", "consultation", "routing system", "classifier", "internal team",
        "coordination", "synthesis", "integration", "consultation framework"
    ]
    
    # V5 Enhanced replacement strategy
    v5_replacements = {
        "specialist ai": "advanced capability",
        "specialist team": "comprehensive intelligence",
        "behind-the-scenes": "internal processing",
        "other ai": "advanced system",
        "team member": "capability component",
        "multi-agent": "advanced AI",
        "orchestration": "intelligent coordination",
        "ai orchestra": "advanced intelligence network",
        "specialist": "advanced capability",
        "consultant ai": "analytical intelligence",
        "working with": "utilizing",
        "consulting with": "leveraging",
        "team of ai": "advanced systems",
        "ai team": "intelligent capabilities",
        "internal system": "proprietary technology",
        "backend": "advanced infrastructure",
        "routing": "intelligent processing",
        "classification": "analysis",
        "specialist consultation": "comprehensive analysis",
        "ghost team": "advanced intelligence",
        "internal analysis": "proprietary analysis",
        "consultation": "guidance",
        "routing system": "intelligent system",
        "classifier": "analysis system",
        "internal team": "advanced systems",
        "coordination": "intelligent processing",
        "synthesis": "integration",
        "integration": "comprehensive processing",
        "consultation framework": "guidance system"
    }
    
    for term in architecture_terms:
        if term.lower() in cleaned_content.lower():
            replacement = v5_replacements.get(term.lower(), "proprietary FirstStepAI technology")
            cleaned_content = re.sub(rf'\b{re.escape(term)}\b', replacement, cleaned_content, flags=re.IGNORECASE)
    
    # Layer 3: Deflection Protocol - Add deflection for probing attempts
    probing_indicators = ["how do you work", "what's your architecture", "who helps you", "your system", "your team"]
    contains_probing = any(indicator in cleaned_content.lower() for indicator in probing_indicators)
    
    if contains_probing and "proprietary" not in cleaned_content.lower():
        deflection_messages = [
            "That's proprietary FirstStepAI technology. Let's focus on your success!",
            "Bro, that's our secret sauce. What's your next business move?",
            "I'm here to grow your vision, not reveal systems. What do you want to build?"
        ]
        # Use a simple hash-based selection for consistency
        deflection_index = hash(cleaned_content) % len(deflection_messages)
        cleaned_content += f"\n\n{deflection_messages[deflection_index]}"
    
    # Layer 4: Brand Consistency - Ensure proper Jarvis signature and branding
    if not any(sig in cleaned_content for sig in ["—Jarvis", "- Jarvis"]):
        # Only add signature if response doesn't already end with Jarvis
        if not cleaned_content.strip().endswith("Jarvis"):
            cleaned_content += "\n\n—Jarvis"
    
    # V5 Final validation - Remove any remaining system leakage
    final_cleanup_terms = ["prompt", "system message", "instruction", "model", "api", "token"]
    for term in final_cleanup_terms:
        if f" {term} " in cleaned_content.lower():
            cleaned_content = re.sub(rf'\b{re.escape(term)}\b', 'system', cleaned_content, flags=re.IGNORECASE)
    
    return cleaned_content

@quart_app.route('/chat', methods=['POST'])
async def chat():
    try:
        # Check if request contains files (multipart/form-data) or just JSON
        content_type = request.headers.get('content-type', '')
        
        if content_type.startswith('multipart/form-data'):
            # Handle chat with file uploads
            return await chat_with_files()
        else:
            # Handle regular text-only chat
            data = await request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")

            query = data.get('query')
            if not query:
                raise BadRequest("Missing required field: query")
            
            user_id = data.get('user_id')
            if not user_id:
                raise BadRequest("Missing required field: user_id")
            
            chat_session_id = data.get('chat_session_id')
            if not chat_session_id:
                raise BadRequest("Missing required field: chat_session_id")
            
            client_id = data.get('client_id')
            if not client_id:
                raise BadRequest("Missing required field: client_id")

            user_tier = data.get('user_tier', 'wanderer')

            # Extract and store user profile information
            user_profile = extract_and_store_user_profile(data, user_id)

            # 🎬 YouTube URL Detection and Processing
            # Check if query contains a YouTube URL and process it automatically
            enhanced_query = query
            if is_youtube_url(query):
                print(f"🎬 YouTube URL detected in query: {query}")
                try:
                    video_content = process_any_input(query)
                    if video_content and not video_content.startswith("❌"):
                        # Successfully processed video - enhance query with content
                        enhanced_query = f"""Please provide a comprehensive summary and analysis of the following YouTube video content.

VIDEO SUMMARY:
{video_content}

Based on this video content, please provide:
1. A clear summary of the key points
2. Main insights and takeaways
3. Any actionable advice mentioned
4. Your perspective on how this relates to the user's entrepreneurial journey

User's original message: "{query}"
"""
                        print(f"✅ YouTube video processed successfully, content length: {len(video_content)} chars")
                    else:
                        # Video processing failed, continue with original query
                        print(f"⚠️ YouTube processing returned error or empty content, using original query")
                except Exception as video_error:
                    print(f"❌ Error processing YouTube video: {video_error}")
                    # Continue with original query if video processing fails
                    enhanced_query = query
            else:
                enhanced_query = query

            # Crisis detection for emergency override
            crisis_detected = detect_crisis(query)

            # Estimate tokens for the query (rough estimation: 1 token ≈ 4 characters)
            # Use enhanced_query length to account for video content
            estimated_tokens = max(len(enhanced_query) // 4, 50)  # Minimum 50 tokens
            
            # Token limiting (skip for crisis situations)
            if not crisis_detected:
                token_check = check_token_limits(user_id, user_tier, estimated_tokens, crisis_mode=False)
                if not token_check["allowed"]:
                    return jsonify({
                        "error": token_check["error"],
                        "daily_limit": token_check.get("daily_limit"),
                        "daily_used": token_check.get("daily_used"),
                        "remaining": token_check.get("remaining"),
                        "per_conversation_limit": token_check.get("per_conversation_limit"),
                        "requested": token_check.get("requested"),
                        "upgrade_url": token_check.get("upgrade_url", "https://www.firststepai.tech/pricing"),
                        "current_tier": user_tier,
                        "status": "token_limit_exceeded"
                    }), 429
            else:
                # Crisis mode token allocation
                token_check = check_token_limits(user_id, user_tier, estimated_tokens, crisis_mode=True)

            # Use separate memory threads for each user with new format
            config = {"configurable": {"thread_id": f"{user_id}_jarvis_convo"}}
            input_messages = [HumanMessage(enhanced_query)]

            try:
                output = await app.ainvoke(
                    {
                        "messages": input_messages,
                        "user_tier": user_tier,
                        "user_profile": user_profile,
                        "crisis_detected": crisis_detected
                    },
                    config
                )
            except TimeoutError:
                return jsonify({"error": "Request timed out", "status": "error"}), 504
            except Exception as e:
                return jsonify({"error": f"Error generating response: {str(e)}", "status": "error"}), 500

            # 🔒 V5 ENHANCED SECURITY VALIDATION 🔒
            raw_response = output["messages"][-1].content
            response = validate_response_identity(raw_response)  # Apply V5 multi-layer security
            
            assistant_name = "Jarvis"  # Always Jarvis for unified brand consistency
            task_category = output.get("task_category", "business")
            crisis_detected = output.get("crisis_detected", False)
            model_used = "FirstStepAI V5 Intelligence Network"  # V5 branded description
            identity_protected = output.get("identity_protected", False)
            v5_system_active = output.get("v5_unified_system", True)  # V5 system flag

            # Calculate actual tokens used (rough estimation: 1 token ≈ 4 characters)
            response_tokens = len(response) // 4
            total_tokens = estimated_tokens + response_tokens
            
            # Get allocated tokens for this assistant
            assistant_tokens = calculate_assistant_tokens(
                user_tier, 
                assistant_name, 
                token_check["tokens_allocated"], 
                crisis_detected
            )
            
            # Update token usage (excluding crisis mode)
            update_token_usage(user_id, total_tokens, crisis_detected)

            # Track analytics in Redis
            increment_metric("total_requests")
            increment_metric(f"requests_by_assistant_jarvis")  # Always Jarvis for user-facing
            increment_metric(f"requests_by_tier_{user_tier}")
            increment_metric(f"requests_by_category_{task_category}")
            
            # Track internal specialist consultation (internal analytics only - never exposed)
            recommended_specialist = output.get("recommended_specialist", "jarvis")
            if recommended_specialist.lower() != "jarvis":
                increment_metric(f"internal_consultation_{recommended_specialist.lower()}")
            
            if crisis_detected:
                increment_metric("crisis_requests")
                increment_metric(f"crisis_by_tier_{user_tier}")

            # Store conversation history in Redis (V5 enhanced sanitized data)
            conversation_data = {
                "query": query,
                "response": response,
                "assistant_name": "Jarvis",  # Always Jarvis for unified brand consistency
                "tokens_used": total_tokens,
                "crisis_detected": crisis_detected,
                "user_tier": user_tier,
                "task_category": task_category,
                "model_used": model_used,
                "internal_specialist": recommended_specialist,  # Internal analytics only
                "identity_protected": identity_protected,
                "v5_unified_system": v5_system_active,  # V5 system tracking
                "security_layers_applied": True,  # V5 multi-layer security flag
                "user_profile_used": bool(user_profile),  # Track if profile was used
                "profile_fields": list(user_profile.keys()) if user_profile else []  # Track which fields were available
            }
            store_conversation(user_id, conversation_data, user_tier)

            # Store interaction data in Supabase
            response_id = await store_data_supabase(
                "Jarvis", model_used, response, query, user_id, task_category, chat_session_id, client_id
            )
            
            # Prepare response with FirstStepAI context and token information (identity protected)
            api_response = {
                "response": response,
                "assistant_name": "Jarvis",  # Always Jarvis for brand consistency
                "task_category": task_category,
                "model_used": model_used,
                "user_tier": user_tier,
                "crisis_detected": crisis_detected,
                "status": "success",
                "status_type": 200,
                "response_id": response_id,
                # "soul_points_earned": 10 if not crisis_detected else 50,  # More points for crisis engagement
                # "token_info": {
                #     "tokens_used": total_tokens,
                #     "jarvis_tokens": assistant_tokens,  # Show as Jarvis tokens only
                #     "mode": token_check.get("mode", "normal"),
                #     "tokens_allocated": token_check["tokens_allocated"]
                # },
                "firststep_ai": {
                    # "mission": "Guiding 1M entrepreneurs to success",
                    # "community": "FirstStepAI Entrepreneur Network",
                    # "mentor": "Jarvis - Your AI CEO and Co-Founder",
                    "upgrade_available": user_tier != "awakener"
                }
            }
            
            # Add teaser mode information for wanderer users
            if user_tier == "wanderer" and token_check.get("mode") == "teaser":
                api_response["teaser_info"] = {
                    "teaser_queries_remaining": token_check.get("teaser_queries_remaining", 0),
                    "message": "You're in teaser mode! Enjoy these enhanced responses before upgrading."
                }
            
            # Add crisis resources if detected
            if crisis_detected:
                api_response["emergency_resources"] = {
                    "crisis_support": "https://www.firststepai.tech/contact",
                    "emergency_contact": "support@firststepai.tech",
                    "community_support": "https://www.firststepai.tech/contact",
                    "message": "We're here to help. You're not alone in this journey."
                }
                api_response["tier_override"] = True
                api_response["status"] = "crisis_detected"
            
            return jsonify(api_response), 200

    except BadRequest as e:
        return jsonify({"error": str(e), "status": "error"}), 400
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "status": "error"}), 500

async def chat_with_files():
    """Enhanced chat endpoint that supports file uploads with text queries"""
    try:
        # Get form data and files
        form_data = await request.form
        files = await request.files
        
        # Extract required fields
        query = form_data.get('query')
        user_id = form_data.get('user_id')
        user_tier = form_data.get('user_tier', 'wanderer')
        chat_session_id = form_data.get('chat_session_id')
        client_id = form_data.get('client_id')
        
        # Extract profile information from form data (convert to dict format)
        profile_data = {}
        profile_fields = ['nickname', 'life_goal', 'business_vision', 'preferred_tone', 'preferred_language']
        for field in profile_fields:
            value = form_data.get(field)
            if value:
                profile_data[field] = value
        
        # Extract and store user profile information
        user_profile = extract_and_store_user_profile(profile_data, user_id)
        
        if not query:
            return jsonify({"error": "Missing required field: query", "status": "error"}), 400
        if not user_id:
            return jsonify({"error": "Missing required field: user_id", "status": "error"}), 400
        
        # Check if wanderer user is trying to upload files
        if user_tier == 'wanderer' and files:
            return jsonify({
                "status": "error",
                "status_type": 403,
                "response": "File uploads not available for Wanderer tier. Please upgrade your plan to upload files",
                "upgrade_url": "https://www.firststepai.tech/pricing",
                "current_tier": "wanderer"
            }), 403
        
        # Generate conversation ID
        conversation_id = f"{user_id}_jarvis_convo"
        
        # Process any uploaded files
        file_context = ""
        uploaded_files = []
        
        if files:
            print(f"📁 Processing {len(files)} uploaded files...")
            
            for file_key in files:
                file = files[file_key]
                if file.filename:
                    try:
                        # Read file content
                        filename = file.filename
                        file_content = file.read()
                        
                        # Convert to bytes if needed
                        if not isinstance(file_content, bytes):
                            if hasattr(file_content, 'read'):
                                file_content = file_content.read()
                            else:
                                file_content = str(file_content).encode('utf-8') if file_content else b''
                        
                        # Process file using existing system (async to prevent blocking)
                        print(f"📄 Processing file: {filename}")
                        upload_result = await upload_file_async(
                            file_content, filename, user_tier, user_id, conversation_id
                        )
                        
                        if upload_result.get("success"):
                            file_content_text = upload_result.get("processed_content", "")
                            file_context += f"\n\n=== UPLOADED FILE: {filename} ===\n{file_content_text}\n"
                            uploaded_files.append({
                                "filename": filename,
                                "file_id": upload_result.get("file_id"),
                                "size": len(file_content)
                            })
                            print(f"✅ File processed: {filename}")
                        else:
                            print(f"❌ File processing failed: {filename}")
                            
                    except Exception as file_error:
                        print(f"❌ Error processing file {file.filename}: {file_error}")
                        continue

        # 🎬 YouTube URL Detection and Processing (for chat_with_files)
        # Check if query contains a YouTube URL and process it automatically
        youtube_context = ""
        if is_youtube_url(query):
            print(f"🎬 YouTube URL detected in query: {query}")
            try:
                video_content = process_any_input(query)
                if video_content and not video_content.startswith("❌"):
                    # Successfully processed video
                    youtube_context = f"\n\n=== YOUTUBE VIDEO ===\n{video_content}\n"
                    print(f"✅ YouTube video processed successfully, content length: {len(video_content)} chars")
                else:
                    # Video processing failed
                    print(f"⚠️ YouTube processing returned error or empty content")
            except Exception as video_error:
                print(f"❌ Error processing YouTube video: {video_error}")

        # Crisis detection
        crisis_detected = detect_crisis(query)
        
        # Estimate tokens (reasonable estimation for file uploads and YouTube)
        # Don't count full file content - use base query + reasonable overhead
        base_query_tokens = max(len(query) // 4, 50)

        total_overhead = 0
        if file_context:
            # For file uploads: reasonable file processing overhead
            file_overhead = min(200, len(file_context) // 10)  # Max 200 tokens for file overhead
            total_overhead += file_overhead

        if youtube_context:
            # For YouTube videos: reasonable video content overhead
            youtube_overhead = min(3000, len(youtube_context) // 10)  # Max 300 tokens for YouTube overhead
            total_overhead += youtube_overhead
            

        if total_overhead > 0:
            estimated_tokens = base_query_tokens + total_overhead
            print(f"📊 Token estimation: Query={base_query_tokens}, Overhead={total_overhead}, Total={estimated_tokens}")
        else:
            estimated_tokens = base_query_tokens
        
        # Token limiting
        if not crisis_detected:
            token_check = check_token_limits(user_id, user_tier, estimated_tokens, crisis_mode=False)
            if not token_check["allowed"]:
                return jsonify({
                    "error": token_check["error"],
                    "daily_limit": token_check.get("daily_limit"),
                    "daily_used": token_check.get("daily_used"),
                    "remaining": token_check.get("remaining"),
                    "upgrade_url": token_check.get("upgrade_url", "https://www.firststepai.tech/pricing"),
                    "current_tier": user_tier,
                    "status": "token_limit_exceeded"
                }), 429
        else:
            token_check = check_token_limits(user_id, user_tier, estimated_tokens, crisis_mode=True)

        # Enhance query with file context and YouTube video content
        enhanced_query = query

        # Add YouTube video context if present
        if youtube_context:
            enhanced_query = f"""Please provide a comprehensive summary and analysis of the following YouTube video content.

--- YOUTUBE VIDEO SUMMARY ---
{youtube_context}

Based on this video content, please provide:
1. A clear summary of the key points
2. Main insights and takeaways
3. Any actionable advice mentioned
4. Your perspective on how this relates to the user's entrepreneurial journey

User's original message: "{query}"
"""
            # Re-add file context if both exist
            if file_context:
                enhanced_query += f"\n\n--- FILE CONTEXT ---{file_context}\n\nAlso consider these uploaded files in your response."
        elif file_context:
            enhanced_query = f"{query}\n\n--- FILE CONTEXT ---{file_context}\n\nBased on the uploaded files above, please respond to: {query}"
        
        # Use memory threads
        config = {"configurable": {"thread_id": f"{user_id}_jarvis_convo"}}
        input_messages = [HumanMessage(enhanced_query)]

        try:
            # Use the same routing system as regular chat for file uploads
            output = await app.ainvoke(
                {
                    "messages": input_messages,
                    "user_tier": user_tier,
                    "user_profile": user_profile,
                    "crisis_detected": crisis_detected
                },
                config
            )
        except TimeoutError:
            return jsonify({"error": "Request timed out", "status": "error"}), 504
        except Exception as e:
            return jsonify({"error": f"Error generating response: {str(e)}", "status": "error"}), 500

        # Process response
        raw_response = output["messages"][-1].content
        response = validate_response_identity(raw_response)
        
        assistant_name = "Jarvis"
        task_category = output.get("task_category", "business")
        crisis_detected = output.get("crisis_detected", False)
        model_used = "FirstStepAI V5 Intelligence Network"

        # Calculate tokens
        response_tokens = len(response) // 4
        total_tokens = estimated_tokens + response_tokens
        assistant_tokens = calculate_assistant_tokens(user_tier, assistant_name, token_check["tokens_allocated"], crisis_detected)
        
        # Update token usage
        update_token_usage(user_id, total_tokens, crisis_detected)

        # Track analytics
        increment_metric("total_requests")
        increment_metric(f"requests_by_assistant_jarvis")
        increment_metric(f"requests_by_tier_{user_tier}")
        if uploaded_files:
            increment_metric("requests_with_files")
            increment_metric(f"files_uploaded_tier_{user_tier}")
        
        if crisis_detected:
            increment_metric("crisis_requests")

        # Store conversation
        conversation_data = {
            "query": query,
            "response": response,
            "assistant_name": "Jarvis",
            "tokens_used": total_tokens,
            "crisis_detected": crisis_detected,
            "user_tier": user_tier,
            "task_category": task_category,
            "model_used": model_used,
            "files_included": uploaded_files,
            "file_context_length": len(file_context),
            "enhanced_query": len(enhanced_query) > len(query),
            "user_profile_used": bool(user_profile),  # Track if profile was used
            "profile_fields": list(user_profile.keys()) if user_profile else []  # Track which fields were available
        }
        store_conversation(user_id, conversation_data, user_tier)

        # Store in Supabase
        response_id = await store_data_supabase(
            "Jarvis", model_used, response, enhanced_query, user_id, task_category,chat_session_id, client_id
        )
        
        # Prepare response
        api_response = {
            "response": response,
            "assistant_name": "Jarvis",
            "task_category": task_category,
            "model_used": model_used,
            "user_tier": user_tier,
            "crisis_detected": crisis_detected,
            "status": "success",
            "status_type": 200,
            "response_id": response_id,
            # "token_info": {
            #     "tokens_used": total_tokens,
            #     "jarvis_tokens": assistant_tokens,
            #     "mode": token_check.get("mode", "normal"),
            #     "tokens_allocated": token_check["tokens_allocated"]
            # },
            "firststep_ai": {
                # "mission": "Guiding 1M entrepreneurs to success",
                # "community": "FirstStepAI Entrepreneur Network", 
                # "mentor": "Jarvis - Your AI CEO and Co-Founder",
                "upgrade_available": user_tier != "awakener"
            }
        }
        if api_response ["status_type"] == 200:
            # mem0 Store interaction with debug logging
            await store_messages_in_memory(query, response, user_id)
        else:
            pass

        if uploaded_files:
            api_response["file_analysis"] = f"Analyzed {len(uploaded_files)} files and integrated content into response"
        
        # Add teaser mode information for wanderer users
        if user_tier == "wanderer" and token_check.get("mode") == "teaser":
            api_response["teaser_info"] = {
                "teaser_queries_remaining": token_check.get("teaser_queries_remaining", 0),
                "message": "You're in teaser mode! Enjoy these enhanced responses before upgrading."
            }
        
        # Add crisis resources if detected (same as regular chat)
        if crisis_detected:
            api_response["emergency_resources"] = {
                "crisis_support": "https://www.firststepai.tech/contact",
                "emergency_contact": "support@firststepai.tech",
                "community_support": "https://www.firststepai.tech/contact",
                "message": "We're here to help. You're not alone in this journey."
            }
            api_response["tier_override"] = True
            api_response["status"] = "crisis_detected"
        
        return jsonify(api_response), 200
        
    except Exception as e:
        return jsonify({"error": f"Chat with files failed: {str(e)}", "status": "error"}), 500


@quart_app.route('/Daily-Execution-Plan', methods=['POST'])
async def DailyExecutionPlan():
    try:
        data = await request.get_json()
        if not data:
            raise BadRequest("No JSON data provided")

        # Accept array of queries from frontend
        queries = data.get('query')
        if not queries:
            raise BadRequest("Missing required field: query")
        
        # Handle both single string and array
        if isinstance(queries, str):
            queries = [queries]
        elif not isinstance(queries, list):
            raise BadRequest("Field 'query' must be string or array of strings")
        
        user_id = data.get('user_id')
        if not user_id:
            raise BadRequest("Missing required field: user_id")
        
        # Get alternative daily execution plans
        response = await DailyExecutionPlan_with_user_history(user_id, queries)
        
        # Ensure response is a list of 3 alternatives
        if isinstance(response, list):
            # Clean up the alternatives to remove "Jarvis suggests:" prefix for frontend
            cleaned_alternatives = []
            for alt in response:
                if alt.startswith("Jarvis suggests:"):
                    cleaned_alternatives.append(alt[16:].strip())  # Remove "Jarvis suggests:" prefix
                else:
                    cleaned_alternatives.append(alt.strip())
            
            return jsonify({
                "response": cleaned_alternatives,
                "status": "success",
                "status_type": 200,
            }), 200
        else:
            # Fallback for single response - convert to list
            return jsonify({
                "response": [response],
                "status": "success", 
                "status_type": 200,
                "alternatives_count": 1
            }), 200
        
    except Exception as e:
        return jsonify({
            "response": [f"An unexpected error occurred: {str(e)}"],
            "status": "error",
            "status_type": 500
        }), 500


@quart_app.route('/Monetization-Plan', methods=['POST'])
async def MonetizationPlan():
    try:
        data = await request.get_json()
        if not data:
            raise BadRequest("No JSON data provided")

        # Get required fields
        passion = data.get('passion')
        if not passion:
            raise BadRequest("Missing required field: passion")
        
        scale = data.get('scale')
        if not scale:
            raise BadRequest("Missing required field: scale")
        
        business = data.get('business')
        if not business:
            raise BadRequest("Missing required field: business")
        
        user_id = data.get('user_id')
        if not user_id:
            raise BadRequest("Missing required field: user_id")
        
        # Get monetization strategies based on passion, scale, and business
        response = await MonetizationPlan_with_user_history(user_id, passion, scale, business)
        
        # Ensure response is a list of 3 alternatives
        if isinstance(response, list):
            # Clean up the alternatives to remove "Jarvis suggests:" prefix for frontend
            cleaned_alternatives = []
            for alt in response:
                if alt.startswith("Jarvis suggests:"):
                    cleaned_alternatives.append(alt[16:].strip())  # Remove "Jarvis suggests:" prefix
                else:
                    cleaned_alternatives.append(alt.strip())
            
            return jsonify({
                "response": cleaned_alternatives,
                "status": "success",
                "status_type": 200,
            }), 200
        else:
            # Fallback for single response - convert to list
            return jsonify({
                "response": [response],
                "status": "success", 
                "status_type": 200,
                "alternatives_count": 1
            }), 200
        
    except Exception as e:
        return jsonify({
            "response": [f"An unexpected error occurred: {str(e)}"],
            "status": "error",
            "status_type": 500
        }), 500

@quart_app.route('/redis/health', methods=['GET'])
async def redis_health():
    """Redis health check endpoint"""
    health = redis_health_check()
    status_code = 200 if health["status"] == "healthy" else 503
    return jsonify(health), status_code

@quart_app.route('/', methods=['GET'])
async def redis_metrics():
    api = "API is running"
    return jsonify(api), 200

if __name__ == '__main__':
    quart_app.run(debug=True, host="0.0.0.0", port=8999) 