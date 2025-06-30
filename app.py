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

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
claude_api_key = os.getenv("CLAUDE_API_KEY")
grok_api_key = os.getenv("XAI_API_KEY")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

quart_app = Quart(__name__)
quart_app = cors(quart_app)

# FirstStepAI Business Configuration
TIER_ACCESS = {
    "wanderer": ["jarvis"],                           # Free
    "builder": ["jarvis", "celine"],                  # $9/month
    "architect": ["jarvis", "celine", "elonix"],      # $29/month
    "awakener": ["jarvis", "celine", "elonix", "optimus"]  # $99/month
}

RATE_LIMITS = {
    "wanderer": {"requests_per_minute": 10, "daily_limit": 50},
    "builder": {"requests_per_minute": 30, "daily_limit": 1000},
    "architect": {"requests_per_minute": 60, "daily_limit": 5000},
    "awakener": {"requests_per_minute": 100, "daily_limit": -1}  # Unlimited
}

# In-memory rate limiting storage (use Redis in production)
user_requests = {}
user_daily_counts = {}

def reset_daily_counts():
    """Reset daily counts at midnight"""
    global user_daily_counts
    user_daily_counts = {}

def check_rate_limits(user_id: str, user_tier: str) -> Dict:
    """Check if user has exceeded rate limits"""
    current_time = time.time()
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    limits = RATE_LIMITS.get(user_tier, RATE_LIMITS["wanderer"])
    
    # Initialize user data if needed
    if user_id not in user_requests:
        user_requests[user_id] = []
    if user_id not in user_daily_counts:
        user_daily_counts[user_id] = {}
    if current_date not in user_daily_counts[user_id]:
        user_daily_counts[user_id][current_date] = 0
    
    # Clean old requests (older than 1 minute)
    user_requests[user_id] = [
        req_time for req_time in user_requests[user_id] 
        if current_time - req_time < 60
    ]
    
    # Check minute limit
    minute_count = len(user_requests[user_id])
    if minute_count >= limits["requests_per_minute"]:
        return {
            "allowed": False,
            "error": "Rate limit exceeded",
            "limit_type": "per_minute",
            "limit": limits["requests_per_minute"],
            "reset_time": 60 - (current_time - min(user_requests[user_id]))
        }
    
    # Check daily limit (if not unlimited)
    if limits["daily_limit"] != -1:
        daily_count = user_daily_counts[user_id][current_date]
        if daily_count >= limits["daily_limit"]:
            return {
                "allowed": False,
                "error": "Daily limit exceeded",
                "limit_type": "daily",
                "limit": limits["daily_limit"],
                "reset_time": "tomorrow"
            }
    
    # Record the request
    user_requests[user_id].append(current_time)
    user_daily_counts[user_id][current_date] += 1
    
    return {"allowed": True}

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
        
        # Rate limiting (skip for crisis situations)
        if not crisis_detected:
            rate_check = check_rate_limits(user_id, user_tier)
            if not rate_check["allowed"]:
                return jsonify({
                    "error": rate_check["error"],
                    "limit_type": rate_check["limit_type"],
                    "limit": rate_check["limit"],
                    "reset_time": rate_check["reset_time"],
                    "upgrade_url": "https://www.firststepai.tech/upgrade",
                    "current_tier": user_tier,
                    "status": "rate_limited"
                }), 429

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

        # Store interaction data
        response_id = await store_data_supabase(
            assistant_name, model_used, response, query, user_id, task_category
        )
        
        # Prepare response with FirstStepAI context
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
            "firststep_ai": {
                "mission": "Guiding 1M entrepreneurs to success",
                "community": "FirstStepAI Entrepreneur Network",
                "upgrade_available": user_tier != "awakener"
            }
        }
        
        # Add crisis resources if detected
        if crisis_detected:
            api_response["emergency_resources"] = {
                "crisis_support": "https://www.firststepai.tech/crisis-support",
                "emergency_contact": "crisis@firststepai.com",
                "community_support": "https://www.firststepai.tech/community",
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
    """Get FirstStepAI AI Orchestra information with tier access"""
    user_tier = request.args.get('tier', 'wanderer')
    available_ais = get_available_ais(user_tier)
    
    assistants = {
        "jarvis": {
            "name": "Jarvis",
            "role": "AI CEO & Strategic Mentor",
            "model": "GPT-4o",
            "specialization": "Entrepreneurial Strategy & Crisis Support",
            "available_tiers": ["wanderer", "builder", "architect", "awakener"],
            "accessible": "jarvis" in available_ais,
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
            "available_tiers": ["builder", "architect", "awakener"],
            "accessible": "celine" in available_ais,
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
            "available_tiers": ["architect", "awakener"],
            "accessible": "elonix" in available_ais,
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
            "available_tiers": ["awakener"],
            "accessible": "optimus" in available_ais,
            "capabilities": [
                "Business process automation",
                "Technical infrastructure development",
                "Data analysis and market research",
                "AI integration and optimization",
                "Scalable solution architecture"
            ]
        }
    }
    
    return jsonify({
        "firststepai_orchestra": assistants,
        "user_tier": user_tier,
        "available_ais": available_ais,
        "mission": "Guiding 1 million entrepreneurs from idea to sustainable success",
        "upgrade_url": "https://firststepai.com/upgrade" if user_tier != "awakener" else None,
        "status": "success"
    }), 200

@quart_app.route('/health', methods=['GET'])
async def health():
    """Enhanced health check with FirstStepAI status"""
    return jsonify({
        "status": "healthy",
        "service": "FirstStepAI - AI Orchestra for Entrepreneurs",
        "mission": "Guiding 1M entrepreneurs to success",
        "ai_orchestra": {
            "jarvis": "AI CEO & Strategic Mentor",
            "celine": "Creative Strategist & Communication", 
            "elonix": "Social Intelligence & Trends",
            "optimus": "Technical Architect & Automation"
        },
        "models": ["GPT-4o", "Claude-3.5-Sonnet", "XAI Grok-3", "DeepSeek Reasoner"],
        "version": "2.0.0",
        "features": ["tier_validation", "crisis_detection", "rate_limiting", "soul_points"]
    }), 200

if __name__ == '__main__':
    quart_app.run(debug=True, host="0.0.0.0", port=8999) 