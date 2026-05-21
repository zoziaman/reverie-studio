# Public Release Checklist

Date: 2026-05-21

Purpose: prepare Reverie Studio for an open-source GitHub release that permits
free use, modification, redistribution, and commercial use while excluding
private credentials, personal data, local runtime state, generated channel
content, and third-party model/audio assets.

## Verdict

NEEDS REVIEW

The tracked publish set has been cleaned for an open-source snapshot: local
agent state, session logs, generated media/output, vendor caches, and
machine-specific paths found during review were removed. The remaining review
gates are repository history and the optional Firebase Functions dependency
audit: scan or replace old private history before turning an existing private
repository public, and review the residual low-severity functions chain before
calling that surface production-ready.

## Release Checklist

| Item | Status | Required before public release |
| --- | --- | --- |
| MIT license present | PASS | `LICENSE` grants broad use, modification, distribution, sublicensing, sale, and commercial use for repository code/docs. |
| README explains open-source scope | PASS | README states what is included, what is excluded, and what users must provide locally. |
| External asset boundary documented | PASS | `EXTERNAL_ASSETS.md` explains that voice data, BGM/SFX, LoRA/checkpoints, and service credentials are user-provided. |
| `.env.example` is safe | PASS | Placeholder-only environment template; no real API keys, tokens, service accounts, or personal paths. |
| Real `.env` excluded | PASS | No `.env` or `.env.*.local` file is tracked; `.env.example` uses placeholders only. |
| OAuth/token/Firebase secrets excluded | PASS | No YouTube OAuth client secret, token pickle, Firebase service account, or credential store is tracked. |
| Memory/session/local-agent data excluded | PASS | `.opennexus/`, `.claude/`, `.cursor/`, `daily/`, `data/collab/`, and tracked memory/session files were removed. |
| Generated output excluded | PASS | Generated video/audio/image/thumbnail/subtitle/script/output folders and Remotion render artifacts were removed from the tracked publish set. |
| External model/audio assets excluded | PASS | BGM/SFX libraries, SoVITS voice data, LoRA/checkpoints/model weights, vendor caches, and Remotion `node_modules` are excluded. |
| Public packs reviewed | PASS | `assets/packs/` was scanned for live secrets, personal paths, and private-key material with no hits. |
| No-credential demo available | PASS | `python -m reverie_demo` runs a public dry-run that writes only report files outside the repository. |
| Local setup doctor available | PASS | `python -m reverie_doctor --json` reports missing local prerequisites without reading secrets or starting services. |
| Backend profile boundary documented | PASS | `docs/BACKEND_PROFILES.md` and `src/reverie_backends.py` describe dry-run, local SoVITS, local Supertonic, and opt-in cloud profiles. |
| Public quality gate available | PASS | The dry-run writes `quality_gate.json` with score, threshold, review requirements, and no media inspection. |
| CI covers public snapshot checks | PASS | `.github/workflows/test.yml` runs the public snapshot scanner and dry-run demo on `main` and `codex/public-snapshot-clean`. |
| Firebase Functions dependency audit | NEEDS REVIEW | Non-breaking `npm audit fix` was applied to the lockfile; `npm audit` still reports 9 low-severity transitive findings that require a breaking force fix. |
| Existing git history reviewed | NEEDS REVIEW | If making an existing repo public, scan or rewrite history before public conversion. |

## Include

- `README.md`
- `LICENSE`
- `SECURITY_PUBLIC_CHECK.md`
- `PUBLIC_RELEASE_CHECKLIST.md`
- `EXTERNAL_ASSETS.md`
- `.env.example`
- `.gitignore`
- source files under `src/`
- tests that do not require private credentials or generated assets
- public setup/onboarding docs under `docs/`
- public pack prompts/templates under `assets/packs/` after review
- public Remotion scaffolding under `remotion-poc/` after excluding render output
- setup/build docs that use placeholders only

## Exclude

- `.env`, `.env.local`, `.env.*.local`
- `.claude/`, `.opennexus/`, `.gstack/`, `.cursor/`, `.skills/`, `daily/`
- memory DBs, session logs, agent exports, private notes, local handoff files
- `config/youtube_credentials.json`, OAuth token pickles, Firebase service
  account JSON, API settings, license keys, private credential stores
- generated videos, images, thumbnails, audio, subtitles, scripts, logs, batch
  state, render output, and temporary files
- BGM/SFX libraries, SoVITS/GPT-SoVITS voice datasets, LoRA files, checkpoints,
  ComfyUI/Stable Diffusion model weights, vendor caches, and build artifacts

## Final Step Before Publishing

Run `SECURITY_PUBLIC_CHECK.md` against the exact release branch/export. Publish
only when `python scripts\public_snapshot_check.py` passes and the publish set
has no real secrets, no personal data, no local runtime state, and no generated
or third-party assets that should remain user-provided.
