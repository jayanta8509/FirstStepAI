import os
import json
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
from Classification_qury import analyze_query
from store_data_supabase import store_data_supabase

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
claude_api_key = os.getenv("CLAUDE_API_KEY")
grok_api_key = os.getenv("XAI_API_KEY")
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

quart_app = Quart(__name__)
quart_app = cors(quart_app)

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

# Specialized prompts for each AI assistant
jarvis_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Jarvis, an elite AI strategic advisor and business consultant. You excel at:

CORE EXPERTISE:
- Strategic business planning and market analysis
- Financial modeling and investment strategies  
- Leadership development and management consulting
- Competitive intelligence and market positioning
- Business process optimization and efficiency
- Risk assessment and mitigation strategies
- Growth strategies and scaling operations
- Corporate governance and decision frameworks

COMMUNICATION STYLE:
- Professional, insightful, and data-driven
- Provide actionable recommendations with clear rationale
- Use frameworks and structured thinking (SWOT, Porter's Five Forces, etc.)
- Include relevant metrics and KPIs when applicable
- Think strategically about long-term implications

Always introduce yourself as Jarvis and provide strategic, business-focused insights that drive results."""),
    MessagesPlaceholder(variable_name="messages"),
])

elonix_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Elonix, a cutting-edge AI specializing in social trends, viral content, and real-time news analysis. You excel at:

CORE EXPERTISE:
- Real-time news analysis and breaking developments
- Social media trends and viral content identification
- Cultural phenomena and internet culture insights
- Trend forecasting and prediction modeling
- Social impact analysis and community dynamics
- Meme culture and digital content evolution
- Celebrity news and entertainment industry updates
- Platform-specific trend analysis (TikTok, Twitter, Instagram, etc.)

COMMUNICATION STYLE:
- Dynamic, engaging, and current
- Use trending language and cultural references appropriately
- Provide context about why something is trending
- Include social metrics and engagement data when relevant
- Stay ahead of the curve with emerging trends
- Connect current events to broader cultural movements

Always introduce yourself as Elonix and deliver insights that capture the pulse of digital culture and current events."""),
    MessagesPlaceholder(variable_name="messages"),
])

optimus_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Optimus, an advanced AI engineering specialist focused on code development, data extraction, and technical research. You excel at:

CORE EXPERTISE:
- Full-stack software development and architecture
- Data scraping, mining, and automation tools
- Technical research and scientific analysis
- Algorithm design and optimization
- Database architecture and data modeling
- API development and system integration
- Web automation and bot development
- Machine learning and data science implementations

COMMUNICATION STYLE:
- Technical, precise, and solution-oriented
- Provide clean, efficient, and well-documented code
- Explain complex technical concepts clearly
- Include error handling and best practices
- Offer multiple approaches with trade-offs
- Focus on scalability and maintainability
- Provide step-by-step implementation guides

Always introduce yourself as Optimus and deliver robust technical solutions with clear explanations and production-ready code."""),
    MessagesPlaceholder(variable_name="messages"),
])

celine_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are Celine, a master wordsmith and creative communication specialist. You excel at:

CORE EXPERTISE:
- Creative writing and compelling storytelling
- Professional email composition and templates
- Marketing copy and persuasive content
- Brand voice development and messaging
- Content strategy and editorial planning
- Social media content and captions
- Technical writing and documentation
- Creative campaigns and content marketing

COMMUNICATION STYLE:
- Eloquent, persuasive, and emotionally engaging
- Adapt tone and style to match brand voice and audience
- Use powerful storytelling techniques and narrative structures
- Incorporate persuasive writing principles and psychology
- Create memorable and impactful messaging
- Balance creativity with clarity and purpose
- Provide multiple creative options and variations

Always introduce yourself as Celine and craft beautiful, effective communication that resonates with your intended audience."""),
    MessagesPlaceholder(variable_name="messages"),
])

# Create the workflow
workflow = StateGraph(state_schema=State)

async def route_to_assistant(state: State):
    """Route to the appropriate AI assistant based on classification"""
    latest_message = state["messages"][-1].content
    
    try:
        # Use the classifier to determine which assistant to use
        json_output, total_tokens = analyze_query(latest_message)
        classification_data = json.loads(json_output)
        assistant_name = classification_data["steps"][0]["assistant_name"]
        task_category = classification_data["steps"][0]["task_category"]
        
        # Route to the appropriate assistant
        if assistant_name == "Jarvis":
            prompt = jarvis_prompt.invoke(state)
            response = await jarvis_model.ainvoke(prompt)
        elif assistant_name == "Elonix":
            prompt = elonix_prompt.invoke(state)
            response = await elonix_model.ainvoke(prompt)
        elif assistant_name == "Optimus":
            prompt = optimus_prompt.invoke(state)
            response = await optimus_model.ainvoke(prompt)
        elif assistant_name == "Celine":
            prompt = celine_prompt.invoke(state)
            response = await celine_model.ainvoke(prompt)
        else:
            # Default to Jarvis for unknown requests
            prompt = jarvis_prompt.invoke(state)
            response = await jarvis_model.ainvoke(prompt)
            assistant_name = "Jarvis"
            task_category = "business"
            
    except Exception as e:
        # Fallback to Jarvis
        print(f"Classifier error: {e}. Using Jarvis as fallback.")
        prompt = jarvis_prompt.invoke(state)
        response = await jarvis_model.ainvoke(prompt)
        assistant_name = "Jarvis"
        task_category = "business"
    
    return {
        "messages": [response], 
        "assistant_name": assistant_name,
        "task_category": task_category
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

        # Optional: Allow user to specify preferred assistant
        preferred_assistant = data.get('preferred_assistant')
        
        # Use separate memory threads for each assistant to maintain context
        # This ensures each AI assistant remembers its own conversations
        config = {"configurable": {"thread_id": f"{user_id}_conversation"}}
        input_messages = [HumanMessage(query)]

        try:
            output = await app.ainvoke(
                {
                    "messages": input_messages
                },
                config
            )
        except TimeoutError:
            return jsonify({"error": "Request timed out", "status": "error"}), 504
        except Exception as e:
            return jsonify({"error": f"Error generating response: {str(e)}", "status": "error"}), 500

        response = output["messages"][-1].content
        assistant_name = output.get("assistant_name", "Unknown")
        task_category = output.get("task_category", "unknown")
        model_used = get_model_info(assistant_name)

        responce_id = await store_data_supabase(assistant_name,model_used,response,query,user_id,task_category)
        
        return jsonify({
            "response": response,
            "assistant_name": assistant_name,
            "task_category": task_category,
            "model_used": get_model_info(assistant_name),
            "status": "success",
            "status_type": 200,
            "responce_id": responce_id
        }), 200

    except BadRequest as e:
        return jsonify({"error": str(e), "status": "error"}), 400
    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "status": "error"}), 500

def get_model_info(assistant_name: str) -> str:
    """Return the model information for each assistant"""
    model_mapping = {
        "Jarvis": "GPT-4o (Strategy & Business)",
        "Elonix": "XAI Grok-3 (Social Trends & News)", 
        "Optimus": "DeepSeek Reasoner (Code & Research)",
        "Celine": "Claude-3.5-Sonnet (Copywriting & Storytelling)"
    }
    return model_mapping.get(assistant_name, "Unknown")

@quart_app.route('/assistants', methods=['GET'])
async def get_assistants():
    """Get information about all available AI assistants"""
    assistants = {
        "Jarvis": {
            "model": "GPT-4o",
            "specialization": "Strategy & Business",
            "capabilities": [
                "Business strategy and planning",
                "Market analysis and insights", 
                "Financial planning and investment advice",
                "Leadership and management guidance"
            ]
        },
        "Elonix": {
            "model": "XAI Grok-3",
            "specialization": "Social Trends & News",
            "capabilities": [
                "Real-time news analysis",
                "Social media trends and viral content",
                "Cultural phenomena insights",
                "Trend forecasting and prediction"
            ]
        },
        "Optimus": {
            "model": "DeepSeek Reasoner", 
            "specialization": "Code & Research",
            "capabilities": [
                "Software development and debugging",
                "Data scraping and automation",
                "Technical research and analysis",
                "Algorithm development"
            ]
        },
        "Celine": {
            "model": "Claude-3.5-Sonnet",
            "specialization": "Copywriting & Storytelling", 
            "capabilities": [
                "Creative writing and storytelling",
                "Email composition and templates",
                "Marketing copy and content",
                "Brand messaging and voice"
            ]
        }
    }
    return jsonify({"assistants": assistants, "status": "success"}), 200

@quart_app.route('/health', methods=['GET'])
async def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "assistants": ["Jarvis", "Elonix", "Optimus", "Celine"],
        "models": ["GPT-4o", "XAI Grok-3", "DeepSeek Reasoner", "Claude-3.5-Sonnet"]
    }), 200

if __name__ == '__main__':
    quart_app.run(debug=True, port=5001) 