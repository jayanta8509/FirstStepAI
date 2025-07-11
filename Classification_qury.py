import os
import re
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from typing import Optional, Dict, List
from prompt_loader import create_classifier_prompt, prompt_loader

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()

class Step(BaseModel):
    assistant_name: str
    task_category: str
    confidence_score: Optional[float] = 0.9
    orchestration_type: Optional[str] = "single"
    reasoning: Optional[str] = ""
    emergency_detected: Optional[bool] = False

class classifier_query_data(BaseModel):
    steps: list[Step]
    user_tier: Optional[str] = "wanderer"
    available_ais: Optional[List[str]] = ["jarvis"]
    complexity_score: Optional[float] = 0.5
    crisis_detected: Optional[bool] = False
    tier_override: Optional[bool] = False

# FirstStepAI Business Logic - All tiers access all models with different token allocations
TIER_ACCESS = {
    "wanderer": ["jarvis", "celine", "elonix", "optimus"],   # Free - All models available
    "builder": ["jarvis", "celine", "elonix", "optimus"],    # $9 - All models available
    "architect": ["jarvis", "celine", "elonix", "optimus"],  # $29 - All models available
    "awakener": ["jarvis", "celine", "elonix", "optimus"]    # $99 - All models available
}

# Crisis keywords are now loaded from YAML configuration
def get_crisis_keywords():
    """Get crisis keywords from YAML configuration"""
    return prompt_loader.get_crisis_keywords()

def detect_crisis(query: str) -> bool:
    """Detect crisis situations that require emergency escalation"""
    query_lower = query.lower()
    crisis_keywords = get_crisis_keywords()
    return any(keyword in query_lower for keyword in crisis_keywords)

def validate_tier_access(assistant_name: str, user_tier: str) -> bool:
    """Validate if user tier allows access to requested AI"""
    available_ais = TIER_ACCESS.get(user_tier, ["jarvis"])
    return assistant_name.lower() in [ai.lower() for ai in available_ais]

def get_available_ais(user_tier: str) -> List[str]:
    """Get list of AIs available for user tier"""
    return TIER_ACCESS.get(user_tier, ["jarvis"])

def analyze_query(
    input_question: str, 
    user_tier: str = "wanderer",
    user_context: Optional[Dict] = None,
    emergency_override: bool = False
) -> tuple[str, int, Dict]:
    """
    Enhanced query analysis with FirstStepAI business logic
    
    Args:
        input_question: User's query
        user_tier: User's subscription tier (wanderer, builder, architect, awakener)
        user_context: Optional user context and history
        emergency_override: Emergency override for crisis situations
    
    Returns:
        Tuple of (json_output, total_tokens, metadata)
    """
    
    # Crisis detection
    crisis_detected = detect_crisis(input_question)
    available_ais = get_available_ais(user_tier)
    
    # Emergency override for crisis situations
    if crisis_detected and not emergency_override:
        emergency_override = True
        available_ais = ["jarvis", "celine", "elonix", "optimus"]  # Full access in crisis
    
    # Use YAML-based classifier prompt
    prompt_template = create_classifier_prompt(
        user_tier=user_tier,
        crisis_detected=crisis_detected,
        emergency_override=emergency_override,
        input_question=input_question
    )

    try:
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
            # Fallback with tier-appropriate AI
            fallback_ai = available_ais[0] if available_ais else "jarvis"
            fallback_response = classifier_query_data(
                steps=[Step(
                    assistant_name=fallback_ai, 
                    task_category="business",
                    emergency_detected=crisis_detected
                )],
                user_tier=user_tier,
                available_ais=available_ais,
                crisis_detected=crisis_detected,
                tier_override=emergency_override
            )
            return fallback_response.model_dump_json(indent=2), total_tokens, {
                "fallback_used": True,
                "crisis_detected": crisis_detected,
                "tier_override": emergency_override
            }
        else:
            # Parse and validate the response
            parsed_data = math_reasoning.parsed
            
            # Ensure AI selection respects tier access (unless emergency override)
            selected_ai = parsed_data.steps[0].assistant_name
            if not emergency_override and not validate_tier_access(selected_ai, user_tier):
                # Fallback to tier-appropriate AI
                selected_ai = available_ais[0] if available_ais else "jarvis"
                parsed_data.steps[0].assistant_name = selected_ai
                parsed_data.steps[0].reasoning = f"Tier access adjusted to {user_tier} permissions"
            
            # V5 Enhanced metadata with ghost team analytics
            parsed_data.user_tier = user_tier
            parsed_data.available_ais = available_ais
            parsed_data.crisis_detected = crisis_detected
            parsed_data.tier_override = emergency_override
            parsed_data.steps[0].emergency_detected = crisis_detected
            
            math_solution = classifier_query_data(
                steps=parsed_data.steps,
                user_tier=parsed_data.user_tier,
                available_ais=parsed_data.available_ais,
                complexity_score=parsed_data.complexity_score,
                crisis_detected=parsed_data.crisis_detected,
                tier_override=parsed_data.tier_override
            )
    
        # Convert the Pydantic model to JSON
        json_output = math_solution.model_dump_json(indent=2)
        
        # V5 Enhanced metadata for ghost team analytics and monitoring
        metadata = {
            "user_tier": user_tier,
            "crisis_detected": crisis_detected,
            "emergency_override": emergency_override,
            "available_ais": available_ais,
            "selected_ai": math_solution.steps[0].assistant_name,
            "tier_compliant": validate_tier_access(math_solution.steps[0].assistant_name, user_tier) or emergency_override,
            "v5_classification_system": True,
            "ghost_team_routing": True,
            "unified_prompt_system": True
        }
        
        return json_output, total_tokens, metadata
        
    except Exception as e:
        # Enhanced error handling
        fallback_ai = available_ais[0] if available_ais else "jarvis"
        fallback_response = classifier_query_data(
            steps=[Step(
                assistant_name=fallback_ai, 
                task_category="business",
                emergency_detected=crisis_detected,
                reasoning=f"Fallback due to error: {str(e)}"
            )],
            user_tier=user_tier,
            available_ais=available_ais,
            crisis_detected=crisis_detected,
            tier_override=emergency_override
        )
        
        metadata = {
            "error": str(e),
            "fallback_used": True,
            "crisis_detected": crisis_detected,
            "user_tier": user_tier,
            "v5_fallback_system": True,
            "ghost_team_routing": False,
            "unified_prompt_system": True
        }
        
        return fallback_response.model_dump_json(indent=2), 0, metadata

# Backward compatibility - override the default function for existing imports
def analyze_query_legacy(input_question: str) -> tuple[str, int]:
    """Legacy wrapper for backward compatibility"""
    json_output, total_tokens, _ = analyze_query(input_question)
    return json_output, total_tokens

# For imports that expect the old signature, alias the new function
__all__ = ['analyze_query', 'detect_crisis', 'validate_tier_access', 'get_available_ais']

