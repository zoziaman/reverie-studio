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

This first package is also the current gold target:

```text
gold_reusable_video_toon_actor_v1
```

The gold target rule is simple: the actor identity stays fixed, while episode
roles, backgrounds, scene contexts, and pack use cases may change. That makes
one model usable as a lead in a daily-life episode, a witness in a mystery
episode, a thumbnail subject, or a dialogue-layer source without redefining the
face, age band, hair silhouette, body proportions, clothing silhouette, or
stable voice slot.

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
template goal, reuse contract, required variants, mouth shapes, eye shapes,
layering contract, voice slot, and public release boundary.

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

Use `reuse-template` to export the portable version of that single-model goal:

```bash
reverie-actor-model-requests reuse-template assets/actor_models/actor_adult_woman_01/actor.json --repo-root . --context daily_life --context mystery --output data/actor_asset_requests/actor_adult_woman_01.reuse_template.json
```

The reuse template expands the actor into context/role slots for
`pack_actor_pool`, `episode_role_casting`, `scene_variant_selection`,
`mouth_flap_layering`, `eye_blink_layering`, `thumbnail_composition`, and
`omnibus_role_swap`. It writes a public-safe JSON manifest only; it does not
generate images, mouth layers, voice samples, checkpoints, or local output.

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

## Layering Contract

`layering_contract` defines how the generated actor assets should be composited
after they exist locally. The first gold template uses transparent PNG layers
on a stable `1024 x 1536` actor canvas:

- `variant_base`: the reusable actor pose/expression image under `variants/`.
- `eye_layer`: the selected eye layer under `face_parts/`.
- `mouth_layer`: the selected mouth layer under `face_parts/`.

The contract also stores normalized anchor points such as `actor_root`,
`eye_center`, and `mouth_center`. These are template coordinates, not generated
media, so they are safe to keep in the public repository. Local generators and
renderers can use them to align mouth and eye layers without guessing the
placement for every episode.

Export the renderer-facing layer spec with:

```bash
reverie-actor-model-requests layer-spec assets/actor_models/actor_adult_woman_01/actor.json --repo-root . --output data/actor_asset_requests/actor_adult_woman_01.layer_spec.json
```

The layer spec writes schema `reverie.actor_model.layer_spec.v1` and expands the
actor's required variants, mouth shapes, and eye shapes into compositable layer
entries. It does not create PNGs, call image models, or include private paths.

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

Export renderer-facing layer specs for the whole roster with:

```bash
reverie-actor-model-requests roster-layer-specs data/actor_asset_requests/daily_life_toon.actor_roster_plan.json --repo-root . --output data/actor_asset_requests/daily_life_toon.actor_roster_layer_specs.json
```

`roster-layer-specs` expands each actor into `variant_base`, `eye_layer`, and
`mouth_layer` entries with canvas size, anchors, z-index order, role ids, and
target PNG paths. This is the renderer handoff beside the asset request
manifest: it still contains no generated media, private paths, voice samples,
or model weights.

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

Check all scene-level actor files before rendering with `episode-asset-coverage`:

```bash
reverie-actor-model-requests episode-asset-coverage data/actor_asset_requests/daily_life_toon_ep001.episode_asset_plan.json --repo-root . --output data/actor_asset_requests/daily_life_toon_ep001.episode_asset_coverage.json --fail-on-missing
```

This verifies every scene's actor variant, mouth layer, and eye layer target
exists locally. It is the broad render-readiness check; the supplemental
`episode-variant-*` commands below handle missing actor variants specifically.

When `episode-asset-plan` reports missing variants, turn those gaps into a
deduplicated supplemental request manifest:

```bash
reverie-actor-model-requests episode-variant-requests data/actor_asset_requests/daily_life_toon.actor_roster_plan.json data/episodes/daily_life_toon_ep001.json --repo-root . --output data/actor_asset_requests/daily_life_toon_ep001.episode_variant_requests.json
```

`episode-variant-requests` writes one request per missing
`actor_id + variant_key`, even when several scenes need the same pose or
expression. It does not mutate `actor.json`; review the request manifest, create
the local PNG, then decide whether that variant should be promoted into the
actor package's durable `required_variants`.

After the supplemental PNGs are generated locally, check episode readiness with
`episode-variant-coverage`:

```bash
reverie-actor-model-requests episode-variant-coverage data/actor_asset_requests/daily_life_toon_ep001.episode_variant_requests.json --repo-root . --output data/actor_asset_requests/daily_life_toon_ep001.episode_variant_coverage.json --fail-on-missing
```

This report verifies the requested `variants/*.png` files exist under each
actor package. It is useful for one-off episode variants that should not yet be
added to durable `required_variants`.

When a generated episode variant should become part of the reusable actor
template, create a promotion plan:

```bash
reverie-actor-model-requests episode-variant-promotions data/actor_asset_requests/daily_life_toon_ep001.episode_variant_coverage.json --repo-root . --output data/actor_asset_requests/daily_life_toon_ep001.episode_variant_promotions.json --fail-on-not-ready
```

The promotion plan lists which `required_variants` entries would be added to
each actor package. It does not mutate `actor.json`; apply the plan only after
reviewing whether the variant belongs in the durable actor model instead of
remaining episode-specific.

To commit reviewed promotions into the local actor template, run:

```bash
reverie-actor-model-requests apply-episode-variant-promotions data/actor_asset_requests/daily_life_toon_ep001.episode_variant_promotions.json --repo-root . --output data/actor_asset_requests/daily_life_toon_ep001.episode_variant_promotion_apply.json
```

This command updates each actor package's `actor.json` `required_variants` list
and writes an apply report. It still does not copy generated PNGs or any voice
or model files into the public repository.

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

## One-Actor Episode Prepare

After a pack casts the gold actor into an episode role, use the one-command
prepare bundle to check the actor template and the referenced background plates
together:

```bash
reverie-videotoon-prepare episode data/actor_asset_requests/daily_life_toon.actor_roster_plan.json data/episodes/daily_life_toon_ep001.json assets/packs/daily_life_toon/settings.json --repo-root . --output-dir data/actor_asset_requests/prepare/daily_life_toon_ep001 --fail-on-not-ready
```

The prepare report keeps `actor_adult_woman_01` as the fixed identity target,
then reports episode-specific `missing_assets` and `next_actions`. The prepare
bundle also writes `actor_layer_specs` so a renderer can read the same actor
canvas, anchors, layer order, and target PNG paths that were checked during
preflight. That is the working loop for this gold model: create or place only
the missing local actor variants, mouth layers, eye layers, and background
plates, rerun prepare, then render when the report is ready.

To turn the prepare bundle into a renderer-facing scene graph, run:

```bash
reverie-videotoon-render-plan from-prepare data/actor_asset_requests/prepare/daily_life_toon_ep001/daily_life_toon_ep001.prepare_report.json --output data/actor_asset_requests/prepare/daily_life_toon_ep001/daily_life_toon_ep001.render_plan.json
```

The render plan writes schema `reverie.pack.videotoon_render_plan.v1`. It
contains scene-level `background_plate`, `variant_base`, `eye_layer`, and
`mouth_layer` composition layers for Remotion or another renderer to consume.
It is still public-safe JSON only; no PNGs, audio, video, private paths, or
model weights are produced.
