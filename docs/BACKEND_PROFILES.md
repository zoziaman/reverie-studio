# Backend Profiles

Reverie Studio treats AI services as selectable backends. The public snapshot
does not bundle models, voices, credentials, or generated media. Backend
profiles document the intended setup shape so users and coding agents can
choose a path without guessing.

The profile catalog lives in `src/reverie_backends.py`.

## Profiles

| Profile | Best For | Default Safety |
| --- | --- | --- |
| `local_dry_run` | Fresh clone validation and CI | No credentials, no services, no media |
| `local_comfyui_sovits` | Local Windows workstation with ComfyUI and GPT-SoVITS | Local-only, upload blocked |
| `local_comfyui_supertonic` | Shorts-style voice pool with Supertonic 3 | Local-only, upload blocked |
| `cloud_assisted_private_review` | Users who explicitly choose paid APIs | Credentials required, private review first |

## Recommended Path

1. Start with `local_dry_run`.
2. Run `python scripts/public_verify.py --out <temp folder>`.
3. Read `<temp folder>/public_verify_report.json` and `<temp folder>/public_demo/pipeline_report.md`.
4. Install missing local tools.
5. Choose one real backend profile.
6. Keep upload in private/test review mode until the user approves production use.

## TTS Selection

TTS is not just an audio setting. It changes script planning because the voice
pool determines how many speakers can be cast clearly.

- `local_comfyui_sovits`: best when the user owns or trains voice data.
- `local_comfyui_supertonic`: best when the user wants a reference-free voice
  pool for short-form content.
- cloud-assisted TTS: best only when the user accepts API cost, service terms,
  and credential handling.

## Commercial Boundary

The MIT license covers this repository's code and documentation. It does not
grant rights to third-party models, voice presets, generated voices, BGM/SFX,
or platform credentials. Each user must verify their own asset and service
licenses before commercial use.
