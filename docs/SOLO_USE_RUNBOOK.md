# Solo-Use Runbook

This runbook is for the owner's local Windows checkout. It favors quick personal
operation over public-demo packaging: open the app, check local prerequisites,
run a dry workflow, and keep private credentials or generated media out of git.

## Daily Start

Run commands from the repository root.

```bat
python src\reverie_doctor.py --json
run_reverie.bat
```

Use the silent launcher when you want the GUI without a console window:

```bat
run_reverie_silent.bat
```

Use the setup doctor launcher when you want a double-clickable local health
check:

```bat
run_reverie_doctor.bat
```

For a no-credential workflow check that writes only temporary reports:

```bat
python src\reverie_demo.py --backend-profile local_dry_run --out "%TEMP%\reverie-solo-demo"
```

The same dry check is available as a launcher:

```bat
run_reverie_demo_dry_run.bat
```

Before trusting a larger edit or after a tool-assisted session:

```bat
python -m pytest -q
```

## Project Map

- `src\main_gui.py`: desktop GUI entrypoint.
- `src\gui\`: window, tabs, settings, and user-facing controls.
- `src\pipeline\`: end-to-end production pipeline helpers.
- `src\modules_pro\`: video, image, TTS, script, quality, and video-toon modules.
- `src\reverie_doctor.py`: local setup and prerequisite report.
- `src\reverie_demo.py`: dry workflow runner for checking the pipeline shape.
- `config\`: project configuration templates and validators.
- `data\`: local runtime state, queues, and logs.
- `assets\packs\`: content packs and pack templates.
- `docs\`: deeper design notes and troubleshooting references.
- `scripts\`: verification, export, audit, and maintenance utilities.
- `tests\`: regression tests that catch broken commands and contracts.

## Config And Data Flow

1. Copy `.env.example` to `.env` once.
2. Put local-only keys, model paths, API URLs, and upload credentials in `.env`.
3. The GUI and pipeline read settings from `config\`, `.env`, and local runtime
   state under `data\`.
4. Content packs under `assets\packs\` feed story planning, image prompts, TTS,
   subtitles, rendering, metadata, and upload review.
5. Generated videos, images, voice files, logs, model weights, and private
   credentials should stay local and untracked.

## Command Notes

Direct script commands work from the repository root without installing the
package:

```bat
python src\reverie_doctor.py --json
python src\reverie_demo.py --backend-profile local_dry_run --out "%TEMP%\reverie-solo-demo"
```

Module-style commands need either an editable install or `PYTHONPATH=src`:

```bat
set PYTHONPATH=src
python -m reverie_doctor --json
python -m reverie_demo --backend-profile local_dry_run --out "%TEMP%\reverie-solo-demo"
```

If a command fails after another agent session, start with these checks:

```bat
git status --short
python src\reverie_doctor.py --json
python -m pytest tests\test_windows_launchers.py tests\test_gui_wiring_guards.py tests\test_gui_runtime.py -q
```

## Personal Safety Rules

- Keep `.env`, Firebase credentials, OAuth tokens, generated media, voice data,
  model weights, and local service paths out of commits.
- Prefer `run_reverie.bat` or `python src\main_gui.py` for GUI work.
- Prefer `python src\reverie_doctor.py --json` before blaming the GUI.
- Prefer `local_dry_run` before touching real AI services or upload flows.
- Commit small verified fixes instead of leaving a half-dirty worktree.
