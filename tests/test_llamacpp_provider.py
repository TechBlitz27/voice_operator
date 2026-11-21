import pytest
from unittest.mock import MagicMock, patch
from src.core.models.intent import LLMIntent
from src.adapters.llamacpp_provider import LlamaCppLLMProvider

def test_llamacpp_provider_fallback_to_mock():
    """Verifies that if llama.cpp model file is missing, it falls back to MockLLMProvider."""
    provider = LlamaCppLLMProvider(model_name="nonexistent_model.gguf")
    assert provider._initialized is False
    
    # Run command and ensure mock parser resolves it
    schema = LLMIntent.model_json_schema()
    res = provider.generate_action("open notepad", schema)
    
    assert res["action"] == "open_app"
    assert res["target"] == "notepad"


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
    
    with patch("os.path.exists", return_value=True):
        with patch("llama_cpp.Llama", return_value=mock_llama) as mock_llama_class:
            provider = LlamaCppLLMProvider(model_name="qwen2.5-3b.gguf")
            assert provider._initialized is True
            
            schema = LLMIntent.model_json_schema()
            res = provider.generate_action("please could you launch the text editor notepad", schema)
            
            assert res["action"] == "open_app"
            assert res["target"] == "notepad"


def test_llamacpp_provider_30_off_topic_phrases_return_unknown():
    """Prompt 4 Requirement: Add a unit test that 30 off-topic phrases all return unknown."""
    off_topic_phrases = [
        "what's the weather",
        "hello",
        "thank you",
        "play music",
        "how are you today",
        "tell me a joke",
        "what time is it",
        "sing me a song",
        "who are you",
        "tell me the news",
        "set an alarm for 7am",
        "how's the stock market",
        "give me a recipe for pasta",
        "what was the cricket score",
        "search google for blue shoes",
        "what is two plus two",
        "why is the sky blue",
        "where is the nearest hospital",
        "can you hear me",
        "good morning operator",
        "good night see you tomorrow",
        "namaste aap kaise ho",
        "testing one two three",
        "tell me about artificial intelligence",
        "what is your favorite color",
        "how to learn python",
        "play some classical jazz",
        "sports update today",
        "weather in New Delhi tomorrow",
        "thank you very much for your help"
    ]

    assert len(off_topic_phrases) == 30, f"Must have exactly 30 phrases, got {len(off_topic_phrases)}"
    
    provider = LlamaCppLLMProvider(model_name="nonexistent.gguf")
    schema = LLMIntent.model_json_schema()

    for phrase in off_topic_phrases:
        action_dict = provider.generate_action(phrase, schema)
        assert action_dict.get("action") == "unknown", (
            f"Phrase '{phrase}' must resolve to 'unknown', got '{action_dict.get('action')}'"
        )
