import pytest
from unittest.mock import MagicMock, patch
from src.core.models.intent import LLMIntent
from src.adapters.llamacpp_provider import LlamaCppLLMProvider

def test_llamacpp_provider_fails_when_gguf_is_missing():
    with pytest.raises(FileNotFoundError, match="nonexistent_model.gguf"):
        LlamaCppLLMProvider(model_name="nonexistent_model.gguf")


def test_llamacpp_provider_successful_parse():
    """Verifies that a successful llama-cpp chat completion parsed structure resolves correctly."""
    mock_llama = MagicMock()
    
    completion_payload = {
        "choices": [
            {
                "message": {
                    "content": '{"intent_confidence": 0.98, "action": "open_app", "target": "notepad", "parameters": {}}'
                }
            }
        ]
    }
    mock_llama.create_chat_completion.return_value = completion_payload
    
    with patch("os.path.isfile", return_value=True):
        with patch("llama_cpp.Llama", return_value=mock_llama) as mock_llama_class:
            provider = LlamaCppLLMProvider(model_name="qwen2.5-3b.gguf")
            assert provider._llm is mock_llama
            
            schema = LLMIntent.model_json_schema()
            res = provider.generate_action("please could you launch the text editor notepad", schema)
            
            assert res["action"] == "open_app"
            assert res["target"] == "notepad"
            mock_llama.create_chat_completion.assert_called_once()


def test_rule_intent_parser_owns_regex_rule_fallback():
    from src.core.rules.rule_intent_parser import RuleIntentParser

    action = RuleIntentParser().generate_action(
        "open notepad",
        LLMIntent.model_json_schema(),
    )

    assert action["action"] == "open_app"
    assert action["target"] == "notepad"
