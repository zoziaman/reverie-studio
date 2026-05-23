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
review item is git history: `--with-history-scan` now adds redacted historical
filename evidence and blocks this recovered branch for direct public conversion,
so publish from a clean release branch/export unless the old commits are
intentionally reviewed or rewritten. `python scripts\public_export.py --out
<temp>` creates a history-free zip archive plus `public_export_manifest.json`
from the current tracked snapshot after the snapshot check passes, and
`public_verify.py --with-public-export` records that export verification in the
public verifier report. After `npm --prefix functions ci`,
`--with-functions-syntax` records whether `functions/index.js` loads under Node
without embedding stack traces or local paths. `--with-functions-audit` now
records 0 production vulnerabilities for the optional functions package,
together with structured counts and dependency versions.
The verifier also reports `publish_gate.release_options`: publish this
recovered/private-history workspace through `history_free_export` when it is
available, and keep `existing_repo_history` blocked until the exact repository
history passes `--with-history-scan`.

## Checklist

| Check | Status | Evidence / action |
| --- | --- | --- |
| Real `.env` / API key / token absent from publish set | PASS | Focused tracked-file scan found no `.env`, token pickle, credential store, Slack token, Discord webhook, Telegram bot token, AWS key, Stripe live key, Hugging Face token, NPM token, or live API key file in the publish set. `.env.example` remains placeholder-only, and the snapshot scanner blocks env-like credential/token filenames. |
| YouTube OAuth credentials and token pickle absent | PASS | No OAuth client-secret JSON or token pickle is tracked. Runtime upload credentials remain user-provided local files. |
| Firebase service account absent | PASS | No Firebase service-account JSON is tracked. Firebase references are code/documentation placeholders only. |
| Memory DB / session log / local agent state absent | PASS | `.opennexus/`, `.claude/`, `daily/`, `data/collab/`, and tracked memory/session artifacts were removed from the publish set. |
| Generated channel output absent | PASS | Tracked generated backups, Remotion render artifacts, local output folders, cache folders, and generated script/image/audio folders were removed. |
| Voice, BGM, SFX, model weights absent | PASS | Tracked SoVITS training helpers, model-output/cache folders, Remotion `node_modules`, and local media output directories were removed from the publish set. |
| Personal identifiers absent | PASS | Focused scan found no real user-home paths or private identifiers in tracked release files; remaining phone-like strings are test fixtures for policy checks. |
| Public pack files reviewed | PASS | `assets/packs/` scan found no live API keys, local machine paths, or private key material. Packs are prompts/templates only unless users add their own assets locally. |
| Public verifier artifacts safe | PASS | `public_verify.py`, `reverie_doctor`, and `reverie_demo` write JSON/JSONL/Markdown reports outside the repository and do not read credentials, call cloud services, start local services, upload, or generate media. Snapshot findings in `public_verify_report.json` are summarized as counts and fingerprints rather than raw paths; public demo artifacts use repo-relative `pack_path` and `<public_demo_output>` placeholders instead of raw workspace/temp paths; run `scripts/public_snapshot_check.py` directly for local raw file locations. |
| Clean public export available | PASS | From a clean workspace, `python scripts\public_export.py --out <temp>` refuses repo-internal output by default, reruns the tracked snapshot check, writes `reverie-public-snapshot.zip`, and records `git_history_included=false`, `archive_sha256`, clean `workspace_state`, archive integrity, and counts in `public_export_manifest.json`. `python scripts\public_verify.py --with-public-export --out <temp>` also creates, verifies, and summarizes the history-free archive under `checks.public_export`. |
| Firebase Functions syntax check | PASS | After `npm --prefix functions ci`, `python scripts\public_verify.py --with-functions-syntax --out <temp>` loads `functions/index.js` through Node and records only status, public-safe command text, return code, and generic detail in `checks.functions_syntax`. |
| Workspace state reported | PASS | `public_verify.py` records `workspace_state` from `git status --porcelain` as counts and path fingerprints, not raw local path names; release review should use a clean branch/export before publishing. |
| Git history filename scan | NEEDS REVIEW | `python scripts\public_verify.py --with-history-scan --out <temp>` reuses the public snapshot path rules against historical filenames and reports only counts/fingerprints. On this recovered branch it blocks direct public conversion because historical blocked roots, media/model extensions, and credential-like filenames still exist in old commits. |
| Public release options | NEEDS REVIEW | Read `publish_gate.release_options` in `public_verify_report.json`. `history_free_export` is the safe route for a clean archive without git history when available. `existing_repo_history` must remain blocked until the history scan passes for the exact repository being made public. |
| Firebase Functions dependency audit | PASS | `npm --prefix functions audit --package-lock-only --omit=dev --json` reports 0 production vulnerabilities after the lockfile refresh and root `uuid` override. The public verifier records structured counts and dependency versions instead of embedding raw parsed `npm audit` output. |
| License boundary explicit | PASS | README and LICENSE state MIT for repository code/docs, while excluding rights to third-party local assets. |

## Focused Checks

Run these against the exact release directory or branch:

```powershell
npm --prefix functions ci
python scripts\public_verify.py --with-pytest --with-functions-audit --with-functions-syntax --with-history-scan --with-public-export --out "$env:TEMP\reverie-public-verify"
Get-Content "$env:TEMP\reverie-public-verify\public_verify_report.json"
python scripts\public_export.py --out "$env:TEMP\reverie-public-export"
python scripts\public_export.py --verify --out "$env:TEMP\reverie-public-export"
Get-Content "$env:TEMP\reverie-public-export\public_export_manifest.json"
python scripts\public_snapshot_check.py --json
rg -n "AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(AKIA|ASIA)[0-9A-Z]{16}|(sk|rk)_live_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{20,}|npm_[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9_-]+|xox[baprs]-[A-Za-z0-9-]{20,}|https://discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]{40,}|bot[0-9]{6,}:[A-Za-z0-9_-]{30,}|BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY|private_key|client_secret|firebase-adminsdk"
rg -n "C:\\Users\\|C:/Users/|@gmail\.com|@naver\.com|@daum\.net|010[- ]?[0-9]{4}[- ]?[0-9]{4}"
git ls-files | rg -i "(^|/)(\.env|.*token.*|.*credential.*|.*secret.*|.*oauth.*|.*session.*|.*memory.*|.*\.db|.*\.sqlite|.*\.pickle|.*\.pkl|.*\.log)$|(^|/)(daily|\.opennexus|\.claude|logs|data/logs|data/backups|src/data/logs)(/|$)"
git ls-files | rg -i "(\.(mp4|mov|avi|wav|mp3|flac|ogg|ckpt|safetensors|pt|pth|bin|onnx|gguf|zip|7z|rar|exe)$)|(^|/)(node_modules|\.cache|__pycache__|release|dist|build|outputs?|temp|tmp|checkpoints?|loras?|voice_datasets?|thumbnails?|screenshots?)(/|$)"
```

## Publication Rule

Do not publish the whole local checkout by accident. Publish only after the
release branch/export passes this check without real credentials, local runtime
state, private personal data, generated media, or third-party model/audio assets.
If the current snapshot passes but history scan fails, publish only the
history-free export or a fresh repository created from it.
