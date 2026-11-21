import os
import json
import time
from typing import Dict, Any, Optional
from src.core.interfaces.llm import LLMProvider
from src.adapters.mocks.llm_mock import MockLLMProvider

class LlamaCppLLMProvider(LLMProvider):
    """Production LLM intent parser using in-process llama-cpp-python GGUF inference with GBNF grammar constraints."""

    def __init__(self, model_name: str = "qwen2.5-3b-instruct.Q4_K_M.gguf", raise_on_failure: bool = False):
        self.model_name = model_name
        self.raise_on_failure = raise_on_failure
        self._llm = None
        self._initialized = False
        
        # Instantiate mock parser as dynamic safety fallback
        self._fallback_provider = MockLLMProvider()

        # Try initializing llama-cpp
        try:
            from llama_cpp import Llama
            model_path = os.path.join("models", model_name)
            
            if os.path.exists(model_path):
                cpu_threads = min(6, os.cpu_count() or 4)
                self._llm = Llama(
                    model_path=model_path,
                    n_ctx=512,
                    n_threads=cpu_threads,
                    verbose=False
                )
                self._initialized = True
                print(f"[LLM] Llama.cpp initialized successfully with model {model_name} on {cpu_threads} CPU threads.")
            else:
                message = f"[LLM] Production model file missing at {model_path}. Install local GGUF model before launching."
                if raise_on_failure:
                    raise RuntimeError(message)
                print(f"{message} Fallback to mock parser activated.")
        except Exception as e:
            if raise_on_failure and not isinstance(e, RuntimeError):
                raise RuntimeError(f"Failed to initialize llama-cpp-python: {e}") from e
            print(f"[LLM] Failed to initialize llama-cpp-python: {e}. Fallback to mock parser activated.")

    def generate_action(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Parses natural text commands into structured schema actions with GBNF grammar constraints and fast-path."""
        t_start = time.time()
        fast_action = self._fallback_provider.generate_action(prompt, schema)
        if fast_action.get("action") not in ("ambiguous", "unknown"):
            t_fast = time.time() - t_start
            print(f"[LLM] Fast-path intent matched: {fast_action} in {t_fast * 1000:.2f}ms")
            return fast_action

        if not self._initialized or not self._llm:
            return fast_action

        try:
            system_prompt = (
                "You are an offline accessibility voice task operator for Windows.\n"
                "Your job is to parse conversational voice transcripts into structured system action commands.\n"
                "If the prompt is off-topic, casual conversation, or not an accessibility action, set action to 'unknown'.\n"
                f"Schema:\n{json.dumps(schema)}\n"
                "Return ONLY raw JSON matching the schema."
            )
            
            response = self._llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                response_format={
                    "type": "json_object",
                    "schema": schema
                },
                max_tokens=64,
                temperature=0.0
            )
            
            content = response["choices"][0]["message"]["content"]
            result = json.loads(content)
            
            # Low confidence default to unknown
            confidence = float(result.get("intent_confidence", 0.5))
            if confidence < 0.8:
                result["action"] = "unknown"
                
            return result

        except Exception as e:
            print(f"[LLM] Inference error: {e}. Returning unknown fallback.")
            return fast_action
