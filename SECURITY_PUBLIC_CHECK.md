# Security Public Check

Date: 2026-05-23

Scope: open-source release preparation for Reverie Studio. This check is about
the exact branch or exported directory that will be published to GitHub. It does
not certify older git history unless that history is also scanned.

## Verdict

NEEDS REVIEW

The current tracked publish set has a one-command public verifier that scans
tracked files, runs the local setup doctor, executes the no-credential dry-run,
checks the current workspace state, and can include pytest evidence. Remaining
review items are git history and the Firebase Functions dependency audit: do not
convert an existing private repository to public until old commits have also
been scanned or replaced by a clean release branch/export, and do not treat the
optional functions surface as production-ready until the residual moderate audit
chain is reviewed.

## Checklist

| Check | Status | Evidence / action |
| --- | --- | --- |
| Real `.env` / API key / token absent from publish set | PASS | Focused tracked-file scan found no `.env`, token pickle, credential store, Slack token, AWS key, Stripe live key, Hugging Face token, NPM token, or live API key file in the publish set. `.env.example` remains placeholder-only, and the snapshot scanner blocks env-like credential/token filenames. |
| YouTube OAuth credentials and token pickle absent | PASS | No OAuth client-secret JSON or token pickle is tracked. Runtime upload credentials remain user-provided local files. |
| Firebase service account absent | PASS | No Firebase service-account JSON is tracked. Firebase references are code/documentation placeholders only. |
| Memory DB / session log / local agent state absent | PASS | `.opennexus/`, `.claude/`, `daily/`, `data/collab/`, and tracked memory/session artifacts were removed from the publish set. |
| Generated channel output absent | PASS | Tracked generated backups, Remotion render artifacts, local output folders, cache folders, and generated script/image/audio folders were removed. |
| Voice, BGM, SFX, model weights absent | PASS | Tracked SoVITS training helpers, model-output/cache folders, Remotion `node_modules`, and local media output directories were removed from the publish set. |
| Personal identifiers absent | PASS | Focused scan found no real user-home paths or private identifiers in tracked release files; remaining phone-like strings are test fixtures for policy checks. |
| Public pack files reviewed | PASS | `assets/packs/` scan found no live API keys, local machine paths, or private key material. Packs are prompts/templates only unless users add their own assets locally. |
| Public verifier artifacts safe | PASS | `public_verify.py`, `reverie_doctor`, and `reverie_demo` write JSON/JSONL/Markdown reports outside the repository and do not read credentials, call cloud services, start local services, upload, or generate media. Snapshot findings in `public_verify_report.json` are summarized as counts and fingerprints rather than raw paths; run `scripts/public_snapshot_check.py` directly for local raw file locations. |
| Workspace state reported | PASS | `public_verify.py` records `workspace_state` from `git status --porcelain` as counts and path fingerprints, not raw local path names; release review should use a clean branch/export before publishing. |
| Firebase Functions dependency audit | NEEDS REVIEW | Non-breaking `npm audit fix --package-lock-only --omit=dev` reduced audit output to 9 moderate production dependency findings; the remaining suggested fix requires a breaking `firebase-admin` / `firebase-functions` path. |
| License boundary explicit | PASS | README and LICENSE state MIT for repository code/docs, while excluding rights to third-party local assets. |

## Focused Checks

Run these against the exact release directory or branch:

```powershell
python scripts\public_verify.py --with-pytest --with-functions-audit --out "$env:TEMP\reverie-public-verify"
Get-Content "$env:TEMP\reverie-public-verify\public_verify_report.json"
rg -n "AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(AKIA|ASIA)[0-9A-Z]{16}|(sk|rk)_live_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{20,}|npm_[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9_-]+|xox[baprs]-[A-Za-z0-9-]{20,}|BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY|private_key|client_secret|firebase-adminsdk"
rg -n "C:\\Users\\|C:/Users/|@gmail\.com|@naver\.com|@daum\.net|010[- ]?[0-9]{4}[- ]?[0-9]{4}"
git ls-files | rg -i "(^|/)(\.env|.*token.*|.*credential.*|.*secret.*|.*oauth.*|.*session.*|.*memory.*|.*\.db|.*\.sqlite|.*\.pickle|.*\.pkl|.*\.log)$|(^|/)(daily|\.opennexus|\.claude|logs|data/logs|data/backups|src/data/logs)(/|$)"
git ls-files | rg -i "(\.(mp4|mov|avi|wav|mp3|flac|ogg|ckpt|safetensors|pt|pth|bin|onnx|gguf|zip|7z|rar|exe)$)|(^|/)(node_modules|\.cache|__pycache__|release|dist|build|outputs?|temp|tmp|checkpoints?|loras?|voice_datasets?|thumbnails?|screenshots?)(/|$)"
```

## Publication Rule

Do not publish the whole local checkout by accident. Publish only after the
release branch/export passes this check without real credentials, local runtime
state, private personal data, generated media, or third-party model/audio assets.
