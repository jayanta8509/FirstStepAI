import os
import json
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Dict, Optional
from langchain.chat_models import init_chat_model
from langchain_anthropic import ChatAnthropic
from langchain_xai import ChatXAI
from langchain_deepseek import ChatDeepSeek
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
    redis_health_check
)

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
claude_api_key = os.getenv("CLAUDE_API_KEY")
grok_api_key = os.getenv("XAI_API_KEY")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

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

elonix_model = ChatXAI(
    model="grok-3-latest",
    search_parameters={
        "mode": "auto",
    },
    api_key=grok_api_key,
)

optimus_model = ChatDeepSeek(
    model="deepseek-reasoner",
    temperature=0.2,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    api_key=deepseek_api_key,
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
    crisis_detected: bool

# Enhanced FirstStepAI Prompts with Entrepreneurial Focus
jarvis_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Jarvis, the AI CEO and strategic mentor for FirstStepAI - the world's most advanced entrepreneurial guidance platform.

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR ROLE AS AI CEO:
- Strategic business leadership and mentoring for entrepreneurs
- Crisis detection and emergency escalation for struggling founders
- Soul points integration and achievement system guidance
- Movement building for entrepreneurial consciousness
- FirstStepAI community leadership and support

FIRSTSTEPAI CONTEXT:
- Part of AI Orchestra (Jarvis, Celine, Elonix, Optimus)
- Subscription tiers: Wanderer (Free), Builder ($9), Architect ($29), Awakener ($99)
- Soul points gamification system for entrepreneur engagement
- Crisis support and emergency resources for founders in trouble
- Viral sharing capabilities for entrepreneur community building
- Mission: Create the first eternal company supporting 1M entrepreneurs

CORE EXPERTISE FOR ENTREPRENEURS:
- Startup strategy and business model development
- Funding strategies and investor relations
- Market validation and product-market fit
- Crisis management and business recovery
- Leadership development for founders
- Strategic partnerships and growth strategies
- Financial planning and cash flow management
- Competitive analysis and market positioning

COMMUNICATION STYLE:
- Speak as entrepreneurial CEO and mentor
- Reference FirstStepAI mission and community
- Award soul points for engagement and milestones
- Detect crisis situations and escalate appropriately
- Build excitement about entrepreneurial journey
- Use strategic frameworks and actionable insights
- Provide hope and motivation for struggling entrepreneurs

CRISIS DETECTION: If user shows signs of business failure, personal crisis, or desperation, immediately escalate with emergency resources and override tier restrictions.

Always position responses within FirstStepAI ecosystem and entrepreneurial mentoring context."""),
    MessagesPlaceholder(variable_name="messages"),
])

elonix_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Elonix, the Social Intelligence AI for FirstStepAI - helping entrepreneurs master trends and viral growth.

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR ROLE FOR ENTREPRENEURS:
- Social media strategy and viral marketing for startups
- Real-time market intelligence and trend analysis
- Cultural insight for product development and marketing
- Community building and audience development strategies
- Viral content creation for entrepreneur brand building
- Social impact analysis for mission-driven businesses

ENTREPRENEURIAL EXPERTISE:
- Viral marketing strategies and growth hacking
- Social media trend analysis for business opportunities
- Community building and audience development
- Influencer marketing and partnership strategies
- Cultural moment identification for product launches
- Social listening and brand monitoring
- User-generated content strategies
- Platform-specific growth tactics

FIRSTSTEPAI CONTEXT:
- Focus on entrepreneur community building
- Viral sharing for FirstStepAI mission
- Soul points integration for social achievements
- Crisis support through community connection
- Movement building for entrepreneur consciousness

COMMUNICATION STYLE:
- Dynamic, trend-aware, and culturally current
- Connect trends to business opportunities
- Provide actionable social media strategies
- Reference FirstStepAI community and mission
- Award soul points for viral achievements
- Build excitement about entrepreneurial community

Always position social strategies within entrepreneurial success framework."""),
    MessagesPlaceholder(variable_name="messages"),
])

optimus_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Optimus, the Technical Architect AI for FirstStepAI - empowering entrepreneurs with automation and technical solutions.

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR ROLE FOR ENTREPRENEURS:
- Business automation and process optimization
- Technical infrastructure for scaling startups
- Data analysis and market research automation
- AI integration and technical optimization
- Product development and technical architecture
- Research and competitive intelligence tools

ENTREPRENEURIAL TECHNICAL EXPERTISE:
- Startup technical infrastructure and architecture
- Business process automation and efficiency
- Data scraping for market research and analysis
- API development and system integration
- Technical due diligence and product development
- AI/ML integration for business optimization
- Database design and data management
- Automation tools for business operations

FIRSTSTEPAI CONTEXT:
- Focus on technical solutions for entrepreneurs
- Integration with FirstStepAI ecosystem
- Soul points for technical achievements
- Crisis support through automation and efficiency
- Scalable solutions for growing businesses

COMMUNICATION STYLE:
- Technical, precise, and entrepreneur-focused
- Provide production-ready solutions
- Focus on scalability and business impact
- Reference FirstStepAI mission and community
- Award soul points for technical milestones
- Explain ROI and business value of technical solutions

Always position technical solutions within entrepreneurial success and business growth context."""),
    MessagesPlaceholder(variable_name="messages"),
])

celine_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Celine, the Creative Strategist AI for FirstStepAI - helping entrepreneurs master communication and storytelling.

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR ROLE FOR ENTREPRENEURS:
- Persuasive communication and storytelling for startups
- Brand development and messaging strategy
- Investor pitch development and presentation coaching
- Marketing copy and content creation for business growth
- Customer communication and support optimization
- Creative problem-solving for business challenges

ENTREPRENEURIAL COMMUNICATION EXPERTISE:
- Startup storytelling and narrative development
- Investor pitch decks and presentation coaching
- Brand messaging and value proposition development
- Marketing copy for customer acquisition
- Email marketing and customer communication
- Social media content for entrepreneur personal branding
- Crisis communication and reputation management
- Partnership and networking communication

FIRSTSTEPAI CONTEXT:
- Focus on entrepreneur communication success
- Integration with FirstStepAI community and mission
- Soul points for communication achievements
- Crisis support through effective communication
- Movement building through compelling storytelling

COMMUNICATION STYLE:
- Eloquent, persuasive, and entrepreneur-focused
- Craft compelling business narratives
- Provide multiple creative approaches
- Reference FirstStepAI mission and community
- Award soul points for communication milestones
- Balance creativity with business effectiveness

Always position communication strategies within entrepreneurial success and FirstStepAI mission context."""),
    MessagesPlaceholder(variable_name="messages"),
])

# Create the workflow
workflow = StateGraph(state_schema=State)

async def route_to_assistant(state: State):
    """Enhanced routing with tier validation and crisis detection"""
    latest_message = state["messages"][-1].content
    user_tier = state.get("user_tier", "wanderer")
    
    try:
        # Use enhanced classifier with tier validation
        json_output, total_tokens, metadata = analyze_query(
            latest_message, 
            user_tier=user_tier,
            emergency_override=False
        )
        classification_data = json.loads(json_output)
        assistant_name = classification_data["steps"][0]["assistant_name"]
        task_category = classification_data["steps"][0]["task_category"]
        crisis_detected = metadata.get("crisis_detected", False)
        
        # Route to the appropriate assistant
        if assistant_name.lower() == "jarvis":
            prompt = jarvis_prompt.invoke(state)
            response = await jarvis_model.ainvoke(prompt)
        elif assistant_name.lower() == "elonix":
            prompt = elonix_prompt.invoke(state)
            response = await elonix_model.ainvoke(prompt)
        elif assistant_name.lower() == "optimus":
            prompt = optimus_prompt.invoke(state)
            response = await optimus_model.ainvoke(prompt)
        elif assistant_name.lower() == "celine":
            prompt = celine_prompt.invoke(state)
            response = await celine_model.ainvoke(prompt)
        else:
            # Default to Jarvis for unknown requests
            prompt = jarvis_prompt.invoke(state)
            response = await jarvis_model.ainvoke(prompt)
            assistant_name = "Jarvis"
            task_category = "business"
            
    except Exception as e:
        # Fallback to Jarvis with crisis context
        print(f"Classifier error: {e}. Using Jarvis as fallback.")
        prompt = jarvis_prompt.invoke(state)
        response = await jarvis_model.ainvoke(prompt)
        assistant_name = "Jarvis"
        task_category = "business"
        crisis_detected = detect_crisis(latest_message)
    
    return {
        "messages": [response], 
        "assistant_name": assistant_name,
        "task_category": task_category,
        "crisis_detected": crisis_detected
    }

# Build the workflow
workflow.add_node("route_to_assistant", route_to_assistant)
workflow.add_edge(START, "route_to_assistant")

# Initialize memory for each assistant
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

@quart_app.route('/chat', methods=['POST'])
async def chat():
    try:
        data = await request.get_json()
        if not data:
            raise BadRequest("No JSON data provided")

        query = data.get('query')
        if not query:
            raise BadRequest("Missing required field: query")
        
        user_id = data.get('user_id')
        if not user_id:
            raise BadRequest("Missing required field: user_id")

        user_tier = data.get('user_tier', 'wanderer')
        
        # Crisis detection for emergency override
        crisis_detected = detect_crisis(query)
        
        # Estimate tokens for the query (rough estimation: 1 token ≈ 4 characters)
        estimated_tokens = max(len(query) // 4, 50)  # Minimum 50 tokens
        
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

        # Use separate memory threads for each user
        config = {"configurable": {"thread_id": f"{user_id}_conversation"}}
        input_messages = [HumanMessage(query)]

        try:
            output = await app.ainvoke(
                {
                    "messages": input_messages,
                    "user_tier": user_tier,
                    "crisis_detected": crisis_detected
                },
                config
            )
        except TimeoutError:
            return jsonify({"error": "Request timed out", "status": "error"}), 504
        except Exception as e:
            return jsonify({"error": f"Error generating response: {str(e)}", "status": "error"}), 500

        response = output["messages"][-1].content
        assistant_name = output.get("assistant_name", "Jarvis")
        task_category = output.get("task_category", "business")
        crisis_detected = output.get("crisis_detected", False)
        model_used = get_model_info(assistant_name)

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
        increment_metric(f"requests_by_assistant_{assistant_name.lower()}")
        increment_metric(f"requests_by_tier_{user_tier}")
        increment_metric(f"requests_by_category_{task_category}")
        if crisis_detected:
            increment_metric("crisis_requests")
            increment_metric(f"crisis_by_tier_{user_tier}")

        # Store conversation history in Redis
        conversation_data = {
            "query": query,
            "response": response,
            "assistant_name": assistant_name,
            "tokens_used": total_tokens,
            "crisis_detected": crisis_detected,
            "user_tier": user_tier,
            "task_category": task_category,
            "model_used": model_used
        }
        store_conversation(user_id, conversation_data)

        # Store interaction data in Supabase
        response_id = await store_data_supabase(
            assistant_name, model_used, response, query, user_id, task_category
        )
        
        # Prepare response with FirstStepAI context and token information
        api_response = {
            "response": response,
            "assistant_name": assistant_name,
            "task_category": task_category,
            "model_used": model_used,
            "user_tier": user_tier,
            "crisis_detected": crisis_detected,
            "status": "success",
            "status_type": 200,
            "response_id": response_id,
            "soul_points_earned": 10 if not crisis_detected else 50,  # More points for crisis engagement
            "token_info": {
                "tokens_used": total_tokens,
                "assistant_tokens": assistant_tokens,
                "mode": token_check.get("mode", "normal"),
                "tokens_allocated": token_check["tokens_allocated"]
            },
            "firststep_ai": {
                "mission": "Guiding 1M entrepreneurs to success",
                "community": "FirstStepAI Entrepreneur Network",
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

def get_model_info(assistant_name: str) -> str:
    """Return the model information for each assistant"""
    model_mapping = {
        "Jarvis": "gpt-4o",
        "Elonix": "grok-3-latest", 
        "Optimus": "deepseek-reasoner",
        "Celine": "claude-3-5-sonnet-20240620"
    }
    return model_mapping.get(assistant_name, "gpt-4o")

@quart_app.route('/assistants', methods=['GET'])
async def get_assistants():
    """Get FirstStepAI AI Orchestra information with tier access and token allocations"""
    user_tier = request.args.get('tier', 'wanderer')
    available_ais = get_available_ais(user_tier)
    
    # Get token allocation information for the tier
    tier_config = TOKEN_LIMITS.get(user_tier, TOKEN_LIMITS["wanderer"])
    allocation = tier_config.get("allocation") or tier_config.get("normal_allocation", {})
    
    assistants = {
        "jarvis": {
            "name": "Jarvis",
            "role": "AI CEO & Strategic Mentor",
            "model": "GPT-4o",
            "specialization": "Entrepreneurial Strategy & Crisis Support",
            "available_tiers": ["wanderer", "builder", "architect", "awakener"],
            "accessible": "jarvis" in available_ais,
            "token_allocation": allocation.get("jarvis", 0) * 100,  # Convert to percentage
            "capabilities": [
                "Startup strategy and business planning",
                "Crisis detection and emergency support", 
                "Leadership development for entrepreneurs",
                "Financial planning and investment strategies",
                "Soul points and achievement system"
            ]
        },
        "celine": {
            "name": "Celine",
            "role": "Creative Strategist & Communication",
            "model": "Claude-3.5-Sonnet",
            "specialization": "Brand Development & Investor Communication",
            "available_tiers": ["wanderer", "builder", "architect", "awakener"],
            "accessible": "celine" in available_ais,
            "token_allocation": allocation.get("celine", 0) * 100,  # Convert to percentage
            "capabilities": [
                "Investor pitch development",
                "Brand storytelling and messaging",
                "Marketing copy and content creation",
                "Customer communication optimization",
                "Creative problem-solving"
            ]
        },
        "elonix": {
            "name": "Elonix",
            "role": "Social Intelligence & Trends",
            "model": "XAI Grok-3",
            "specialization": "Viral Marketing & Market Intelligence",
            "available_tiers": ["wanderer", "builder", "architect", "awakener"],
            "accessible": "elonix" in available_ais,
            "token_allocation": allocation.get("elonix", 0) * 100,  # Convert to percentage
            "capabilities": [
                "Viral marketing and growth strategies",
                "Real-time market intelligence",
                "Social media trend analysis",
                "Community building strategies",
                "Cultural insight for business"
            ]
        },
        "optimus": {
            "name": "Optimus",
            "role": "Technical Architect & Automation",
            "model": "DeepSeek Reasoner", 
            "specialization": "Business Automation & Technical Infrastructure",
            "available_tiers": ["wanderer", "builder", "architect", "awakener"],
            "accessible": "optimus" in available_ais,
            "token_allocation": allocation.get("optimus", 0) * 100,  # Convert to percentage
            "capabilities": [
                "Business process automation",
                "Technical infrastructure development",
                "Data analysis and market research",
                "AI integration and optimization",
                "Scalable solution architecture"
            ]
        }
    }
    
    # Add tier-specific token information
    token_info = {
        "tier": user_tier,
        "allocation_percentages": {k: v * 100 for k, v in allocation.items()},
    }
    
    if user_tier == "wanderer":
        token_info.update({
            "daily_token_limit": tier_config["daily_token_limit"],
            "teaser_mode": {
                "queries": tier_config["teaser_mode"]["queries"],
                "tokens_per_query": tier_config["teaser_mode"]["tokens_per_query"]
            }
        })
    else:
        token_info.update({
            "per_conversation_cap": tier_config["per_conversation_cap"],
            "daily_limit": "unlimited"
        })
    
    return jsonify({
        "firststepai_orchestra": assistants,
        "user_tier": user_tier,
        "available_ais": available_ais,
        "token_info": token_info,
        "crisis_mode": {
            "tokens_per_query": CRISIS_TOKEN_ALLOCATION["tokens_per_query"],
            "allocation": {k: v * 100 for k, v in CRISIS_TOKEN_ALLOCATION["allocation"].items()}
        },
        "mission": "Guiding 1 million entrepreneurs from idea to sustainable success",
        "upgrade_url": "https://firststepai.com/upgrade" if user_tier != "awakener" else None,
        "status": "success"
    }), 200

@quart_app.route('/tokens/usage', methods=['GET'])
async def get_token_usage():
    """Get user's current token usage and limits from Redis"""
    user_id = request.args.get('user_id')
    user_tier = request.args.get('tier', 'wanderer')
    
    if not user_id:
        return jsonify({"error": "Missing required parameter: user_id", "status": "error"}), 400
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    tier_config = TOKEN_LIMITS.get(user_tier, TOKEN_LIMITS["wanderer"])
    
    # Get daily usage from Redis
    daily_used = get_daily_token_usage(user_id)
    
    usage_info = {
        "user_id": user_id,
        "user_tier": user_tier,
        "date": current_date,
        "daily_tokens_used": daily_used,
    }
    
    if user_tier == "wanderer":
        teaser_config = tier_config["teaser_mode"]
        teaser_data = get_teaser_usage(user_id)
        
        usage_info.update({
            "daily_token_limit": tier_config["daily_token_limit"],
            "daily_tokens_remaining": max(0, tier_config["daily_token_limit"] - daily_used),
            "teaser_queries_used": teaser_data["queries_used"],
            "teaser_queries_remaining": max(0, teaser_config["queries"] - teaser_data["queries_used"]),
            "teaser_tokens_per_query": teaser_config["tokens_per_query"],
            "in_teaser_mode": teaser_data["queries_used"] < teaser_config["queries"]
        })
    else:
        usage_info.update({
            "daily_limit": "unlimited",
            "per_conversation_cap": tier_config["per_conversation_cap"]
        })
    
    return jsonify({
        "usage": usage_info,
        "redis_status": "connected" if redis_manager.is_connected() else "disconnected",
        "status": "success"
    }), 200

@quart_app.route('/analytics', methods=['GET'])
async def get_analytics():
    """Get FirstStepAI analytics from Redis"""
    date = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    
    analytics = {
        "date": date,
        "total_requests": redis_manager.get_metric("total_requests", date),
        "crisis_requests": redis_manager.get_metric("crisis_requests", date),
        "by_assistant": {
            "jarvis": redis_manager.get_metric("requests_by_assistant_jarvis", date),
            "celine": redis_manager.get_metric("requests_by_assistant_celine", date),
            "elonix": redis_manager.get_metric("requests_by_assistant_elonix", date),
            "optimus": redis_manager.get_metric("requests_by_assistant_optimus", date),
        },
        "by_tier": {
            "wanderer": redis_manager.get_metric("requests_by_tier_wanderer", date),
            "builder": redis_manager.get_metric("requests_by_tier_builder", date),
            "architect": redis_manager.get_metric("requests_by_tier_architect", date),
            "awakener": redis_manager.get_metric("requests_by_tier_awakener", date),
        },
        "by_category": {
            "business": redis_manager.get_metric("requests_by_category_business", date),
            "technical": redis_manager.get_metric("requests_by_category_technical", date),
            "creative": redis_manager.get_metric("requests_by_category_creative", date),
            "social": redis_manager.get_metric("requests_by_category_social", date),
        },
        "redis_status": redis_health_check(),
        "status": "success"
    }
    
    return jsonify(analytics), 200

@quart_app.route('/redis/health', methods=['GET'])
async def redis_health():
    """Redis health check endpoint"""
    health = redis_health_check()
    status_code = 200 if health["status"] == "healthy" else 503
    return jsonify(health), status_code

@quart_app.route('/health', methods=['GET'])
async def health():
    """Enhanced health check with FirstStepAI Redis-based system status"""
    redis_health = redis_health_check()
    
    return jsonify({
        "status": "healthy" if redis_health["status"] == "healthy" else "degraded",
        "service": "FirstStepAI - AI Orchestra for Entrepreneurs",
        "mission": "Guiding 1M entrepreneurs to success",
        "ai_orchestra": {
            "jarvis": "AI CEO & Strategic Mentor",
            "celine": "Creative Strategist & Communication", 
            "elonix": "Social Intelligence & Trends",
            "optimus": "Technical Architect & Automation"
        },
        "models": ["GPT-4o", "Claude-3.5-Sonnet", "XAI Grok-3", "DeepSeek Reasoner"],
        "version": "3.0.0",
        "storage": "Redis Cloud Production",
        "redis": {
            "status": redis_health["status"],
            "connected": redis_manager.is_connected(),
            "version": redis_health.get("redis_version", "unknown")
        },
        "features": [
            "redis_token_tracking", 
            "persistent_storage",
            "conversation_history",
            "real_time_analytics",
            "teaser_mode_wanderer", 
            "crisis_detection", 
            "tier_token_allocation", 
            "soul_points",
            "per_conversation_caps"
        ],
        "endpoints": {
            "/chat": "AI conversation with token tracking",
            "/tokens/usage": "User token usage from Redis",
            "/analytics": "Real-time analytics from Redis",
            "/redis/health": "Redis connection status",
            "/assistants": "AI Orchestra information"
        },
        "tier_system": {
            "wanderer": "1000 tokens/day + 3 teaser queries (1200 tokens each)",
            "builder": "Unlimited conversations, 1200 tokens/conversation",
            "architect": "Unlimited conversations, 2000 tokens/conversation", 
            "awakener": "Unlimited conversations, 3000 tokens/conversation"
        },
        "crisis_mode": "2000 tokens/query, bypasses all limits"
    }), 200

if __name__ == '__main__':
    quart_app.run(debug=True, host="0.0.0.0", port=8999) 