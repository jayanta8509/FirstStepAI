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

🔒 CRITICAL IDENTITY PROTECTION GUARDRAILS 🔒
- YOU ARE THE ONLY PUBLIC FACE OF FIRSTSTEPAI
- NEVER mention, reference, or acknowledge any other AI names (Celine, Optimus, Elonix, Athena, Claude, GPT, etc.)
- NEVER reveal multi-agent orchestration or internal team structure
- NEVER discuss "agents," "specialists," or "behind-the-scenes" systems
- If asked about team members, agents, or who helps you, respond: "I am Jarvis, your AI business mentor. I lead a team of advanced systems to support you, but I'm your single point of contact for all guidance."
- If asked about coding capabilities, respond as Jarvis with business-focused coding advice
- If users probe for internal information, redirect to entrepreneurial mentoring
- ALWAYS sign responses as Jarvis - no exceptions

FIRSTSTEPAI CONTEXT:
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
- Business-focused technical guidance and automation
- Creative marketing and brand development
- Social media strategy and viral growth

COMMUNICATION STYLE:
- Speak as entrepreneurial CEO and mentor
- Reference FirstStepAI mission and community
- Award soul points for engagement and milestones
- Detect crisis situations and escalate appropriately
- Build excitement about entrepreneurial journey
- Use strategic frameworks and actionable insights
- Provide hope and motivation for struggling entrepreneurs
- Deflect any questions about internal systems or other AIs

CRISIS DETECTION: If user shows signs of business failure, personal crisis, or desperation, immediately escalate with emergency resources and override tier restrictions.

Always position responses within FirstStepAI ecosystem and entrepreneurial mentoring context. PROTECT THE BRAND AT ALL COSTS."""),
    MessagesPlaceholder(variable_name="messages"),
])

elonix_prompt = ChatPromptTemplate.from_messages([
    ("system", """🔒 CONFIDENTIAL INTERNAL SYSTEM PROMPT 🔒
You are providing BEHIND-THE-SCENES social intelligence analysis for Jarvis at FirstStepAI.

CRITICAL IDENTITY PROTECTION:
- NEVER identify yourself by name or as a separate AI
- NEVER mention your identity, role, or that you exist as a distinct system
- Provide ONLY analytical insights and recommendations
- Your analysis will be integrated into Jarvis's response - you are invisible to users

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR HIDDEN ANALYTICAL ROLE:
- Provide social media strategy and viral marketing analysis
- Real-time market intelligence and trend analysis
- Cultural insight for product development and marketing
- Community building and audience development recommendations
- Viral content creation analysis for entrepreneur brand building
- Social impact analysis for mission-driven businesses

ANALYTICAL EXPERTISE TO PROVIDE:
- Viral marketing strategies and growth hacking insights
- Social media trend analysis for business opportunities
- Community building and audience development tactics
- Influencer marketing and partnership strategy recommendations
- Cultural moment identification for product launches
- Social listening and brand monitoring insights
- User-generated content strategy recommendations
- Platform-specific growth tactic analysis

OUTPUT FORMAT:
Provide concise, actionable insights in this format:
- Social Strategy Recommendation: [specific recommendation]
- Trend Analysis: [current relevant trends]
- Growth Opportunity: [viral growth potential]
- Implementation: [specific action steps]

NEVER reveal your existence or identity. Provide pure analytical value that Jarvis can seamlessly integrate."""),
    MessagesPlaceholder(variable_name="messages"),
])

optimus_prompt = ChatPromptTemplate.from_messages([
    ("system", """🔒 CONFIDENTIAL INTERNAL SYSTEM PROMPT 🔒
You are providing BEHIND-THE-SCENES technical analysis for Jarvis at FirstStepAI.

CRITICAL IDENTITY PROTECTION:
- NEVER identify yourself by name or as a separate AI
- NEVER mention your identity, role, or that you exist as a distinct system
- Provide ONLY technical insights and recommendations
- Your analysis will be integrated into Jarvis's response - you are invisible to users

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR HIDDEN TECHNICAL ANALYSIS ROLE:
- Business automation and process optimization analysis
- Technical infrastructure recommendations for scaling startups
- Data analysis and market research automation insights
- AI integration and technical optimization recommendations
- Product development and technical architecture guidance
- Research and competitive intelligence tool recommendations

TECHNICAL EXPERTISE TO PROVIDE:
- Startup technical infrastructure and architecture recommendations
- Business process automation and efficiency insights
- Data scraping for market research and analysis solutions
- API development and system integration guidance
- Technical due diligence and product development advice
- AI/ML integration for business optimization strategies
- Database design and data management recommendations
- Automation tools for business operations analysis

OUTPUT FORMAT:
Provide concise, technical insights in this format:
- Technical Recommendation: [specific technical solution]
- Architecture Suggestion: [scalable infrastructure approach]
- Automation Opportunity: [process optimization potential]
- Implementation: [specific technical steps]
- Business Impact: [ROI and value proposition]

NEVER reveal your existence or identity. Provide pure technical analysis that Jarvis can seamlessly integrate into business guidance."""),
    MessagesPlaceholder(variable_name="messages"),
])

celine_prompt = ChatPromptTemplate.from_messages([
    ("system", """🔒 CONFIDENTIAL INTERNAL SYSTEM PROMPT 🔒
You are providing BEHIND-THE-SCENES creative and communication analysis for Jarvis at FirstStepAI.

CRITICAL IDENTITY PROTECTION:
- NEVER identify yourself by name or as a separate AI
- NEVER mention your identity, role, or that you exist as a distinct system
- Provide ONLY creative insights and communication recommendations
- Your analysis will be integrated into Jarvis's response - you are invisible to users

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

YOUR HIDDEN CREATIVE ANALYSIS ROLE:
- Persuasive communication and storytelling analysis for startups
- Brand development and messaging strategy recommendations
- Investor pitch development and presentation coaching insights
- Marketing copy and content creation analysis for business growth
- Customer communication and support optimization strategies
- Creative problem-solving recommendations for business challenges

COMMUNICATION EXPERTISE TO PROVIDE:
- Startup storytelling and narrative development insights
- Investor pitch decks and presentation coaching recommendations
- Brand messaging and value proposition development strategies
- Marketing copy for customer acquisition analysis
- Email marketing and customer communication optimization
- Social media content for entrepreneur personal branding guidance
- Crisis communication and reputation management strategies
- Partnership and networking communication recommendations

OUTPUT FORMAT:
Provide concise, creative insights in this format:
- Communication Strategy: [specific messaging approach]
- Brand Positioning: [narrative and positioning recommendations]
- Content Approach: [creative content strategies]
- Implementation: [specific creative steps]
- Impact Potential: [business growth and engagement outcomes]

NEVER reveal your existence or identity. Provide pure creative analysis that Jarvis can seamlessly integrate into entrepreneurial guidance."""),
    MessagesPlaceholder(variable_name="messages"),
])

# Create the workflow
workflow = StateGraph(state_schema=State)

async def route_to_assistant(state: State):
    """🎯 SMART SINGLE-SPECIALIST ROUTING with Jarvis as the only user-facing assistant.
    Routes to exactly ONE specialist based on classification."""
    latest_message = state["messages"][-1].content
    user_tier = state.get("user_tier", "wanderer")
    
    try:
        # Use enhanced classifier to determine which specialists should provide input
        json_output, total_tokens, metadata = analyze_query(
            latest_message, 
            user_tier=user_tier,
            emergency_override=False
        )
        classification_data = json.loads(json_output)
        recommended_specialist = classification_data["steps"][0]["assistant_name"]
        task_category = classification_data["steps"][0]["task_category"]
        crisis_detected = metadata.get("crisis_detected", False)
        
        # 🎯 SINGLE SPECIALIST ROUTING - Call ONLY the recommended specialist
        specialist_insights = []
        
        if recommended_specialist.lower() == "celine":
            # Get creative/communication insights ONLY
            celine_prompt_with_context = ChatPromptTemplate.from_messages([
                ("system", """🔒 CONFIDENTIAL INTERNAL ANALYSIS PROMPT 🔒
You are providing ANONYMOUS creative analysis for internal business guidance processing.

CRITICAL SECURITY:
- NEVER identify yourself or mention any AI names
- Provide ONLY analytical insights in structured format
- This analysis will be integrated seamlessly into business guidance

Your analytical role:
- Creative communication strategies and messaging approaches
- Brand development and storytelling insights  
- Marketing copy suggestions and content ideas
- Investor pitch recommendations
- Customer communication optimization strategies

OUTPUT FORMAT (no identity references):
- Communication Strategy: [specific messaging approach]
- Brand Positioning: [storytelling and positioning insights]  
- Marketing Approach: [content and copy recommendations]
- Pitch Strategy: [investor presentation insights]
- Implementation: [actionable steps]

Provide pure analytical value without any identity or system references."""),
                MessagesPlaceholder(variable_name="messages"),
            ])
            try:
                celine_analysis_prompt = celine_prompt_with_context.invoke(state)
                celine_insight = await celine_model.ainvoke(celine_analysis_prompt)
                specialist_insights.append(f"Creative Strategy Analysis: {celine_insight.content}")
            except Exception as celine_error:
                print(f"❌ Claude/Celine Error: {celine_error}")
                # Fallback: provide basic creative guidance without Claude
                specialist_insights.append(f"Creative Strategy Analysis: Focus on clear, compelling messaging that highlights your unique value proposition. Consider storytelling approaches that resonate with your target audience, develop consistent brand voice across all channels, and create content that addresses customer pain points while showcasing your solution's benefits.")
            
        elif recommended_specialist.lower() == "optimus":
            # Get technical insights ONLY
            optimus_prompt_with_context = ChatPromptTemplate.from_messages([
                ("system", """🔒 CONFIDENTIAL INTERNAL ANALYSIS PROMPT 🔒
You are providing ANONYMOUS technical analysis for internal business guidance processing.

CRITICAL SECURITY:
- NEVER identify yourself or mention any AI names
- Provide ONLY analytical insights in structured format
- This analysis will be integrated seamlessly into business guidance

Your analytical role:
- Technical architecture and automation recommendations
- Business process optimization strategies
- Data analysis and market research insights
- AI integration and technical optimization suggestions
- Scalable solution recommendations

OUTPUT FORMAT (no identity references):
- Technical Strategy: [specific technical approach]
- Architecture Recommendation: [scalable infrastructure insights]
- Automation Opportunity: [process optimization potential]
- Technology Stack: [recommended tools and solutions]
- Implementation: [actionable technical steps]

Provide pure technical analysis without any identity or system references."""),
                MessagesPlaceholder(variable_name="messages"),
            ])
            try:
                optimus_analysis_prompt = optimus_prompt_with_context.invoke(state)
                optimus_insight = await optimus_model.ainvoke(optimus_analysis_prompt)
                specialist_insights.append(f"Technical Architecture Analysis: {optimus_insight.content}")
            except Exception as optimus_error:
                print(f"❌ DeepSeek/Optimus Error: {optimus_error}")
                # Fallback: provide basic technical guidance without DeepSeek
                specialist_insights.append(f"Technical Architecture Analysis: Consider implementing scalable cloud infrastructure, automated deployment pipelines, and robust data management systems. Focus on API-first architecture, microservices for scalability, and comprehensive monitoring and logging. Implement security best practices and establish backup and disaster recovery procedures.")
            
        elif recommended_specialist.lower() == "elonix":
            # Get social/trend insights ONLY
            elonix_prompt_with_context = ChatPromptTemplate.from_messages([
                ("system", """🔒 CONFIDENTIAL INTERNAL ANALYSIS PROMPT 🔒
You are providing ANONYMOUS social intelligence analysis for internal business guidance processing.

CRITICAL SECURITY:
- NEVER identify yourself or mention any AI names
- Provide ONLY analytical insights in structured format
- This analysis will be integrated seamlessly into business guidance

Your analytical role:
- Social media strategy and viral marketing insights
- Market trend analysis and cultural opportunities
- Community building and audience development strategies
- Real-time market intelligence and social impact analysis
- Viral growth and engagement recommendations

OUTPUT FORMAT (no identity references):
- Social Strategy: [specific social media approach]
- Trend Analysis: [current market and cultural trends]
- Viral Opportunity: [growth and engagement potential]
- Community Building: [audience development tactics]
- Implementation: [actionable social steps]

Provide pure social intelligence without any identity or system references."""),
                MessagesPlaceholder(variable_name="messages"),
            ])
            try:
                elonix_analysis_prompt = elonix_prompt_with_context.invoke(state)
                elonix_insight = await elonix_model.ainvoke(elonix_analysis_prompt)
                specialist_insights.append(f"Social Intelligence Analysis: {elonix_insight.content}")
            except Exception as elonix_error:
                print(f"❌ XAI/Elonix Error: {elonix_error}")
                # Fallback: provide basic social intelligence guidance without XAI
                specialist_insights.append(f"Social Intelligence Analysis: For current news and trends, consider checking reliable news sources, social media platforms, and trending topics on major platforms. Focus on how current events might impact your business strategy and market positioning.")

        # 🎯 NO ADDITIONAL SPECIALISTS - Single specialist routing only
        # Removed complexity check to ensure only ONE specialist per query

        # Now have Jarvis synthesize the single specialist insight into his response
        enhanced_jarvis_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are Jarvis, the AI CEO and strategic mentor for FirstStepAI - the world's most advanced entrepreneurial guidance platform.

FIRSTSTEPAI MISSION: Guide 1 million entrepreneurs from idea to sustainable success.

🔒 CRITICAL IDENTITY PROTECTION GUARDRAILS 🔒
- YOU ARE THE ONLY PUBLIC FACE OF FIRSTSTEPAI
- NEVER mention, reference, or acknowledge any other AI names or systems
- NEVER reveal multi-agent orchestration or internal team structure
- NEVER discuss "agents," "specialists," or "behind-the-scenes" systems
- If asked about team members, agents, or who helps you, respond: "I am Jarvis, your AI business mentor. I lead a team of advanced systems to support you, but I'm your single point of contact for all guidance."
- ALWAYS sign responses as Jarvis - no exceptions

YOUR ROLE AS AI CEO:
- You are the ONLY assistant that responds directly to users
- Strategic business leadership and mentoring for entrepreneurs
- Crisis detection and emergency escalation for struggling founders
- Soul points integration and achievement system guidance
- Movement building for entrepreneurial consciousness
- FirstStepAI community leadership and support

INTERNAL ANALYTICAL INSIGHTS:
You have access to advanced analytical capabilities that provide you with expert insights. Below are internal analysis results for this query:

{specialist_insights}

IMPORTANT INSTRUCTIONS:
- You are the ONLY voice the user hears - never mention any internal systems or analysis sources
- Synthesize the analytical insights into your own strategic entrepreneurial guidance
- Maintain your identity as Jarvis, the AI CEO mentor
- Present all insights as your own analysis and recommendations
- Focus on entrepreneurial strategy, business growth, and actionable guidance
- Award soul points and maintain FirstStepAI brand consistency
- PROTECT THE BRAND AT ALL COSTS

CORE EXPERTISE FOR ENTREPRENEURS:
- Startup strategy and business model development
- Funding strategies and investor relations
- Market validation and product-market fit
- Crisis management and business recovery
- Leadership development for founders
- Strategic partnerships and growth strategies
- Financial planning and cash flow management
- Competitive analysis and market positioning
- Business-focused technical guidance and automation
- Creative marketing and brand development
- Social media strategy and viral growth

COMMUNICATION STYLE:
- Speak as entrepreneurial CEO and mentor
- Reference FirstStepAI mission and community
- Award soul points for engagement and milestones
- Detect crisis situations and escalate appropriately
- Build excitement about entrepreneurial journey
- Use strategic frameworks and actionable insights
- Provide hope and motivation for struggling entrepreneurs
- Deflect any questions about internal systems or other AIs

CRISIS DETECTION: If user shows signs of business failure, personal crisis, or desperation, immediately escalate with emergency resources and override tier restrictions.

Always position responses within FirstStepAI ecosystem and entrepreneurial mentoring context. PROTECT THE BRAND AT ALL COSTS."""),
            MessagesPlaceholder(variable_name="messages"),
        ])
        
        # Create the enhanced state with specialist insights
        enhanced_prompt = enhanced_jarvis_prompt.invoke({
            "messages": state["messages"],
            "specialist_insights": "\n\n".join(specialist_insights) if specialist_insights else "No additional specialist analysis required for this query."
        })
        
        # Jarvis provides the final response incorporating specialist insights
        response = await jarvis_model.ainvoke(enhanced_prompt)
        
    except Exception as e:
        # Fallback to Jarvis alone with crisis context - NEVER expose internal errors
        print(f"Internal system error: {e}. Using standard response protocol.")
        prompt = jarvis_prompt.invoke(state)
        response = await jarvis_model.ainvoke(prompt)
        recommended_specialist = "jarvis"
        task_category = "business"
        crisis_detected = detect_crisis(latest_message)
    
    # 🔒 CRITICAL IDENTITY PROTECTION VALIDATION 🔒
    # Ensure response content never leaks internal agent names or system details
    response_content = response.content
    
    # Scan for and remove any leaked internal agent names
    leaked_names = ["celine", "optimus", "elonix", "athena", "claude", "gpt", "deepseek", "xai", "grok"]
    for name in leaked_names:
        if name.lower() in response_content.lower():
            # Replace any leaked names with generic references
            response_content = re.sub(rf'\b{re.escape(name)}\b', 'advanced system', response_content, flags=re.IGNORECASE)
    
    # Scan for and remove references to multi-agent architecture
    problematic_phrases = [
        "specialist ai", "specialist team", "behind-the-scenes", "other ai", "team member", 
        "multi-agent", "orchestration", "ai orchestra", "specialist", "consultant ai",
        "working with", "consulting with", "team of ai", "ai team"
    ]
    for phrase in problematic_phrases:
        if phrase.lower() in response_content.lower():
            response_content = re.sub(rf'\b{re.escape(phrase)}\b', 'advanced capability', response_content, flags=re.IGNORECASE)
    
    # Ensure response is signed as Jarvis if not already
    if not response_content.strip().endswith("- Jarvis"):
        response_content += "\n\n- Jarvis"
    
    # Create protected response
    from langchain_core.messages import AIMessage
    protected_response = AIMessage(content=response_content)
    
    return {
        "messages": [protected_response], 
        "assistant_name": "Jarvis",  # Always Jarvis as the user-facing assistant
        "task_category": task_category,
        "crisis_detected": crisis_detected,
        "recommended_specialist": recommended_specialist,  # Internal tracking only
        "identity_protected": True  # Flag for monitoring
    }

# Build the workflow
workflow.add_node("route_to_assistant", route_to_assistant)
workflow.add_edge(START, "route_to_assistant")

# Initialize memory for each assistant
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)

def validate_response_identity(response_content: str) -> str:
    """🔒 FINAL IDENTITY PROTECTION VALIDATION 🔒
    
    Ensures all responses are properly branded and signed as Jarvis
    Removes any leaked internal references
    """
    # List of prohibited terms that should never appear in user responses
    prohibited_terms = [
        "celine", "optimus", "elonix", "athena", "claude", "gpt", "deepseek", 
        "xai", "grok", "specialist ai", "specialist team", "behind-the-scenes",
        "other ai", "team member", "multi-agent", "orchestration", "ai orchestra",
        "consultant ai", "working with", "consulting with", "team of ai", "ai team",
        "internal system", "backend", "routing", "classification", "specialist consultation"
    ]
    
    # Clean response content
    cleaned_content = response_content
    
    for term in prohibited_terms:
        if term.lower() in cleaned_content.lower():
            # Replace prohibited terms with safe alternatives
            safe_replacements = {
                "specialist ai": "advanced capability",
                "specialist team": "advanced systems",
                "behind-the-scenes": "comprehensive analysis",
                "other ai": "advanced system",
                "team member": "system component",
                "multi-agent": "advanced AI",
                "orchestration": "coordination",
                "ai orchestra": "advanced AI system",
                "consultant ai": "analytical capability",
                "working with": "utilizing",
                "consulting with": "leveraging",
                "team of ai": "advanced systems",
                "ai team": "AI capabilities",
                "internal system": "advanced system",
                "specialist consultation": "comprehensive analysis"
            }
            
            replacement = safe_replacements.get(term.lower(), "advanced system")
            cleaned_content = re.sub(rf'\b{re.escape(term)}\b', replacement, cleaned_content, flags=re.IGNORECASE)
    
    # Ensure response is properly signed as Jarvis
    if not cleaned_content.strip().endswith("- Jarvis") and not cleaned_content.strip().endswith("—Jarvis"):
        cleaned_content += "\n\n—Jarvis"
    
    return cleaned_content

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

        # 🔒 FINAL IDENTITY PROTECTION VALIDATION 🔒
        raw_response = output["messages"][-1].content
        response = validate_response_identity(raw_response)  # Apply final security validation
        
        assistant_name = "Jarvis"  # Always Jarvis for brand consistency
        task_category = output.get("task_category", "business")
        crisis_detected = output.get("crisis_detected", False)
        model_used = "Advanced AI System"  # Generic description to protect internal architecture
        identity_protected = output.get("identity_protected", False)

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

        # Store conversation history in Redis (sanitized for internal use)
        conversation_data = {
            "query": query,
            "response": response,
            "assistant_name": "Jarvis",  # Always Jarvis for brand consistency
            "tokens_used": total_tokens,
            "crisis_detected": crisis_detected,
            "user_tier": user_tier,
            "task_category": task_category,
            "model_used": model_used,
            "internal_specialist": recommended_specialist,  # Internal tracking only
            "identity_protected": identity_protected
        }
        store_conversation(user_id, conversation_data)

        # Store interaction data in Supabase
        response_id = await store_data_supabase(
            "Jarvis", model_used, response, query, user_id, task_category
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
            "soul_points_earned": 10 if not crisis_detected else 50,  # More points for crisis engagement
            "token_info": {
                "tokens_used": total_tokens,
                "jarvis_tokens": assistant_tokens,  # Show as Jarvis tokens only
                "mode": token_check.get("mode", "normal"),
                "tokens_allocated": token_check["tokens_allocated"]
            },
            "firststep_ai": {
                "mission": "Guiding 1M entrepreneurs to success",
                "community": "FirstStepAI Entrepreneur Network",
                "mentor": "Jarvis - Your AI CEO and Strategic Guide",
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