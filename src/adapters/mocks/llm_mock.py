from src.core.rules.rule_intent_parser import RuleIntentParser


class MockLLMProvider(RuleIntentParser):
    """Test adapter exposing the deterministic rules parser under the mock interface."""
