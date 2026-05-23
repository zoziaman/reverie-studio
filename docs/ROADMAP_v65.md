# Reverie Studio Roadmap v65

Current version: v63.0
Last updated: 2026-05-01 KST

## Direction Change

Reverie is no longer pursuing the old pack set as the product default. The old horror/senior/scam packs and the old dynamic video/motiontoon output direction are retired for normal production.

The product direction is now:

```text
story research
-> story bible
-> storyboard JSON
-> reusable background layer
-> consistent character foreground layer
-> mouth/blink sprite cues
-> Remotion VideoToon assembly
-> local QC/report
```

## Product Packs

| Pack ID | Product Label | Status |
| --- | --- | --- |
| `daily_life_toon` | 일상 영상툰 | Active default |
| `mystery_toon` | 미스터리 영상툰 | Active default |

Legacy IDs are compatibility aliases only:

| Legacy ID | Routed To |
| --- | --- |
| `horror`, `horror_v59` | `mystery_toon` |
| `senior`, `senior_touching`, `senior_makjang`, `senior_life_saguk` | `daily_life_toon` |
| `senior_scam_alert` | `mystery_toon` |

## Retired Defaults

- Old pack assets in `assets/packs`.
- Old channel JSON imports in `data/channels`.
- Prop overlay-heavy scam pack UI.
- Legacy dynamic shake/zoom/pulse effects as a default.
- AnimateDiff/full-scene motion generation as a default production route.

## Current Priorities

1. Make GUI, license, pack loading, and renderer defaults all resolve to `daily_life_toon` or `mystery_toon`.
2. Keep `videotoon_layered` as the runtime render mode.
3. Use background and character layers instead of full-scene motion generation.
4. Promote only visually approved golden-cast assets into production.
5. Add production reports that score story freshness, layer readiness, policy safety, and commercial readiness.
6. Add Shorts output only after the long-form layered VideoToon path is stable.

## Quality Bar

Commercial-ready VideoToon output must satisfy:

- Recurring character identity is recognizable across scenes.
- Background and character layer separation is clean.
- Mouth animation follows speech timing without covering captions.
- Captions remain readable and do not occupy half the screen.
- Story premises are specific, current, and not generic AI template melodrama.
- YouTube metadata avoids false true-story claims, private data, unsafe scam instructions, and reused boilerplate.
- Every generated video ships with a local QC/readiness report.

## Next Milestones

### Phase 1: VideoToon Default Stabilization

- Finish removing product-facing references to old packs.
- Keep legacy aliases only where needed for compatibility.
- Validate `daily_life_toon` and `mystery_toon` pack load paths.
- Verify GUI starts with VideoToon local mode forced on.

### Phase 2: Asset Approval

- Review all six golden-cast expression sheets.
- Replace procedural mouth sprites with approved mouth-shape sprites.
- Mark accepted/rejected assets in the golden-cast manifest.

### Phase 3: Render Integration

- Use finalized layer bundles as the normal Remotion source.
- Keep failed-cut regeneration local and deterministic.
- Add per-scene layer/QC status into the GUI.

### Phase 4: Product Hardening

- Update user/admin docs to describe only the current VideoToon packs.
- Add a commercial readiness report to every output.
- Add installation/storage guidance for D-drive heavy assets.
- Add Shorts presets after the layered renderer is stable.
