# Security Public Check

Date: 2026-05-21

Scope: open-source release preparation for Reverie Studio. This check is about
the exact branch or exported directory that will be published to GitHub. It does
not certify older git history unless that history is also scanned.

## Verdict

NEEDS REVIEW

The current tracked publish set has been cleaned of local agent state, session
logs, generated backups, render outputs, large local caches, and machine-local
paths found during the focused scan. The remaining review item is git history:
do not convert an existing private repository to public until old commits have
also been scanned or replaced by a clean release branch/export.

## Checklist

| Check | Status | Evidence / action |
| --- | --- | --- |
| Real `.env` / API key / token absent from publish set | PASS | Focused tracked-file scan found no `.env`, token pickle, credential store, or live API key file in the publish set. `.env.example` remains placeholder-only. |
| YouTube OAuth credentials and token pickle absent | PASS | No OAuth client-secret JSON or token pickle is tracked. Runtime upload credentials remain user-provided local files. |
| Firebase service account absent | PASS | No Firebase service-account JSON is tracked. Firebase references are code/documentation placeholders only. |
| Memory DB / session log / local agent state absent | PASS | `.opennexus/`, `.claude/`, `daily/`, `data/collab/`, and tracked memory/session artifacts were removed from the publish set. |
| Generated channel output absent | PASS | Tracked generated backups, Remotion render artifacts, local output folders, cache folders, and generated script/image/audio folders were removed. |
| Voice, BGM, SFX, model weights absent | PASS | Tracked SoVITS training helpers, model-output/cache folders, Remotion `node_modules`, and local media output directories were removed from the publish set. |
| Personal identifiers absent | PASS | Focused scan found no real user-home paths or private identifiers in tracked release files; remaining phone-like strings are test fixtures for policy checks. |
| Public pack files reviewed | PASS | `assets/packs/` scan found no live API keys, local machine paths, or private key material. Packs are prompts/templates only unless users add their own assets locally. |
| License boundary explicit | PASS | README and LICENSE state MIT for repository code/docs, while excluding rights to third-party local assets. |

## Focused Checks

Run these against the exact release directory or branch:

```powershell
rg -n "AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|ya29\.[A-Za-z0-9_-]+|xox[baprs]-[A-Za-z0-9-]{20,}|BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY|private_key|client_secret|firebase-adminsdk"
rg -n "C:\\Users\\|C:/Users/|@gmail\.com|@naver\.com|@daum\.net|010[- ]?[0-9]{4}[- ]?[0-9]{4}"
git ls-files | rg -i "(^|/)(\.env|.*token.*|.*credential.*|.*secret.*|.*oauth.*|.*session.*|.*memory.*|.*\.db|.*\.sqlite|.*\.pickle|.*\.pkl|.*\.log)$|(^|/)(daily|\.opennexus|\.claude|logs|data/logs|data/backups|src/data/logs)(/|$)"
git ls-files | rg -i "(\.(mp4|mov|avi|wav|mp3|flac|ogg|ckpt|safetensors|pt|pth|bin|onnx|gguf|zip|7z|rar|exe)$)|(^|/)(node_modules|\.cache|__pycache__|release|dist|build|outputs?|temp|tmp|checkpoints?|loras?|voice_datasets?|thumbnails?|screenshots?)(/|$)"
```

## Publication Rule

Do not publish the whole local checkout by accident. Publish only after the
release branch/export passes this check without real credentials, local runtime
state, private personal data, generated media, or third-party model/audio assets.
