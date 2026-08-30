# Controller UI design assets

These files support the floating-controller redesign tracked by Issue #25 and Design PR #51.

## Reference images

- `reference/current-controller.webp` — current UI screenshot supplied during design review.
- `reference/controller-redesign-preview.webp` — GPT Image concept preview for the proposed 2×2 controller.
- `reference/controller-redesign-asset-board.webp` — GPT Image asset/style board used during design discussion.

The reference copies are WebP exports sized for repository review. The original conversation images remain the visual source used to prepare them.

## Extracted concept assets

- `assets/icon-text-ocr.png`
- `assets/icon-vision.png`
- `assets/icon-watch.png`
- `assets/icon-context-watch.png`
- `assets/status-strip-ready.webp`

These are **design references**, not an instruction to rasterize the production UI. Cards, labels, shortcut/footer chips, status text, borders, hover states, and layout should remain native Qt UI built from the existing theme primitives so they scale correctly across Windows/macOS and DPI settings.

The standalone icon PNGs are extracted concept assets for reuse/reference. Prefer the existing `app/ui/theme.py` drawing/icon path when it can reproduce the approved shapes cleanly rather than adding unnecessary bitmap runtime dependencies.

The GPT Image asset board is exploratory and contains shortcut labels for Watch modes that are **not** part of the accepted design. The implementation source of truth remains `docs/plans/controller-ui-unification-design.md`.
