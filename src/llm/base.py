from dataclasses import dataclass
from typing import Any


@dataclass
class LLMTextResponse:
    text: str
    raw: Any = None
