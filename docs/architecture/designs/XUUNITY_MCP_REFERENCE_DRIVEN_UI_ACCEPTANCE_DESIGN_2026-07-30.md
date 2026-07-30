# XUUnity MCP Reference-Driven UI Acceptance Design

Date: `2026-07-30`
Status: `P0.1 implemented and host-validated; P0.2 / P1.x / P2.x planned`
Scope: `Operations/XUUnityLightUnityMcp`
Source: [`2026-07-30_reference_driven_ui_completion_and_visual_acceptance_retro.md`](../../archive/retros/2026-07-30_reference_driven_ui_completion_and_visual_acceptance_retro.md)

## Problem

The MCP can prove that a Unity UI flow ran. It cannot prove that the rendered
screen matches a supplied design reference. A green scenario plus a screenshot
was being read as design acceptance, which is a category error:

```
compile passed + runtime flow passed + screenshot captured != reference UI accepted
```

The retro's capability map put three slices ahead of everything else: a
reference contract, a deterministic fixture, and a comparison that produces a
truthful verdict.

## Acceptance model: similarity, not pixel equality

The decisive design constraint, set by the operator after the first draft:

> Pixel-exact agreement with the reference must never be the bar. The Game View
> resolution in Play mode is switchable and will differ from the reference. The
> result has to be *recognisably the same screen* — style, placement, size — and
> "recognisably" must be configurable and sane.

The comparison therefore runs on a **resolution-independent cell grid**, not on
raw pixels:

1. The declared reference viewport is divided into a grid (`comparison_grid_width`
   cells wide, default 128; rows follow the reference aspect).
2. Each capture is reduced to that same grid by an **exact box average** of every
   pixel that falls into a cell. The same screen area yields the same cell mean
   whether it was rendered at 1440x3200, 1080x2400, or 720x1600.
3. Each cell also carries a **local contrast** value derived from its neighbours'
   mean luminance. That is the "is there detail here" signal — it is what catches
   body copy that never rendered, and it is resolution independent for the same
   reason the means are.

Three independent, separately reported lanes decide a region:

| Lane | Question | Signal |
| --- | --- | --- |
| Colour | Is this area the same colour/tone? | per-cell mean colour delta |
| Detail | Is the same amount of content drawn here? | per-cell local contrast delta, relative to the busier cell |
| Layout | Is the content in the same place at the same size? | content bounding box offset and size ratio per region |

A region passes when `similarity_score = min(colour_score, detail_score)` clears
the region minimum **and** the layout lane passes. A whole-screen score is
reported alongside, never instead of, the region scores.

### Why a mismatch has to survive three filters

Naive per-pixel comparison fails a rescaled capture for reasons that have nothing
to do with design fidelity. Three deliberate tolerances remove exactly those
artefacts and nothing else:

- **Per-cell tolerance** (`cell_color_tolerance`, `cell_structure_tolerance`) —
  absorbs antialiasing and minor palette drift.
- **Neighbourhood match** (`cell_match_radius`, default 1) — a cell may match any
  reference cell within one cell. This absorbs sub-cell layout jitter and the
  sampling-phase shift a resolution change necessarily introduces. Real movement
  is still caught, by the layout lane, which measures it in percent.
- **Coarse-scale confirmation** (`cell_coarse_factor`, default 2) — a mismatch
  must also survive at a 2x2 block average. High-frequency content (text lines,
  dithered art) lands on different cell boundaries at a different resolution; its
  local average does not. A wrong colour, a wrong sprite, or missing content
  fails at both scales.

### Tolerance profiles

`tolerance_profile` selects a named, documented tolerance set; per-reference
numeric overrides sit on top of it. Nothing is a global magic number.

| Profile | Intent | Cell colour | Region minimum | Layout offset |
| --- | --- | --- | --- | --- |
| `strict` | pixel-adjacent regression gate on a fixed resolution (no neighbourhood or coarse fallback) | 6 | 0.98 | 1% |
| `balanced` (default) | "clearly the same screen, built from the same design" | 14 | 0.92 | 3% |
| `lenient` | early implementation, art still in flight | 24 | 0.85 | 6% |

### Scale policy

`scale_policy` governs which captures are admissible at all:

- `aspect_scale` (default) — any Game View resolution whose aspect matches the
  reference within `aspect_tolerance` (2%). This is the switchable-resolution
  case; the verdict payload records `capture_scale` and warns that fine
  typography is outside the grid's resolving power.
- `strict` — dimensions must equal the reference exactly.
- `stretch` — different aspect accepted deliberately; recorded as a warning
  because layout and size findings weaken.

An orientation or aspect mismatch is refused as `comparison_not_comparable` with
**no score at all**, plus the list of same-aspect resolutions to set the Game
View to. An attractive but meaningless percentage is never printed.

## Delivered surface (P0.1)

Three host-side tools; no Unity dependency, no Unity asset writes.

| Tool / CLI | Purpose |
| --- | --- |
| `unity_ui_reference_register` / `ui-reference-register` | Copy the supplied PNG verbatim into a hash-linked bundle and record viewport, regions, declared masks, required UI selectors, tolerance profile, scale policy, owner, and per-lane acceptance requirements as `xuunity.ui-reference.v1`. |
| `unity_ui_reference_validate` / `ui-reference-validate` | Re-check schema, expected-image hash, viewport agreement, region geometry, mask policy, and thresholds; report same-aspect capture resolutions. |
| `unity_ui_reference_compare` / `ui-reference-compare` | Compare a capture, publish `actual.png` / `overlay.png` / `diff.png` / `metrics.json` / `verdict.json`, and return a `reference_acceptance` verdict. |

Modules, one responsibility each and all under the repo's 700-line review line:

| Module | Owns |
| --- | --- |
| `server_ui_reference_png.py` | dependency-free PNG decode/encode (stdlib `zlib` only) |
| `server_ui_reference_manifest.py` | contract vocabulary, tolerance profiles, normalizers, geometry |
| `server_ui_reference_policy.py` | manifest validation and the mask audit |
| `server_ui_reference_registry.py` | register/load/validate a reference bundle on disk |
| `server_ui_reference_similarity.py` | cell grid, colour/detail lanes, layout lane, pixel diagnostics |
| `server_ui_reference_artifacts.py` | overlay, diff heat map, metrics publishing |
| `server_ui_reference_verdict.py` | scoring, acceptance lanes, decision readiness, next actions |
| `server_ui_reference_compare.py` | orchestration and capture stability |

### Verdict vocabulary

`reference_acceptance` is deliberately not a boolean:

| Value | Meaning |
| --- | --- |
| `passed` | Every declared-required lane passed. Only reachable when the manifest declares semantic/interaction as not required. |
| `failed` | The visual lane failed; region, lane, and layout numbers say where. |
| `blocked` | No trustworthy score exists: not comparable, invalid manifest, unstable capture, or a would-be pass with unproven capture stability. |
| `pending_lanes` | Visual similarity passed while required semantic/interaction lanes are unevaluated. This is the retro's Stage G rule in code. |
| `pending_manual_style` | `owner: human`. Manual styling is a handoff state and is never auto-promoted to acceptance. |

`decision_ready` is reported separately and is false while capture stability is
unproven or the fixture was not reported as established, so a verdict that is
correct today but not reproducible cannot be filed as durable evidence.

### Guardrails implemented from the retro

1. No score for a non-comparable capture — refusal plus recommended resolutions.
2. Masks require an id, a rect, and a stated reason; total mask area is capped at
   25% of the viewport and 50% of any required region, audited in every payload.
3. Visual score is never semantic proof: `acceptance_lanes` always reports
   semantic and interaction as `not_evaluated` with the reason.
4. A pass requires proven capture stability (two captures of the same frozen
   fixture). Waiving it is possible, recorded, and forfeits `decision_ready`.
5. The supplied reference is copied byte-for-byte and hash-pinned; a later edit
   fails validation as `ui_reference_expected_image_hash_mismatch`.
6. `pixel_diagnostics` is reported only when resolutions match, is labelled
   supporting evidence, and never gates the verdict.

## Validation evidence

- `python3 -m unittest discover -s tests`: **517 passed**, 13 platform skips
  (macOS host, 2026-07-30). 41 of those are the new
  `tests/test_ui_reference_acceptance.py`, covering the retro's acceptance matrix
  plus scale invariance, tolerance profiles, and layout findings.
- Production-scale check (synthetic 1440x3200 popup, host timing):
  - same design captured at 1080x2400 -> `passed`, global similarity `0.997`,
    per-region 0.98-1.00, 0.7 s including artifact rendering;
  - wrong illustration colour + body copy not rendered at 1080x2400 -> `failed`,
    illustration 0.10, body 0.59 with `content_moved_or_resized`, global 0.79,
    0.8 s;
  - `comparison_not_comparable` for a 240x420 capture against a 240x480
    reference, with `1440x3200 / 1080x2400 / 720x1600` recommended.
- Parity baselines (`tests/fixtures/server_parity_baseline.json`) regenerated for
  the three new tools and three new CLI commands.

## Remaining slices, in delivery order

| Order | Slice | Status | Done when |
| --- | --- | --- | --- |
| 2 | P0.2 UI fixture contract | planned | A project action/scenario can report `ui_fixture` evidence (fixture id, frozen clock, locale, data source, viewport) that `compare` consumes; live data downgrades decision readiness automatically instead of by convention. |
| 3 | P1.1 prefab validation + uGUI semantic tree | planned | `unity.prefab.validate` fails a missing/obsolete script GUID or an unassignable serialized reference before PlayMode; `unity.ui.tree_snapshot` answers visibility, bounds, text, resolved font/material, and interactability so a failed region can be explained. |
| 4 | P1.2 isolated prefab/Canvas render | planned | A prefab renders at the declared viewport in seconds without app boot and returns the same evidence schema. |
| 5 | P2.1 guarded prefab mutation | planned | Typed patch with preview, atomic Editor apply, binding validation, reversible delta. |
| 6 | P2.2 guarded interaction + P2.3 device lane | planned | Close/CTA paths and device captures carry independent pass/fail evidence. |

P1.1 is what turns a failed region from "these cells differ" into "the Body
`TMP_Text` is active but its font asset did not resolve", which is the diagnosis
the originating incident actually needed.

## Post-implementation self-review

- The comparator is deterministic and explainable end to end: every verdict traces
  to counted cells, named lanes, and declared tolerances. No opaque perceptual
  model is involved.
- The PNG codec is dependency-free by design (stdlib `zlib` only). It refuses
  interlaced, sub-byte-palette, and non-PNG inputs with typed errors rather than
  guessing. Worst-case Paeth unfiltering of a 1440x3200 capture costs ~4 s; the
  normal path measured 0.7-0.8 s per full comparison.
- Residual risk: grid cells are ~11 px at 1440 width, so differences finer than a
  cell (letter-spacing, 1 px borders, font hinting) are below the resolving power
  by construction. That is intentional for the acceptance question being asked,
  and it is stated in the payload whenever a rescaled capture is compared. A
  `strict` profile on a matched resolution remains available when a
  pixel-adjacent gate is wanted.
- Residual gap: the tolerance profiles are calibrated against synthetic screens
  and one production-scale synthetic case. They should be re-checked against real
  Game View captures of a real popup before being treated as portfolio defaults.
