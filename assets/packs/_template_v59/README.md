# Reverie Story Drama Template

This template is meant to be copied and turned into a real production pack.

## How to use it

1. Copy `_template_v59` to a new folder under `assets/packs/`.
2. Replace `pack_id`, `pack_name`, and `genre/channel_type` in `manifest.json`.
3. Rewrite `topics.json` so the template, tags, and scenario pools match the new niche.
4. Rewrite the prompts before shipping. The minimum set is:
   - `hook_generation.txt`
   - `hook_enhanced.txt`
   - `topic_generation.txt`
   - `topic_enhanced.txt`
   - `story_blueprint.txt`
   - `metadata_generation.txt`
   - `thumbnail_style.txt`
   - `cold_open_bridge.txt`
5. Update `settings.json` so voice mapping, thumbnail defaults, title hooks, and image style match the channel.
6. Build a `.revpack`, validate it, and test one full production run.

## What a production-ready pack must define

- A clear dramatic hook grammar. The first line must feel like a scene, not a generic slogan.
- A topic pool that creates conflict, reversal, and a payoff worth waiting for.
- A story blueprint that forces cold-open potential, mid-story escalation, and a last-line payoff.
- Metadata rules that generate both long-form and shorts-ready outputs.
- Thumbnail rules that expose the wound, secret, or reversal in 2-4 short phrases.

## Checklist before shipping

- No unresolved placeholder text.
- No unused variables like `{{tone}}` unless the runtime actually replaces them.
- No genre-specific logic added to Python code.
- `thumbnail.title_hooks` is populated.
- `metadata_generation.txt` outputs a `shorts` object.
- `cold_open_bridge.txt` exists and reads naturally after a dramatic cold open.
