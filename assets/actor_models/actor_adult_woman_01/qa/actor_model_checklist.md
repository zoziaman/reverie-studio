# Actor Model Checklist

Actor: `actor_adult_woman_01`

Use this checklist before moving a local actor package beyond `template`.

- [ ] Identity lock is clear enough for another agent to reproduce.
- [ ] Required variants are generated or curated locally.
- [ ] Mouth shapes exist locally and align to the same face.
- [ ] Eye shapes exist locally and align to the same face.
- [ ] Voice profile is selected and stable.
- [ ] Actor can be referenced from `settings.motiontoon.actor_pool`.
- [ ] No public package files contain generated channel output.
- [ ] No public package files contain voice datasets, model weights, API keys,
      local paths, memory DBs, session logs, or OAuth credentials.
