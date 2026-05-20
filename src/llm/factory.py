from config.settings import config
from llm.claude_cli_adapter import ClaudeCliStoryAdapter
from llm.gemini_adapter import GeminiStoryAdapter


def create_story_llm(provider: str = None):
    effective_provider = (provider or config.STORY_LLM_PROVIDER or "claude_cli").strip().lower()

    if effective_provider == "gemini":
        return GeminiStoryAdapter(model_name=config.STORY_LLM_MODEL)

    if effective_provider in {"claude_cli", "claude"}:
        return ClaudeCliStoryAdapter(
            cli_path=config.CLAUDE_CLI_PATH,
            model_name=config.STORY_LLM_MODEL or config.CLAUDE_CLI_MODEL,
            extra_args=config.CLAUDE_CLI_EXTRA_ARGS,
        )

    raise ValueError(f"Unsupported story LLM provider: {effective_provider}")
