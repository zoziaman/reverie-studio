# Actor Model Template

Status: public-safe template contract

This document defines how Reverie Studio stores a reusable video-toon actor as
an asset package. It extends the active actor-pool rule in
`docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`.

The actor model package is not a generated media bundle. It is a contract for
where local users place references, variants, face parts, and QA notes after
they generate or curate their own assets.

## First Template Actor

The first template actor is:

```text
actor_adult_woman_01
```

This actor is a reusable adult Korean woman video-toon actor. The same actor can
be cast as a lead, support character, witness, neighbor, victim, office worker,
or mystery support role across different packs and episodes.

## Folder Shape

```text
assets/actor_models/actor_adult_woman_01/
  actor.json
  prompts/
    identity_prompt.txt
    variant_prompt.txt
    mouth_prompt.txt
    negative_prompt.txt
  references/
    README.md
    .gitkeep
  variants/
    .gitkeep
  face_parts/
    .gitkeep
  qa/
    actor_model_checklist.md
```

The public repository should keep these folders free of generated media, voice
samples, checkpoints, LoRA files, local paths, session logs, and credentials.

## actor.json

`actor.json` is the stable source of truth for one actor's identity lock,
required variants, mouth shapes, eye shapes, voice slot, and public release
boundary.

Packs may reference the actor from `settings.motiontoon.actor_pool`:

```json
{
  "actor_pool": {
    "actor_adult_woman_01": {
      "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
      "visual_identity": "adult Korean woman reusable video-toon actor",
      "voice_profile": "female_01",
      "required_variants": ["neutral_standing", "talking_standing"]
    }
  }
}
```

The pack can narrow required variants for a channel, but it should not redefine
the actor's age band, face shape, body proportions, or stable voice.

## Required Variants

The starter actor template requires:

- `neutral_standing`
- `talking_standing`
- `blink_standing`
- `happy_standing`
- `sad_standing`
- `angry_standing`
- `worried_standing`
- `scared_standing`
- `neutral_seated`
- `talking_seated`

These names are keys, not required public files. Local users can generate or
curate private images under `variants/`.

## Mouth And Eye Shapes

The early mouth-flap contract uses:

- `mouth_closed`
- `mouth_small_open`
- `mouth_wide_open`
- `mouth_round`

The early blink/expression support contract uses:

- `eyes_open`
- `eyes_closed`
- `eyes_worried`
- `eyes_angry`

Private local face-part files can be placed under `face_parts/` after the user
creates them.

## Public-Safe Boundary

The template may contain:

- JSON metadata.
- Prompt templates.
- README files.
- QA checklists.
- Empty placeholder files.

The template must not contain:

- Real generated actor images.
- Real voice samples or voice datasets.
- BGM, SFX, or channel output.
- LoRA files, checkpoints, model weights, or vendor caches.
- Local filesystem paths.
- API keys, OAuth tokens, Firebase service accounts, memory DBs, or session
  logs.

## Validation

The sample actor template is checked by `tests/test_actor_model_template.py`.
The schema is defined in `schemas/video_toon_actor_model.schema.json`.

Runtime-facing validation lives in `utils.actor_model.validate_actor_model_package`.
Pack-level validation uses `PackValidator(repo_root=...)` to verify
`settings.motiontoon.actor_pool.*.actor_model_path` references. A pack can only
request variants that exist in the actor model contract.

The public `daily_life_toon` and `mystery_toon` packs both expose
`actor_adult_woman_01` in `settings.motiontoon.actor_pool` and cast that actor
into one lead/observer slot while keeping older named actor aliases available
for compatibility.

## Scaffolding More Actors

Use `scaffold` to create the same public-safe folder contract for another
reusable actor. This is the preferred path when adding more fixed video-toon
models for new packs, genres, ages, and role ranges.

```bash
reverie-actor-model-requests scaffold actor_middle_man_01 --repo-root . --display-name "Middle Man Actor 01" --age-band middle_aged --gender-presentation man --role-range lead,support,suspect,witness --visual-identity "middle-aged Korean man with a practical jacket and calm expression"
```

The command creates `actor.json`, prompt templates, empty asset folders,
`references/README.md`, and `qa/actor_model_checklist.md`. It refuses to
overwrite an existing actor package unless `--force` is passed. The generated
package is a template only; it does not create or bundle PNGs, voice samples,
checkpoints, LoRAs, private paths, or generation logs.

For repeated pack work, start from the public-safe preset catalog:

```text
assets/actor_model_presets/catalog.json
```

The catalog contains starter archetypes for daily-life, mystery, historical,
school, family, office, and omniverse casting. Use `scaffold-preset` when the
actor should inherit a known age band, role range, voice slot, genre tags, and
visual identity:

```bash
reverie-actor-model-requests scaffold-preset daily_adult_man actor_daily_adult_man_01 --repo-root .
```

`scaffold-preset` still writes only the template package. Generated images,
mouth layers, eye layers, voice samples, and model weights remain local user
assets.

To plan a pack roster from presets, use `roster-plan`:

```bash
reverie-actor-model-requests roster-plan daily_life_toon --assignment protagonist=daily_adult_man:actor_daily_adult_man_01 --assignment witness=daily_middle_woman:actor_daily_middle_woman_01 --output data/actor_asset_requests/daily_life_toon.actor_roster_plan.json
```

The roster plan writes a public-safe JSON patch shape with
`motiontoon_patch.actor_pool`, `motiontoon_patch.cast_slots`,
`motiontoon_patch.role_casting_contract`, and an `episode_cast_seed`. This is
the bridge between reusable actor presets and pack-level casting: the actor id
stays fixed, while episode role casting can change per omnibus story.

Create every actor model package referenced by that roster plan with
`scaffold-roster`:

```bash
reverie-actor-model-requests scaffold-roster data/actor_asset_requests/daily_life_toon.actor_roster_plan.json --repo-root . --output data/actor_asset_requests/daily_life_toon.actor_roster_scaffold.json
```

The scaffold report lists which actor folders were created and whether each
generated `actor.json` validates. Existing actor folders are not overwritten
unless `--force` is passed.

After the roster actors exist, write one combined request manifest for every
variant, mouth shape, and eye shape needed by that pack roster:

```bash
reverie-actor-model-requests roster-asset-requests data/actor_asset_requests/daily_life_toon.actor_roster_plan.json --repo-root . --output data/actor_asset_requests/daily_life_toon.actor_roster_asset_requests.json
```

`roster-asset-requests` expands each actor in `motiontoon_patch.actor_pool`
through its `actor_model_path`, or through `--actor-root` when the scaffold was
created in a separate local directory. The output is still only a work order:
it lists prompt text and target PNG paths, but does not create images, voice
samples, model weights, or runtime artifacts.

Before rendering an omnibus episode, map scene roles to fixed actor assets with
`episode-asset-plan`:

```bash
reverie-actor-model-requests episode-asset-plan data/actor_asset_requests/daily_life_toon.actor_roster_plan.json data/episodes/daily_life_toon_ep001.json --repo-root . --output data/actor_asset_requests/daily_life_toon_ep001.episode_asset_plan.json --fail-on-invalid
```

The episode JSON should contain `episode_id`, `role_casting`, and `scenes`.
Each scene is checked against `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`, then
mapped to a concrete actor variant such as `variants/happy_standing.png`.
Dialogue scenes also receive a default mouth layer target such as
`face_parts/mouth_small_open.png`. Missing scene variants are reported before
the run reaches ComfyUI, SD WebUI, or the renderer.

Apply the roster plan to a pack settings file by writing a new output file:

```bash
reverie-actor-model-requests apply-roster-plan assets/packs/daily_life_toon/settings.json data/actor_asset_requests/daily_life_toon.actor_roster_plan.json --output data/actor_asset_requests/daily_life_toon.settings.with_roster.json
```

`apply-roster-plan` refuses to overwrite existing `actor_pool` or `cast_slots`
entries unless `--force` is passed. The default workflow writes a new settings
file, so public pack files are not changed during planning.

## Asset Request Manifest

The template can produce a local work order for generating the actual variant,
mouth, and eye assets. This command writes prompts and target paths only; it
does not call ComfyUI, SD WebUI, TTS, or any external model.

```bash
reverie-actor-model-requests asset-requests assets/actor_models/actor_adult_woman_01/actor.json --repo-root . --output data/actor_asset_requests/actor_adult_woman_01.asset_requests.json
```

From an uninstalled checkout, run the same command through the module with
`PYTHONPATH=src`.

The generated manifest uses schema `reverie.actor_model.asset_requests.v1` and
contains one request for every `required_variants`, `mouth_shapes`, and
`eye_shapes` entry in `actor.json`. Each request points at a local target such
as `variants/neutral_standing.png` or `face_parts/mouth_closed.png`.

Keep generated manifests and output images local unless they have passed the
public release boundary in this document.

To check local asset coverage after generation, run:

```bash
reverie-actor-model-requests coverage assets/actor_models/actor_adult_woman_01/actor.json --repo-root . --output data/actor_asset_requests/actor_adult_woman_01.coverage.json --fail-on-missing
```

The asset coverage report lists every expected variant, mouth, and eye target,
then marks which files exist locally. The public template is expected to report
missing assets because it does not bundle generated PNG files.

For a full pack, use `pack-coverage` against the pack settings file:

```bash
reverie-actor-model-requests pack-coverage assets/packs/daily_life_toon/settings.json --repo-root . --output data/actor_asset_requests/daily_life_toon.actor_coverage.json --fail-on-missing
```

`pack-coverage` scans `settings.motiontoon.actor_pool` for every
`actor_model_path`, runs actor asset coverage for each one, and returns one
pack-level readiness result.
