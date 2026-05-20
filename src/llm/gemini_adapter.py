from config.settings import config
from llm.base import LLMTextResponse


class GeminiStoryAdapter:
    def __init__(self, model_name: str = "auto"):
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is required for STORY_LLM_PROVIDER=gemini")

        from utils.gemini_compat import configure_gemini, get_gemini_model

        configure_gemini(config.GEMINI_API_KEY)
        effective_name = model_name or config.STORY_LLM_MODEL or "auto"
        self._model = get_gemini_model(effective_name)
        if not self._model:
            raise RuntimeError("Failed to initialize Gemini story model")

    @property
    def model_name(self) -> str:
        return getattr(self._model, "model_name", "gemini")

    def generate_content(self, prompt, timeout=None, generation_config=None, **kwargs):
        response = self._model.generate_content(
            prompt,
            timeout=timeout,
            generation_config=generation_config,
            **kwargs,
        )
        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return LLMTextResponse(text=text, raw=response)
