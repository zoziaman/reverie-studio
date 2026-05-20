import os
import shlex
import shutil
import subprocess
import time
import logging

from config.settings import config
from llm.base import LLMTextResponse

try:
    from utils.logger import get_logger
    logger = get_logger("claude_cli_adapter")
except Exception:
    logger = logging.getLogger("claude_cli_adapter")


class ClaudeCliStoryAdapter:
    def __init__(self, cli_path: str = "", model_name: str = "", extra_args: str = ""):
        self.cli_path = (cli_path or config.CLAUDE_CLI_PATH or "claude").strip()
        self._model_name = (model_name or config.STORY_LLM_MODEL or config.CLAUDE_CLI_MODEL or "sonnet").strip()
        self._extra_args = shlex.split(extra_args or config.CLAUDE_CLI_EXTRA_ARGS or "")
        self._setting_sources = (getattr(config, "CLAUDE_CLI_SETTING_SOURCES", "") or "").strip()
        self._no_session_persistence = bool(
            getattr(config, "CLAUDE_CLI_NO_SESSION_PERSISTENCE", True)
        )

        resolved_cli = shutil.which(self.cli_path)
        if not resolved_cli and os.path.exists(self.cli_path):
            resolved_cli = self.cli_path
        if not resolved_cli:
            raise FileNotFoundError(
                f"Claude CLI not found: {self.cli_path}. Install Claude Code CLI and ensure it is on PATH."
            )
        self._resolved_cli = resolved_cli

    @staticmethod
    def _prompt_to_text(prompt) -> str:
        if isinstance(prompt, str):
            return prompt
        if isinstance(prompt, list):
            return "\n".join(str(item) for item in prompt)
        return str(prompt)

    @staticmethod
    def _coerce_generation_config(generation_config):
        if generation_config is None:
            return {}
        if isinstance(generation_config, dict):
            return dict(generation_config)
        if hasattr(generation_config, "to_dict"):
            try:
                return dict(generation_config.to_dict())
            except Exception:
                pass
        data = getattr(generation_config, "__dict__", None)
        if isinstance(data, dict):
            return dict(data)
        return {}

    @classmethod
    def _build_sampling_hint(cls, generation_config) -> str:
        data = cls._coerce_generation_config(generation_config)
        if not data:
            return ""

        hints = []
        temperature = data.get("temperature")
        top_p = data.get("top_p")
        top_k = data.get("top_k")

        if isinstance(temperature, (int, float)):
            if temperature <= 0.35:
                hints.append("Keep the output tightly controlled, conservative, and highly consistent.")
            elif temperature >= 0.85:
                hints.append("Allow more novelty, sharper phrasing variety, and less predictable story beats while staying coherent.")

        if isinstance(top_p, (int, float)) and top_p < 0.75:
            hints.append("Prefer safer, more probable wording over unusual alternatives.")
        elif isinstance(top_p, (int, float)) and top_p > 0.9:
            hints.append("Permit a wider range of phrasings and imaginative variations.")

        if isinstance(top_k, (int, float)) and top_k <= 20:
            hints.append("Stay focused on the clearest and most direct continuation.")
        elif isinstance(top_k, (int, float)) and top_k >= 60:
            hints.append("Consider a broader spread of candidate phrasings before deciding.")

        if not hints:
            return ""
        return "[Sampling hint]\n" + "\n".join(f"- {hint}" for hint in hints) + "\n\n"

    @property
    def model_name(self) -> str:
        return f"claude-cli:{self._model_name}"

    def _build_command(self, include_optimized_flags: bool = True):
        cmd = [
            self._resolved_cli,
            "-p",
            "--output-format",
            "text",
            "--model",
            self._model_name,
        ]
        if include_optimized_flags:
            if self._setting_sources:
                cmd.extend(["--setting-sources", self._setting_sources])
            if self._no_session_persistence:
                cmd.append("--no-session-persistence")
        cmd.extend(self._extra_args)
        return cmd

    @staticmethod
    def _has_unsupported_flag(stderr: str) -> bool:
        stderr = (stderr or "").lower()
        return "unknown option '--setting-sources'" in stderr or "unknown option '--no-session-persistence'" in stderr

    def generate_content(self, prompt, timeout=None, generation_config=None, **kwargs):
        del kwargs

        sampling_hint = self._build_sampling_hint(generation_config)
        prompt_text = sampling_hint + self._prompt_to_text(prompt)
        timeout_sec = int(timeout or config.STORY_LLM_TIMEOUT_SEC or 180)
        retry_timeout_sec = max(timeout_sec + 180, int(timeout_sec * 1.5))

        def _run(cmd, timeout_override=None):
            started = time.time()
            active_timeout = int(timeout_override or timeout_sec)
            logger.info(
                f"[ClaudeCLI] invoke model={self._model_name} timeout={active_timeout}s "
                f"optimized_flags={'yes' if cmd == self._build_command(include_optimized_flags=True) else 'no'} "
                f"sampling_hint={'yes' if sampling_hint else 'no'}"
            )
            return subprocess.run(
                cmd,
                input=prompt_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=active_timeout,
                check=False,
            ), started, active_timeout

        cmd = self._build_command(include_optimized_flags=True)
        try:
            completed, started, active_timeout = _run(cmd)
        except subprocess.TimeoutExpired:
            logger.warning(f"[ClaudeCLI] timeout after {timeout_sec}s, retrying once with {retry_timeout_sec}s")
            completed, started, active_timeout = _run(cmd, timeout_override=retry_timeout_sec)
        logger.info(
            f"[ClaudeCLI] completed rc={completed.returncode} elapsed={time.time() - started:.1f}s "
            f"timeout={active_timeout}s"
        )
        if completed.returncode != 0 and self._has_unsupported_flag(completed.stderr):
            fallback_cmd = self._build_command(include_optimized_flags=False)
            try:
                completed, started, active_timeout = _run(fallback_cmd)
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"[ClaudeCLI] optimized flags unsupported, fallback timed out after {timeout_sec}s; "
                    f"retrying once with {retry_timeout_sec}s"
                )
                completed, started, active_timeout = _run(fallback_cmd, timeout_override=retry_timeout_sec)
            logger.info(
                f"[ClaudeCLI] fallback completed rc={completed.returncode} elapsed={time.time() - started:.1f}s "
                f"timeout={active_timeout}s"
            )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise RuntimeError(f"Claude CLI failed with exit code {completed.returncode}: {stderr}")

        text = (completed.stdout or "").strip()
        if not text:
            raise RuntimeError("Claude CLI returned an empty response")
        return LLMTextResponse(text=text, raw=completed)
