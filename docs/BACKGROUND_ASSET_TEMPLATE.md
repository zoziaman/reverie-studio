# Background Asset Template

Status: public-safe background plate contract

Video-toon packs need reusable background plates for omnibus episodes. The
actor identity stays fixed, while the location, time, and episode role can
change. This document defines how Reverie Studio turns pack background
templates into local generation requests and render-readiness coverage reports.

## Purpose

Background assets are not committed generated media. The public repository
stores:

- Location templates in pack `settings.json`.
- Prompt and negative prompt contracts.
- JSON request manifests.
- Coverage reports that say which local files are missing.

Generated PNGs remain local user assets under a background folder such as:

```text
assets/backgrounds/daily_life_toon/
```

## Request Manifest

Use the CLI to create a full background plate work order from a pack settings
file:

```bash
reverie-background-library-requests asset-requests assets/packs/daily_life_toon/settings.json --repo-root . --pack-id daily_life_toon --time day --time night --images-per-location 2 --output data/background_asset_requests/daily_life_toon.background_requests.json
```

The manifest schema is:

```text
reverie.background_library.asset_requests.v1
```

Each request contains:

- `request_type`: `background_plate`
- `location_id`
- `time`
- `target_relative_path`
- `prompt`
- `negative_prompt`
- deterministic `seed`
- 16:9 `width` and `height`
- `public_safe: true`

The command does not call SD WebUI, ComfyUI, or any image backend. It writes
only a public-safe JSON work order.

For real episode production, prefer an episode-specific request manifest:

```bash
reverie-background-library-requests episode-asset-requests assets/packs/daily_life_toon/settings.json data/episodes/daily_life_toon_ep001.json --repo-root . --pack-id daily_life_toon --output data/background_asset_requests/daily_life_toon_ep001.background_requests.json
```

The episode request schema is:

```text
reverie.background_library.episode_asset_requests.v1
```

This command reads scene background fields and creates requests only for the
location/time pairs used by that episode. It avoids generating unused
cross-product combinations such as `home_night` when the episode only needs
`home_day`.

## Coverage

After local generation or curation, verify that every requested background file
exists:

```bash
reverie-background-library-requests coverage data/background_asset_requests/daily_life_toon.background_requests.json --repo-root . --output data/background_asset_requests/daily_life_toon.background_coverage.json --fail-on-missing
```

The coverage schema is:

```text
reverie.background_library.asset_coverage.v1
```

The report includes `expected_count`, `existing_count`, `missing_count`,
`coverage_ratio`, `missing_assets`, and `ready_for_render`.

For episode rendering, prefer the narrower scene-level gate:

```bash
reverie-background-library-requests episode-coverage data/background_asset_requests/daily_life_toon_ep001.background_requests.json data/episodes/daily_life_toon_ep001.json --repo-root . --output data/background_asset_requests/daily_life_toon_ep001.background_coverage.json --fail-on-missing
```

The episode coverage schema is:

```text
reverie.background_library.episode_asset_coverage.v1
```

This report reads `episode.scenes[*].background_id`, `background_location`,
`location`, `place`, or `setting`, then matches those scene locations against
the background request manifest. It checks only the background plates needed by
that episode.

## Episode Preflight

Once actor episode coverage and background coverage are both available, combine
them into a single render gate:

```bash
reverie-videotoon-preflight episode --actor-coverage data/actor_asset_requests/daily_life_toon_ep001.episode_asset_coverage.json --background-coverage data/background_asset_requests/daily_life_toon_ep001.background_coverage.json --output data/preflight/daily_life_toon_ep001.preflight.json --fail-on-not-ready
```

The preflight schema is:

```text
reverie.pack.videotoon_episode_preflight.v1
```

The report is ready only when both actor assets and background plates are ready.
This is the first gate that answers the practical question: can this episode be
rendered without missing fixed actors, mouth or eye layers, or background
plates?

To write the actor reports, background reports, and preflight report in one
pass, use:

```bash
reverie-videotoon-prepare episode data/actor_asset_requests/daily_life_toon.actor_roster_plan.json data/episodes/daily_life_toon_ep001.json assets/packs/daily_life_toon/settings.json --repo-root . --output-dir data/preflight/daily_life_toon_ep001 --fail-on-not-ready
```

This command still writes JSON reports only. It does not generate actor images,
background images, voices, or video files. The bundle includes actor layer
specs, background requests, background coverage, final preflight, and a prepare
report with `missing_assets` and `next_actions` so the next local asset work is
visible without reading every coverage file manually.

After prepare, use `reverie-videotoon-render-plan from-prepare ...` to convert
the checked actor and background artifacts into a scene composition plan for
Remotion or another renderer.
Then use `reverie-videotoon-render-plan to-remotion-props ...` to export the
current Remotion props JSON without creating media files.

## Public Boundary

Background request manifests and coverage reports must not contain:

- Generated PNGs or video output.
- Voice samples.
- Model weights, LoRAs, checkpoints, or vendor caches.
- Absolute private paths.
- API keys, OAuth tokens, Firebase service accounts, memory DBs, or session
  logs.

This keeps the public repo useful as an asset-production contract while the
actual generated media stays local.
