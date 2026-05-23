from __future__ import annotations

import os
from typing import Any


def _describe_key_state(api_key: str | None) -> str:
    if not (api_key or "").strip():
        return "missing"
    return "configured (value hidden)"


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _load_gemini_module() -> Any:
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai is not installed. Install project dependencies before running this diagnostic."
        ) from exc
    return genai


def main() -> int:
    _load_dotenv_if_available()
    api_key = os.getenv("GEMINI_API_KEY")

    print("=" * 50)
    print("[Gemini API diagnostic]")
    print(f"API key: {_describe_key_state(api_key)}")
    print("=" * 50)

    if not api_key:
        print("[error] GEMINI_API_KEY is not set in the environment or .env file.")
        return 1

    try:
        genai = _load_gemini_module()
        genai.configure(api_key=api_key)
    except Exception as exc:
        print(f"[configuration error] {exc}")
        return 1

    print("\nRequesting available Gemini models...")
    try:
        available_models = []
        for model_info in genai.list_models():
            supported_methods = getattr(model_info, "supported_generation_methods", [])
            if "generateContent" in supported_methods:
                model_name = getattr(model_info, "name", str(model_info))
                print(f"   found: {model_name}")
                available_models.append(model_name)

        if not available_models:
            print("\n[result] No generateContent-capable models were returned.")
            print("   Possible causes: quota exhausted, expired key, or an invalid key.")
            return 1

        target_model = available_models[0].replace("models/", "")
        print(f"\nTesting content generation with '{target_model}'...")
        model = genai.GenerativeModel(target_model)
        response = model.generate_content("Hello, are you working?")
        print(f"   response: {getattr(response, 'text', '')}")
        print("\n[result] Gemini API responded successfully.")
        return 0
    except Exception as exc:
        print(f"\n[connection failed] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
