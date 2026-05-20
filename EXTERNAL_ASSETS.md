# External Assets

Reverie Studio is open-source code, but many production workflows depend on
local assets and services that are intentionally not included in this
repository.

Users should prepare their own assets and keep them outside git.

## User-Provided Items

- LLM/API keys for services the user chooses to enable
- YouTube OAuth credentials for upload-related workflows
- Firebase credentials only for features that explicitly require Firebase
- FFmpeg
- Stable Diffusion WebUI, ComfyUI, or another compatible image backend
- GPT-SoVITS, SoVITS, or another compatible TTS/voice backend
- Voice datasets and trained voice models
- BGM and SFX libraries with licenses suitable for the user's use case
- Stable Diffusion checkpoints, LoRA files, ComfyUI models, and related weights

## Recommended Local Layout

These are examples only. Use any local path and put the real paths in `.env`.

```text
external_assets/
  bgm/
  sfx/
  voice_datasets/
  models/
    checkpoints/
    loras/
```

## Git Rule

Do not commit external assets. Commit only code, docs, tests, safe sample
configuration, and reviewed public pack templates.

## Codex Setup Prompt

```text
Read README.md, .env.example, EXTERNAL_ASSETS.md, SECURITY_PUBLIC_CHECK.md, and
PUBLIC_RELEASE_CHECKLIST.md. Set up Reverie Studio locally on Windows using my
own API keys, models, voice data, BGM/SFX assets, and generation services. Keep
all credentials and generated outputs outside git.
```
