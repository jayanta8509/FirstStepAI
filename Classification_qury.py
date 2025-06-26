import os
import re
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()


class Step(BaseModel):
    assistant_name: str
    task_category: str

class classifier_query_data(BaseModel):
    steps: list[Step]

def analyze_query(input_question):

    prompt_template = """You are an expert task classifier for an AI routing system with specialized AI assistants. Your job is to analyze user messages and route them to the most appropriate AI assistant based on their expertise and the user's needs.

AI ASSISTANTS AND THEIR SPECIALIZATIONS:

1. "Jarvis" (GPT-4o) - STRATEGY & BUSINESS:
   - Business strategy and planning
   - Market analysis and business insights
   - Financial planning and investment advice
   - Leadership and management guidance
   - Business process optimization
   - Strategic decision making
   - Competitive analysis
   - Business model development

2. "Elonix" (XAI/Grok) - SOCIAL TRENDS & VIRAL CONTENT & NEWS:
   - Current events and breaking news
   - Social media trends and viral content
   - Cultural phenomena and trending topics
   - Real-time information and latest developments
   - Social impact analysis
   - Trend forecasting and prediction
   - Meme culture and internet trends
   - Celebrity news and entertainment

3. "Optimus" (DeepSeek) - CODE & DATA SCRAPING & RESEARCH:
   - Programming and software development
   - Code debugging and optimization
   - Data scraping and web automation
   - Technical research and analysis
   - Algorithm development
   - Database design and management
   - API development and integration
   - Technical documentation
   - Scientific research and data analysis

4. "Celine" (Claude) - COPYWRITING & EMAIL & STORYTELLING:
   - Creative writing and storytelling
   - Email composition and templates
   - Marketing copy and advertising content
   - Blog posts and articles
   - Social media captions
   - Product descriptions
   - Brand messaging and voice
   - Content creation and editing
   - Professional communication

CLASSIFICATION GUIDELINES:
- Focus on the PRIMARY intent and expertise needed
- Consider which AI assistant has the most specialized knowledge for the task
- For technical/coding tasks → Optimus
- For business/strategy questions → Jarvis  
- For current events/trends/news → Elonix
- For writing/communication tasks → Celine
- When in doubt, consider what type of specialized knowledge is most needed

EXAMPLES:
- "Write a business plan for a startup" → Jarvis (strategy)
- "What's trending on social media today?" → Elonix (social_trends)
- "Help me debug this Python code" → Optimus (coding)
- "Write a professional email to a client" → Celine (copywriting)
- "Analyze the latest AI market trends" → Jarvis (business)
- "What are the latest news about climate change?" → Elonix (news)
- "Create a web scraper for product prices" → Optimus (data_scraping)
- "Write a compelling story for my brand" → Celine (storytelling)

Respond with the assistant name and task category. Valid combinations:
- Jarvis: strategy, business
- Elonix: social_trends, viral_content, news
- Optimus: coding, data_scraping, research
- Celine: copywriting, email, storytelling"""

    completion = client.beta.chat.completions.parse(
    model="gpt-4o-2024-08-06",
    messages=[
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": input_question}
    ],
    response_format=classifier_query_data,
    )

    math_reasoning = completion.choices[0].message
    total_tokens = completion.usage.total_tokens
    if hasattr(math_reasoning, 'refusal') and math_reasoning.refusal:
        # Fallback to Jarvis for business if there's a refusal
        fallback_response = classifier_query_data(steps=[Step(assistant_name="Jarvis", task_category="business")])
        return fallback_response.model_dump_json(indent=2), total_tokens
    else:
        # Convert the parsed response to a Pydantic model
        math_solution = classifier_query_data(steps=math_reasoning.parsed.steps)
    
    # Convert the Pydantic model to JSON
    json_output = math_solution.model_dump_json(indent=2)
    return json_output, total_tokens

