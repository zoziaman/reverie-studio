# Reverie Studio

Reverie Studio is a local, Windows-first AI video production studio. It is built
around repeatable creator workflows: content packs, story planning, generated
visuals, voice synthesis, subtitles, video assembly, thumbnail review, metadata
checks, and batch-run bookkeeping.

This repository is prepared as an open-source code release. The code is free to
use, modify, redistribute, and use commercially under the MIT License. It does
not include private credentials, private local data, generated channel output,
voice datasets, BGM libraries, LoRA/model weights, or service-account files.

## What You Can Use

- The Windows-first Python desktop app and workflow modules under `src/`
- Content-pack structure, pack validators, prompt templates, and public pack
  examples under `assets/packs/`
- Remotion integration scaffolding under `remotion-poc/`
- YouTube metadata guard, upload adapter code, and related tests
- Local batch, validation, rendering, and production-statistics utilities
- A safe placeholder environment template in `.env.example`

## What Is Not Included

The following items are intentionally excluded from the public repository:

- Real `.env` files, API keys, OAuth tokens, token pickle files, Firebase
  service-account JSON files, and local credential stores
- Personal local paths, usernames, emails, phone numbers, session logs, memory
  databases, private agent notes, and local runtime exports
- Generated channel videos, images, thumbnails, audio, subtitles, scripts,
  checkpoints, logs, and cache folders
- SoVITS/GPT-SoVITS voice datasets, trained voice models, BGM/SFX libraries,
  Stable Diffusion checkpoints, LoRA files, ComfyUI models, and other large
  third-party model/vendor assets

## Setup Overview

The repository expects users to provide their own local tools, credentials, and
assets. A typical setup looks like this:

1. Install Python 3.11+.
2. Install project dependencies from `pyproject.toml` or `requirements.txt` if
   your checkout includes one.
3. Install and run any local generation services you want to use, such as Stable
   Diffusion WebUI, ComfyUI, GPT-SoVITS, Supertonic 3, or a compatible TTS
   service.
4. Copy `.env.example` to `.env` and fill in local-only values.
5. Run the desktop app:

```powershell
copy .env.example .env
python src\main_gui.py
```

If you ask another Codex session to set this up from GitHub, the useful prompt is:

```text
Clone this repository, read README.md, .env.example, EXTERNAL_ASSETS.md,
SECURITY_PUBLIC_CHECK.md, and PUBLIC_RELEASE_CHECKLIST.md, then set up a local
Windows development run without adding real credentials or generated outputs to
git.
```

## Required Local Assets

Reverie Studio can reference external tools and assets, but those are not
bundled here. Users should prepare their own:

- API keys for any LLM/image/video service they choose to use
- YouTube OAuth credentials if they want upload-related flows
- Firebase credentials only if they use license/admin features that require it
- Local TTS or voice-cloning assets, including SoVITS/GPT-SoVITS voice data.
  Supertonic 3 can be enabled with `TTS_ENGINE=supertonic` after installing the
  optional `supertonic` package; see `docs/SUPERTONIC_TTS.md`.
- BGM and SFX assets with licenses suitable for their own use
- Stable Diffusion, ComfyUI, LoRA, checkpoint, or other model files
- FFmpeg and any external renderer/runtime required by their chosen workflow

Keep all of those items outside git, or store only placeholder paths in `.env`.
See `EXTERNAL_ASSETS.md` for a concise setup boundary.

## Content Packs

Public pack files and prompt templates are intended to be part of the open
release when they do not contain private credentials, private personal data, or
generated channel output. Packs are workflow examples and starting points; users
can modify them, create new packs, or replace them entirely.

Do not treat included pack prompts as guaranteed-safe publishing guidance. Review
generated content, metadata, disclosures, and platform policy compliance before
uploading anything.

## Safety And Upload Posture

Upload automation is treated as an adapter behind user-controlled configuration.
The safe default is local testing and review. If users enable YouTube upload
flows, they should use private/test uploads first and keep OAuth files local.

Synthetic or dramatized story content should not be presented as verified real
events. Metadata and titles should preserve disclosure, privacy checks,
scam-prevention disclaimers where relevant, and personal-data blocking.

## License

This project is released under the MIT License. See `LICENSE`.

The MIT license covers the code and documentation in this repository. It does
not grant rights to third-party models, voice datasets, BGM/SFX libraries,
generated media, or external services that users add locally.

## Public Release Checks

Before publishing, run the public checks against the exact branch or exported
folder you plan to release:

```powershell
Get-Content SECURITY_PUBLIC_CHECK.md
Get-Content PUBLIC_RELEASE_CHECKLIST.md
```

Do not publish if the release contains real credentials, private local state,
generated channel output, model weights, voice datasets, BGM/SFX libraries, or
personal identifiers.
