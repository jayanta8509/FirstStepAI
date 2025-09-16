from openai import OpenAI
from mem0 import Memory

openai_client = OpenAI()
memory = Memory()

async def store_messages_in_memory(user_message: str, ai_message: str, user_id: str) -> dict:
    """
    Store user and AI messages in mem0 based on user_id
    
    Args:
        user_message (str): The user's message
        ai_message (str): The AI's response message
        user_id (str): Unique identifier for the user
    
    Returns:
        dict: Result of the memory storage operation
    """
    # Create conversation messages format
    messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": ai_message}
    ]
    
    # Store the conversation in memory for the specific user
    result = memory.add(messages, user_id=user_id)

async def DailyExecutionPlan_with_user_history(user_id: str, current_message, limit: int = 10):
    """
    Generate alternative daily execution plans based on user's history
    
    Args:
        user_id (str): Unique identifier for the user
        current_message: Can be string or list of queries
        limit (int): Number of previous memories to retrieve
    
    Returns:
        list or str: 3 alternative daily plans or single response
    """
    # Handle both single string and array inputs
    if isinstance(current_message, list):
        queries = current_message
        is_alternative_request = True
    else:
        queries = [current_message]
        is_alternative_request = "alternative" in current_message.lower()
    
    # Retrieve user's history and preferences
    user_memories = memory.search(query=" ".join(queries), user_id=user_id, limit=limit)
    all_memories = memory.get_all(user_id=user_id)
    
    # Build user context from memories
    history_context = []
    
    # Extract relevant memories
    if all_memories:
        for mem_entry in all_memories:
            if isinstance(mem_entry, dict) and 'memory' in mem_entry:
                memory_content = mem_entry['memory']
                history_context.append(f"- {memory_content}")
    
    # Create simple context with just previous conversations
    user_context = f"""
Previous Conversations and Context:
{chr(10).join(history_context[:5])}  # Limit to recent 5 memories
"""

    if is_alternative_request:
        # Generate 3 alternative daily execution plans
        system_prompt = f"""You are Jarvis, the AI CEO and Co-Founder. Based on the user's previous conversations, create 3 SHORT alternative daily execution plans.

{user_context}

INSTRUCTIONS:
- Start each alternative with "Jarvis suggests:"
- Keep each plan to 3-4 bullet points maximum
- Focus on actionable steps for business growth
- Make each alternative unique and valuable
- Use a professional but friendly tone
- Be concise and direct - no long explanations

Format as 3 separate alternatives, each starting with "Jarvis suggests:" """
        
        combined_query = f"Generate 3 alternative daily execution plans for: {' | '.join(queries)}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": combined_query}
        ]
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=messages,
            max_tokens=500  # Keep responses short
        )
        
        ai_response = response.choices[0].message.content
        
        # Split into 3 alternatives
        alternatives = []
        if "Jarvis suggests:" in ai_response:
            parts = ai_response.split("Jarvis suggests:")
            for i, part in enumerate(parts[1:4]):  # Take first 3 alternatives
                alternative = f"Jarvis suggests:{part.strip()}"
                alternatives.append(alternative)
        
        # Ensure we have exactly 3 alternatives
        while len(alternatives) < 3:
            alternatives.append(f"Jarvis suggests: Focus on your business goals - take one strategic action today.")
        
        # Store the interaction
        store_messages_in_memory(combined_query, str(alternatives), user_id)
        
        return alternatives[:3]  # Return exactly 3 alternatives
        
    else:
        # Regular single response
        system_prompt = f"""You are Jarvis, the AI CEO and Co-Founder. Provide helpful, personalized guidance.

{user_context}

Use a professional but friendly tone and reference previous conversations when relevant. Keep responses focused and actionable."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": current_message}
        ]
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=messages
        )
        
        ai_response = response.choices[0].message.content
        
        # Store the conversation
        await store_messages_in_memory(current_message, ai_response, user_id)
        
        return ai_response



async def MonetizationPlan_with_user_history(user_id: str, passion: str, scale: str, business: str, limit: int = 10):
    """
    Generate monetization strategies based on user's passion, scale, and business type
    
    Args:
        user_id (str): Unique identifier for the user
        passion (str): What the user is passionate about
        scale (str): The scale/size of business they want (e.g., "small", "medium", "large")
        business (str): Type of business or industry
        limit (int): Number of previous memories to retrieve
    
    Returns:
        list: 3 monetization strategies for the business idea
    """
    # Create comprehensive business context from the new parameters
    business_context = f"Passion: {passion}, Scale: {scale}, Business Type: {business}"
    
    # Retrieve user's history and preferences
    user_memories = memory.search(query=business_context, user_id=user_id, limit=limit)
    all_memories = memory.get_all(user_id=user_id)
    
    # Build user context from memories
    history_context = []
    
    # Extract relevant memories
    if all_memories:
        for mem_entry in all_memories:
            if isinstance(mem_entry, dict) and 'memory' in mem_entry:
                memory_content = mem_entry['memory']
                history_context.append(f"- {memory_content}")
    
    # Create simple context with just previous conversations
    user_context = f"""
Previous Business Ideas and Conversations:
{chr(10).join(history_context[:3])}  # Limit to recent 3 memories
"""

    # Generate 3 monetization strategies tailored to passion, scale, and business type
    system_prompt = f"""You are Jarvis, the AI CEO and Co-Founder. Based on the user's passion, desired business scale, and business type, create 3 SPECIFIC monetization strategies to turn their vision into revenue.

{user_context}

USER'S BUSINESS PROFILE:
- Passion: {passion}
- Desired Scale: {scale}
- Business Type: {business}

INSTRUCTIONS:
- Provide 3 distinct revenue generation strategies tailored to their passion and scale
- Each strategy should align with their business type and desired scale
- Focus on different monetization models (subscription, one-time, affiliate, marketplace, etc.)
- Consider the scale preference (small = local/niche, medium = regional/scaling, large = global/enterprise)
- Keep each strategy to 2-3 sentences maximum
- Use a professional but friendly tone
- Be specific about revenue streams that match their passion and business type
- Ensure strategies are realistic for the chosen scale

Format: Provide 3 separate strategies as bullet points, each focusing on a different monetization approach that aligns with their passion, scale, and business type."""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Generate 3 monetization strategies for someone passionate about {passion}, wanting to build a {scale} scale {business} business."}
    ]
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=messages,
        max_tokens=400  # Keep responses concise
    )
    
    ai_response = response.choices[0].message.content
    
    # Parse the response into 3 strategies
    strategies = []
    
    # Split by bullet points or line breaks
    lines = ai_response.split('\n')
    current_strategy = ""
    
    for line in lines:
        line = line.strip()
        if line:
            # Check if it's a new bullet point or strategy
            if line.startswith('•') or line.startswith('-') or line.startswith('*') or line.startswith('1.') or line.startswith('2.') or line.startswith('3.'):
                # Save previous strategy if exists
                if current_strategy:
                    strategies.append(current_strategy.strip())
                # Start new strategy (remove bullet point)
                current_strategy = line.lstrip('•-*123. ').strip()
            else:
                # Continue current strategy
                if current_strategy:
                    current_strategy += " " + line
                else:
                    current_strategy = line
    
    # Add the last strategy
    if current_strategy:
        strategies.append(current_strategy.strip())
    
    # Ensure we have exactly 3 strategies
    while len(strategies) < 3:
        strategies.append(f"Create a subscription model around your {passion.lower()} in the {business.lower()} space with monthly recurring revenue appropriate for {scale} scale.")
    
    # Take only first 3 strategies and clean them
    final_strategies = []
    for i, strategy in enumerate(strategies[:3]):
        # Add monetization focus if not present
        if not any(word in strategy.lower() for word in ['$', 'revenue', 'price', 'cost', 'subscription', 'sell', 'monetize', 'income']):
            strategy += " Focus on pricing that reflects the value you provide and matches your scale preference."
        final_strategies.append(strategy)
    
    # Store the interaction
    await store_messages_in_memory(business_context, f"Monetization strategies: {final_strategies}", user_id)
    
    return final_strategies[:3]





# if __name__ == "__main__":
#     print("Chat with AI (type 'exit' to quit)")
#     user_id ="jayanta123"
#     while True:
#         user_input = input("You: ").strip()
#         if user_input.lower() == 'exit':
#             print("Goodbye!")
#             break
#         print(f"AI: {information_with_user_history(user_id , user_input)}")
