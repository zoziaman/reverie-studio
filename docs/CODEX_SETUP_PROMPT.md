# Codex Setup Prompt

Use this when a non-developer wants Codex to clone the public repository, check
the local machine, and prepare a safe Reverie Studio run.

## Copy-Paste Prompt

```text
I want to try Reverie Studio from this GitHub repository:
https://github.com/zoziaman/reverie-studio

Please clone it, read README.md, .env.example, EXTERNAL_ASSETS.md,
docs/PUBLIC_DEMO.md, docs/BACKEND_PROFILES.md, SECURITY_PUBLIC_CHECK.md, and
PUBLIC_RELEASE_CHECKLIST.md.

Start with the safe public checks only:

1. Run python scripts/public_verify.py --out <a temporary folder outside the repo>.
2. Run python scripts/public_verify.py --with-pytest --with-functions-audit --out <a temporary folder outside the repo> if pytest and npm are available.
3. Read public_verify_report.json and the generated public_demo reports.

The verifier wraps the same safe checks that used to be run separately:
python scripts/public_snapshot_check.py, python -m reverie_doctor --json, and
python -m reverie_demo --out <a temporary folder outside the repo>.

Do not paste real API keys, OAuth secrets, Firebase service accounts, private
keys, local personal paths, voice datasets, model weights, BGM/SFX libraries, or
generated media into the repository.

After the dry-run passes, explain which local tools are missing on this machine:
FFmpeg, Node.js, npm, ComfyUI or Stable Diffusion, TTS backend, Remotion setup,
YouTube OAuth, Firebase, and any model or asset folders.

If I choose a backend profile, help me configure it locally:

- local_dry_run: no AI services, no credentials, report-only demo
- local_comfyui_sovits: ComfyUI plus GPT-SoVITS, using my own local assets
- local_comfyui_supertonic: ComfyUI plus Supertonic 3 voice presets
- cloud_assisted_private_review: explicit opt-in credentials, private/test mode first

Keep every real secret and generated output outside git. If anything looks like
a credential or private local file, stop and report BLOCKED before committing.
```

## First Commands

```powershell
git clone https://github.com/zoziaman/reverie-studio.git
cd reverie-studio
$env:PYTHONPATH="src"
python scripts\public_verify.py --out "$env:TEMP\reverie-public-verify"
Get-Content "$env:TEMP\reverie-public-verify\public_verify_report.json"
Get-Content "$env:TEMP\reverie-public-verify\public_verify_summary.md"
Get-Content "$env:TEMP\reverie-public-verify\public_demo\pipeline_report.md"
```

## Expected First Outcome

The first successful run should create report files only:

```text
reverie-public-verify/
  public_verify_report.json
  public_verify_summary.md
  public_demo/
    backend_profile.json
    environment_report.json
    quality_gate.json
    run_manifest.json
    stage_log.jsonl
    pipeline_report.md
```

It should not create video, audio, image, subtitle, credential, token, database,
model, or cache files inside the repository.
