---
status: pending
started: 2026-02-03
parent: [[2026-01-26-gemini-batch-mode]]
---

# Task: Shire/LOTR Batch Loading Animation

## Intent

Add a distinctive, cozy Shire-themed loading animation for batch processing. The concept: Bilbo smoking his pipe on a bench, Gandalf slowly walking in from the distance. "A wizard is never late..." — fits perfectly with the patient waiting theme of batch processing.

**v1 shipped:** CoffeeLoading (CSS pixel art coffee mug with steam). Works well.

**This task:** Polish and ship the Shire animation as an alternative/replacement.

## What Works (POC done)

- Sprite-based scene with Gandalf walking across the Shire
- CSS smoke overlay animation (same technique as coffee steam)
- LOTR quote rotation

## What Needs Polish

1. **Slow down Gandalf walk** — currently way too fast (1/10 to 1/50x slower)
2. **Remove green fringe** — chroma key artifacts on sprite edges after background removal
3. **Clean Bilbo image** — need base image without baked-in smoke (so CSS smoke overlay can position correctly over his pipe)
4. **Proper sprite cropping** — current walk strip has two rows bleeding in, need clean single row

## LOTR Quotes

```
"A wizard is never late..."
"He arrives precisely when he means to."
"Have patience..."
"All we have to decide is what to do with the time given to us."
```

## Assets

User has raw Gemini-generated sprites stored locally:
- `gandalf-sprites.png` — multiple Gandalf sizes on green background
- `shire-scene.png` — Shire sunset with Bilbo on bench

Previous agent's processed assets (in worktree, now cleaned up):
- `gandalf-walk.png` — cropped walk cycle, green removed (had fringe issues)
- `shire-scene.jpg` — compressed background

## Technical Approach

- CSS sprite animation with `steps()` for walk cycle
- CSS smoke wisps overlaid on Bilbo's pipe position
- `image-rendering: pixelated` for crisp scaling
- ImageMagick/PIL for sprite processing (green removal, cropping, defringing)
