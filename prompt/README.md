# FirstStepAI V5 - Unified Prompt System

This directory contains the YAML-based prompt configurations for the FirstStepAI V5 Ghost Team Architecture.

## 🎯 V5 System Overview

The V5 system uses **unified prompts** that automatically adapt to user tiers (wanderer, builder, architect, awakener), reducing complexity by 75% while maintaining sophisticated tier-based intelligence.

## 📁 Prompt Files

### Core AI Agents

- **`jarvis.yml`** - AI CEO & Strategic Mentor (Unified Brand Voice)
  - Public-facing entrepreneurial guidance
  - Tier-adaptive personality and capabilities
  - Crisis detection and escalation
  - Soul points integration

- **`celine.yml`** - Creative Intelligence (Ghost Specialist)
  - Brand storytelling and messaging
  - Marketing and communication strategies
  - Investor pitch development
  - Tier-adaptive creative guidance

- **`optimus.yml`** - Technical Intelligence (Ghost Specialist)
  - Business automation and optimization
  - Technical architecture guidance
  - AI integration strategies
  - Tier-adaptive technical solutions

- **`elonix.yml`** - Social Intelligence (Ghost Specialist)
  - Social media and viral strategies
  - Market trend analysis
  - Community building tactics
  - Tier-adaptive social approaches

### System Components

- **`classifier.yml`** - V5 Ghost Team Classification System
  - Query routing to optimal specialists
  - Crisis detection keywords
  - Tier-specific consultation levels
  - Security protocols for invisible operation

## 🔧 Configuration Structure

Each agent YAML file contains:

```yaml
meta:
  agent_name: "Agent Name"
  role: "Agent Role"
  model: "AI Model"
  version: "v5_unified"
  description: "Agent description"

tiers:
  wanderer:    # FREE tier
  builder:     # $9/month tier  
  architect:   # $29/month tier
  awakener:    # $99/month tier

system_prompt: |
  # Prompt template with {variables}
```

## 🛠️ Usage

The prompt system is accessed via `prompt_loader.py`:

```python
from prompt_loader import create_unified_jarvis_prompt

# Create tier-specific prompt
prompt = create_unified_jarvis_prompt(user_tier="architect")
```

## 🔒 Security Features

- **Ghost Team Architecture**: Specialist AIs operate invisibly
- **Identity Protection**: Only Jarvis visible to users
- **Multi-layer Security**: Prevents architecture exposure
- **Tier Adaptation**: Automatic intelligence scaling

## 📈 Benefits

- **75% Complexity Reduction**: From 16 prompts to 4 unified prompts
- **Dynamic Adaptation**: Real-time tier-based customization
- **Easy Management**: YAML-based configuration
- **Version Control**: Track prompt changes efficiently
- **Scalability**: Add new tiers/features easily

## 🚀 V5 Deployment Status

✅ All prompt files created  
✅ YAML loader implemented  
✅ Integration with app.py complete  
✅ Classification system updated  
✅ Backward compatibility maintained  

**System Status**: V5 Ghost Team Architecture ACTIVE 