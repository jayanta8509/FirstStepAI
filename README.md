# Multi-AI Assistant System

A sophisticated AI routing system that intelligently directs queries to specialized AI assistants based on their expertise.

## 🤖 Meet Your AI Assistants

### Jarvis (GPT-4o) - Strategy & Business
**"Your Strategic Business Advisor"**
- Business strategy and planning
- Market analysis and insights
- Financial planning and investment advice
- Leadership and management guidance
- Business process optimization
- Strategic decision making

### Elonix (XAI Grok-3) - Social Trends & News
**"Your Digital Culture Expert"**
- Real-time news analysis and breaking developments
- Social media trends and viral content identification
- Cultural phenomena and internet culture insights
- Trend forecasting and prediction modeling
- Celebrity news and entertainment updates
- Platform-specific trend analysis

### Optimus (DeepSeek Reasoner) - Code & Research
**"Your Technical Engineering Specialist"**
- Full-stack software development and debugging
- Data scraping, mining, and automation tools
- Technical research and scientific analysis
- Algorithm design and optimization
- Database architecture and data modeling
- API development and system integration

### Celine (Claude-3.5-Sonnet) - Copywriting & Storytelling
**"Your Creative Communication Expert"**
- Creative writing and compelling storytelling
- Professional email composition and templates
- Marketing copy and persuasive content
- Brand voice development and messaging
- Content strategy and editorial planning
- Social media content and captions

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Up Environment Variables
Create a `.env` file with your API keys:
```env
OPENAI_API_KEY=your_openai_api_key
CLAUDE_API_KEY=your_claude_api_key
GROK_API_KEY=your_xai_grok_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
```

### 3. Start the Server
```bash
python app.py
```

### 4. Test the Integration
```bash
python test_assistant_integration.py
```

## 📡 API Endpoints

### Chat with AI Assistants
**POST** `/chat`

Request body:
```json
{
  "query": "Your question or request",
  "user_id": "unique_user_identifier"
}
```

Response:
```json
{
  "response": "AI assistant response",
  "assistant_name": "Jarvis|Elonix|Optimus|Celine",
  "task_category": "business|coding|news|copywriting",
  "model_used": "Model information",
  "status": "success",
  "status_type": 200
}
```

### Get Assistant Information
**GET** `/assistants`

Returns detailed information about all available AI assistants.

### Health Check
**GET** `/health`

Returns system status and available models.

## 🧠 Memory & Context

The system maintains separate conversation memory for each user, ensuring:
- Continuity across conversations
- Personalized responses based on history
- Context-aware interactions
- Thread-safe memory management

## 📊 Query Classification Examples

The system automatically routes queries to the most appropriate assistant:

| Query | Routes to | Reason |
|-------|-----------|---------|
| "Create a marketing strategy for my startup" | Jarvis | Business strategy |
| "What's trending on TikTok today?" | Elonix | Social trends |
| "Debug this Python code" | Optimus | Programming |
| "Write a product launch email" | Celine | Copywriting |

## 🛠️ Architecture

```
User Query → Classification System → Route to Specialist → Response
    ↓              ↓                        ↓               ↓
 Input Text → GPT-4o Classifier → Jarvis/Elonix/Optimus/Celine → Specialized Response
```

### Key Components:
- **Classification System**: Intelligent query routing using GPT-4o
- **Memory Management**: LangGraph with persistent memory per user
- **Specialized Prompts**: Custom system prompts for each assistant
- **Error Handling**: Graceful fallbacks and error recovery

## 🔧 Customization

### Adding New Assistants
1. Add model initialization in `app.py`
2. Create specialized prompt template
3. Update classification system in `Classification_qury.py`
4. Add routing logic in `route_to_assistant` function

### Modifying Assistant Behavior
Each assistant's behavior is controlled by:
- **System Prompt**: Defines expertise and communication style
- **Model Parameters**: Temperature, max tokens, etc.
- **Classification Categories**: Determines routing logic

## 🚨 Error Handling

The system includes comprehensive error handling:
- **Classification Failures**: Falls back to Jarvis (business assistant)
- **Model Timeouts**: Returns appropriate error messages
- **API Key Issues**: Graceful degradation with informative errors
- **Invalid Requests**: Clear validation error messages

## 📈 Performance Optimization

- **Parallel Processing**: Asynchronous request handling
- **Memory Efficiency**: Optimized memory usage per conversation
- **Caching**: Response caching for common queries (optional)
- **Load Balancing**: Can be extended for multiple instances

## 🔒 Security Considerations

- API key management through environment variables
- Input validation and sanitization
- Rate limiting capabilities (can be added)
- User session isolation

## 📝 Usage Examples

### Business Strategy Query
```python
import aiohttp

async def ask_jarvis():
    async with aiohttp.ClientSession() as session:
        payload = {
            "query": "Analyze the competitive landscape for AI startups",
            "user_id": "user_123"
        }
        async with session.post("http://localhost:5001/chat", json=payload) as response:
            result = await response.json()
            print(f"Jarvis says: {result['response']}")
```

### Social Trends Query
```python
async def ask_elonix():
    payload = {
        "query": "What are the latest viral TikTok trends?",
        "user_id": "user_123"
    }
    # Similar request pattern...
```

## 🧪 Testing

Run the comprehensive test suite:
```bash
python test_assistant_integration.py
```

Tests include:
- Health checks
- Assistant routing accuracy
- Memory persistence
- Error handling
- Response quality validation

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

This project is licensed under iksen india pvt ltd(Jayanta Roy).

## 🆘 Support

For issues and questions:
1. Check the error logs
2. Verify API key configuration
3. Test individual components
4. Review classification accuracy

---

**Built with ❤️ for intelligent AI assistance** 