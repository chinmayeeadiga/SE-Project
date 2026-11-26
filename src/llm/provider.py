import abc
import json
import logging
import re
from typing import Optional, Dict, Any, Type, TypeVar
import requests
from pydantic import BaseModel
from src.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMProvider(abc.ABC):
    """Abstract interface for LLM backends."""

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False
    ) -> str:
        """Generates raw text response for the prompt."""
        pass

    def is_available(self) -> bool:
        """Returns True if the provider service is reachable."""
        return True

    @staticmethod
    def clean_json_response(raw_text: str) -> str:
        """Extracts JSON block from LLM markdown fences or raw text."""
        stripped = raw_text.strip()
        # Look for ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return stripped

    @staticmethod
    def repair_truncated_json(raw: str) -> str:
        """Best-effort repair of a JSON string truncated at the token limit.

        Walks backwards from the end of the string looking for the largest
        prefix that is valid JSON (ends at a balanced ``}`` or ``]``).
        Falls back to returning the cleaned raw text so the caller can still
        raise a meaningful json.JSONDecodeError.
        """
        text = LLMProvider.clean_json_response(raw)
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass
        for i in range(len(text) - 1, 0, -1):
            if text[i] in ('}', ']'):
                candidate = text[:i + 1]
                try:
                    json.loads(candidate)
                    logger.warning(
                        "LLM response was truncated; recovered %d of %d chars",
                        len(candidate), len(text)
                    )
                    return candidate
                except json.JSONDecodeError:
                    continue
        return text  # caller will raise on json.loads


class OllamaProvider(LLMProvider):
    """Local LLM provider using Ollama HTTP API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model_name = model_name or settings.OLLAMA_MODEL
        self.temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self.timeout = timeout or settings.LLM_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False
    ) -> str:
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": True,          # Stream tokens to avoid read timeout on small models
            "options": {
                "temperature": self.temperature,
                "num_predict": 4096,  # Enough for full structured JSON responses
            }
        }
        if json_mode:
            payload["format"] = "json"
        if system_prompt:
            payload["system"] = system_prompt

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                # connect timeout=10s; per-chunk read timeout=180s (7B models need
                # time to load into CPU/RAM before the first token appears)
                timeout=(10, 180)
            )
            resp.raise_for_status()
            tokens: list[str] = []
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tokens.append(chunk.get("response", ""))
                if chunk.get("done", False):
                    break
            return "".join(tokens)
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request error: {e}")
            raise


class OpenAIProvider(LLMProvider):
    """OpenAI or compatible REST endpoint provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1"
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model_name = model_name or settings.OPENAI_MODEL
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False
    ) -> str:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=body,
            timeout=settings.LLM_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class FallbackProvider(LLMProvider):
    """Deterministic fallback provider ensuring reliable execution."""

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False
    ) -> str:
        return "{}"


def get_llm_provider() -> LLMProvider:
    """Factory function returning the configured LLM provider or fallback."""
    provider_type = settings.LLM_PROVIDER.lower()

    if provider_type == "ollama":
        provider = OllamaProvider()
        if provider.is_available():
            logger.info(f"Connected to live Ollama provider with model: {provider.model_name}")
            return provider
        else:
            logger.warning(
                "Local Ollama instance is not reachable at "
                f"{settings.OLLAMA_BASE_URL}. "
                "To start Ollama, run: 'ollama serve' and 'ollama run mistral'. "
                "Activating intelligent domain fallback engine."
            )
            return FallbackProvider()

    elif provider_type == "openai":
        provider = OpenAIProvider()
        if provider.is_available():
            return provider
        logger.warning("OpenAI API key missing. Activating fallback provider.")
        return FallbackProvider()

    else:
        return FallbackProvider()
