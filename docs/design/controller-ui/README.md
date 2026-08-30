# Controller UI design references and reusable assets

This directory supports Issue #25 / Design PR #51.

## `reference/`

Visual references only; they are not runtime assets.

- `current-controller.webp` — current controller screenshot supplied during review.
- `controller-redesign-preview.webp` — GPT Image concept preview for the proposed 2×2 controller.
- `controller-redesign-asset-board.webp` — GPT Image style / asset-board reference.

## `assets/`

Reusable **vector source assets**. These are clean standalone SVGs with a common 64×64 viewBox, consistent stroke treatment, and no card/background/text baked into the file.

- `icon-text-ocr.svg`
- `icon-vision.svg`
- `icon-watch.svg`
- `icon-context-watch.svg`

Cards, shortcut/footer chips, borders, hover/pressed states and the compact status strip are **not image assets**. They should be implemented natively in Qt using `app/ui/theme.py` so layout and DPI scaling remain correct on Windows and macOS.

The previous cropped bitmap exports were intentionally removed: they were board fragments, not reusable source assets.

The GPT Image boards are exploratory references. Any invented shortcuts, labels or colors on those boards are not implementation requirements. The source of truth remains `docs/plans/controller-ui-unification-design.md`.
