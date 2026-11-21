import json
import os
from typing import Any, Dict

from src.core.interfaces.llm import LLMProvider


class LlamaCppLLMProvider(LLMProvider):
    """Production intent parser using local llama.cpp GGUF inference."""

    DEFAULT_MODEL_NAME = "qwen2.5-3b-instruct.Q4_K_M.gguf"

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self.model_name = model_name
        model_path = os.path.join("models", model_name)
        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"Required local GGUF model is missing at '{model_path}'."
            )

        try:
            from llama_cpp import Llama
        except ImportError as error:
            raise RuntimeError("The llama-cpp-python runtime is not installed.") from error

        cpu_threads = min(6, os.cpu_count() or 4)
        self._llm = Llama(
            model_path=model_path,
            n_ctx=512,
            n_threads=cpu_threads,
            verbose=False,
        )
        print(
            f"[LLM] Llama.cpp initialized successfully with model {model_name} "
            f"on {cpu_threads} CPU threads."
        )

    def generate_action(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Parse speech using constrained local inference; never fall back to mock rules."""
        system_prompt = (
            "You are an offline accessibility voice task operator for Windows.\n"
            "Parse transcripts into structured system action commands.\n"
            "For off-topic or non-action input, return action 'unknown'.\n"
            f"Schema:\n{json.dumps(schema)}\n"
            "Return ONLY raw JSON matching the schema."
        )
        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object", "schema": schema},
            max_tokens=64,
            temperature=0.0,
        )
        result = json.loads(response["choices"][0]["message"]["content"])

        if float(result.get("intent_confidence", 0.5)) < 0.8:
            result["action"] = "unknown"
        return result
