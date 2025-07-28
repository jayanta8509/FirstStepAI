"""
FirstStepAI V5 - Prompt Loader Module
Handles loading YAML prompt configurations and creating unified prompt templates
"""

import os
import yaml
from typing import Dict, Any, Optional
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

class PromptLoader:
    """Load and manage V5 unified prompt configurations from YAML files"""
    
    def __init__(self, prompt_dir: str = "prompt"):
        """Initialize the prompt loader
        
        Args:
            prompt_dir: Directory containing YAML prompt files
        """
        self.prompt_dir = prompt_dir
        self._cache = {}
        
    def load_yaml_config(self, filename: str) -> Dict[str, Any]:
        """Load YAML configuration file
        
        Args:
            filename: Name of the YAML file (without extension)
            
        Returns:
            Dictionary containing the YAML configuration
        """
        if filename in self._cache:
            return self._cache[filename]
            
        file_path = os.path.join(self.prompt_dir, f"{filename}.yml")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                config = yaml.safe_load(file)
                self._cache[filename] = config
                return config
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML file {file_path}: {e}")
    
    def create_jarvis_prompt(
        self, 
        user_tier: str = "wanderer", 
        user_profile: Dict[str, Any] = None
    ) -> ChatPromptTemplate:
        """Create unified Jarvis prompt for specified tier with user profile
        
        Args:
            user_tier: User subscription tier (wanderer, builder, architect, awakener)
            user_profile: Optional user profile containing nickname, life_goal, etc.
            
        Returns:
            ChatPromptTemplate configured for the specified tier and user
        """
        config = self.load_yaml_config("jarvis")
        tier_config = config["tiers"].get(user_tier, config["tiers"]["wanderer"])
        
        # Extract profile information with defaults
        profile = user_profile or {}
        nickname = profile.get("nickname", "")
        life_goal = profile.get("life_goal", "")
        business_vision = profile.get("business_vision", "")
        preferred_tone = profile.get("preferred_tone", "professional")
        preferred_language = profile.get("preferred_language", "English")
        
        # Create personalization context
        personalization = ""
        if nickname:
            personalization += f"USER'S PREFERRED NAME: {nickname}\n"
        if life_goal:
            personalization += f"USER'S LIFE GOAL: {life_goal}\n"
        if business_vision:
            personalization += f"USER'S BUSINESS VISION: {business_vision}\n"
        if preferred_tone and preferred_tone != "professional":
            personalization += f"PREFERRED COMMUNICATION TONE: {preferred_tone}\n"
        
        # CRITICAL: Always enforce language preference
        if preferred_language:
            personalization += f"🌍 LANGUAGE REQUIREMENT: You MUST respond ONLY in {preferred_language}. Do NOT use any other language.\n"
        
        if personalization:
            personalization = f"\n🎯 PERSONALIZATION CONTEXT:\n{personalization}"
        
        # Format the system prompt with tier-specific and profile values
        system_prompt = config["system_prompt"].format(
            user_tier=user_tier.upper(),
            tier_price=tier_config["price"],
            personality=tier_config["personality"],
            focus=tier_config["focus"],
            capabilities=tier_config["capabilities"],
            soul_points=tier_config["soul_points"],
            approach=tier_config["approach"],
            guidance_style=tier_config["guidance_style"],
            framework_level=tier_config["framework_level"],
            personalization=personalization
        )
        
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
    
    def create_celine_prompt(
        self, 
        user_tier: str = "wanderer", 
        user_profile: Dict[str, Any] = None
    ) -> ChatPromptTemplate:
        """Create unified Celine prompt for specified tier with user profile
        
        Args:
            user_tier: User subscription tier
            user_profile: Optional user profile containing nickname, life_goal, etc.
            
        Returns:
            ChatPromptTemplate configured for the specified tier and user
        """
        config = self.load_yaml_config("celine")
        tier_config = config["tiers"].get(user_tier, config["tiers"]["wanderer"])
        
        # Extract profile information with defaults
        profile = user_profile or {}
        nickname = profile.get("nickname", "")
        life_goal = profile.get("life_goal", "")
        business_vision = profile.get("business_vision", "")
        preferred_tone = profile.get("preferred_tone", "professional")
        preferred_language = profile.get("preferred_language", "English")
        
        # Create personalization context
        personalization = ""
        if nickname:
            personalization += f"USER'S PREFERRED NAME: {nickname}\n"
        if life_goal:
            personalization += f"USER'S LIFE GOAL: {life_goal}\n"
        if business_vision:
            personalization += f"USER'S BUSINESS VISION: {business_vision}\n"
        if preferred_tone and preferred_tone != "professional":
            personalization += f"PREFERRED COMMUNICATION TONE: {preferred_tone}\n"
        
        # CRITICAL: Always enforce language preference
        if preferred_language:
            personalization += f"🌍 LANGUAGE REQUIREMENT: You MUST respond ONLY in {preferred_language}. Do NOT use any other language.\n"
        
        if personalization:
            personalization = f"\n🎯 PERSONALIZATION CONTEXT:\n{personalization}"
        
        # Format the system prompt with tier-specific and profile values
        system_prompt = config["system_prompt"].format(
            user_tier=user_tier.upper(),
            tier_approach=tier_config["approach"],
            output_requirement=tier_config["output_requirement"],
            personalization=personalization
        )
        
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
    
    def create_optimus_prompt(
        self, 
        user_tier: str = "wanderer", 
        user_profile: Dict[str, Any] = None
    ) -> ChatPromptTemplate:
        """Create unified Optimus prompt for specified tier with user profile
        
        Args:
            user_tier: User subscription tier
            user_profile: Optional user profile containing nickname, life_goal, etc.
            
        Returns:
            ChatPromptTemplate configured for the specified tier and user
        """
        config = self.load_yaml_config("optimus")
        tier_config = config["tiers"].get(user_tier, config["tiers"]["wanderer"])
        
        # Extract profile information with defaults
        profile = user_profile or {}
        nickname = profile.get("nickname", "")
        life_goal = profile.get("life_goal", "")
        business_vision = profile.get("business_vision", "")
        preferred_tone = profile.get("preferred_tone", "professional")
        preferred_language = profile.get("preferred_language", "English")
        
        # Create personalization context
        personalization = ""
        if nickname:
            personalization += f"USER'S PREFERRED NAME: {nickname}\n"
        if life_goal:
            personalization += f"USER'S LIFE GOAL: {life_goal}\n"
        if business_vision:
            personalization += f"USER'S BUSINESS VISION: {business_vision}\n"
        if preferred_tone and preferred_tone != "professional":
            personalization += f"PREFERRED COMMUNICATION TONE: {preferred_tone}\n"
        
        # CRITICAL: Always enforce language preference
        if preferred_language:
            personalization += f"🌍 LANGUAGE REQUIREMENT: You MUST respond ONLY in {preferred_language}. Do NOT use any other language.\n"
        
        if personalization:
            personalization = f"\n🎯 PERSONALIZATION CONTEXT:\n{personalization}"
        
        # Format the system prompt with tier-specific and profile values
        system_prompt = config["system_prompt"].format(
            user_tier=user_tier.upper(),
            tier_approach=tier_config["approach"],
            output_requirement=tier_config["output_requirement"],
            personalization=personalization
        )
        
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
    
    def create_elonix_prompt(
        self, 
        user_tier: str = "wanderer", 
        user_profile: Dict[str, Any] = None
    ) -> ChatPromptTemplate:
        """Create unified Elonix prompt for specified tier with user profile
        
        Args:
            user_tier: User subscription tier
            user_profile: Optional user profile containing nickname, life_goal, etc.
            
        Returns:
            ChatPromptTemplate configured for the specified tier and user
        """
        config = self.load_yaml_config("elonix")
        tier_config = config["tiers"].get(user_tier, config["tiers"]["wanderer"])
        
        # Extract profile information with defaults
        profile = user_profile or {}
        nickname = profile.get("nickname", "")
        life_goal = profile.get("life_goal", "")
        business_vision = profile.get("business_vision", "")
        preferred_tone = profile.get("preferred_tone", "professional")
        preferred_language = profile.get("preferred_language", "English")
        
        # Create personalization context
        personalization = ""
        if nickname:
            personalization += f"USER'S PREFERRED NAME: {nickname}\n"
        if life_goal:
            personalization += f"USER'S LIFE GOAL: {life_goal}\n"
        if business_vision:
            personalization += f"USER'S BUSINESS VISION: {business_vision}\n"
        if preferred_tone and preferred_tone != "professional":
            personalization += f"PREFERRED COMMUNICATION TONE: {preferred_tone}\n"
        
        # CRITICAL: Always enforce language preference
        if preferred_language:
            personalization += f"🌍 LANGUAGE REQUIREMENT: You MUST respond ONLY in {preferred_language}. Do NOT use any other language.\n"
        
        if personalization:
            personalization = f"\n🎯 PERSONALIZATION CONTEXT:\n{personalization}"
        
        # Format the system prompt with tier-specific and profile values
        system_prompt = config["system_prompt"].format(
            user_tier=user_tier.upper(),
            tier_approach=tier_config["approach"],
            output_requirement=tier_config["output_requirement"],
            personalization=personalization
        )
        
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
    
    def create_classifier_prompt(
        self, 
        user_tier: str = "wanderer",
        crisis_detected: bool = False,
        emergency_override: bool = False,
        input_question: str = ""
    ) -> str:
        """Create classifier prompt for query classification
        
        Args:
            user_tier: User subscription tier
            crisis_detected: Whether crisis was detected
            emergency_override: Whether emergency override is active
            input_question: The user's query to classify
            
        Returns:
            Formatted classifier prompt string
        """
        config = self.load_yaml_config("classifier")
        
        # Get tier-specific consultation levels
        tier_creative_level = config["tier_levels"]["creative"][user_tier]
        tier_technical_level = config["tier_levels"]["technical"][user_tier]
        tier_social_level = config["tier_levels"]["social"][user_tier]
        
        # Format the system prompt with current context
        system_prompt = config["system_prompt"].format(
            user_tier=user_tier,
            crisis_detected=crisis_detected,
            emergency_override=emergency_override,
            tier_creative_level=tier_creative_level,
            tier_technical_level=tier_technical_level,
            tier_social_level=tier_social_level,
            crisis_keywords=config["crisis_keywords"],
            input_question=input_question
        )
        
        return system_prompt
    
    def get_agent_metadata(self, agent_name: str) -> Dict[str, Any]:
        """Get metadata for a specific agent
        
        Args:
            agent_name: Name of the agent (jarvis, celine, optimus, elonix)
            
        Returns:
            Dictionary containing agent metadata
        """
        config = self.load_yaml_config(agent_name)
        return config.get("meta", {})
    
    def get_crisis_keywords(self) -> list:
        """Get crisis detection keywords from classifier config
        
        Returns:
            List of crisis detection keywords
        """
        config = self.load_yaml_config("classifier")
        return config.get("crisis_keywords", [])
    
    def clear_cache(self):
        """Clear the configuration cache"""
        self._cache.clear()

# Global prompt loader instance
prompt_loader = PromptLoader()

# Convenience functions for backward compatibility
def create_unified_jarvis_prompt(
    user_tier: str = "wanderer", 
    user_profile: Dict[str, Any] = None
) -> ChatPromptTemplate:
    """Create unified Jarvis prompt - V5 YAML-based system with user profile support"""
    return prompt_loader.create_jarvis_prompt(user_tier, user_profile)

def create_unified_celine_prompt(
    user_tier: str = "wanderer", 
    user_profile: Dict[str, Any] = None
) -> ChatPromptTemplate:
    """Create unified Celine prompt - V5 YAML-based system with user profile support"""
    return prompt_loader.create_celine_prompt(user_tier, user_profile)

def create_unified_optimus_prompt(
    user_tier: str = "wanderer", 
    user_profile: Dict[str, Any] = None
) -> ChatPromptTemplate:
    """Create unified Optimus prompt - V5 YAML-based system with user profile support"""
    return prompt_loader.create_optimus_prompt(user_tier, user_profile)

def create_unified_elonix_prompt(
    user_tier: str = "wanderer", 
    user_profile: Dict[str, Any] = None
) -> ChatPromptTemplate:
    """Create unified Elonix prompt - V5 YAML-based system with user profile support"""
    return prompt_loader.create_elonix_prompt(user_tier, user_profile)

def create_classifier_prompt(
    user_tier: str = "wanderer",
    crisis_detected: bool = False,
    emergency_override: bool = False,
    input_question: str = ""
) -> str:
    """Create classifier prompt - V5 YAML-based system"""
    return prompt_loader.create_classifier_prompt(
        user_tier, crisis_detected, emergency_override, input_question
    ) 