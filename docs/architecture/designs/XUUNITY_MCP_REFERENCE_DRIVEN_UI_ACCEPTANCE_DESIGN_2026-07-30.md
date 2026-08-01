# XUUnity MCP Reference-Driven UI Acceptance Design

Date: `2026-07-30`
Status: `P0.1, P0.2, P1.1, P1.2, P1.3, P2.1, P2.2, P2.3, P3.1, P3.2 implemented; audited externally 2026-07-31, findings closed in v0.3.51`

An independent external audit of this surface found false passes that this document's
own validation section did not: caller-named result files accepted as editor receipts,
a mask policy measuring declared pixels while the comparison suppressed whole grid
cells, a similarity grid that failed the identical design captured at another
resolution, and a single full-screen region diluting a missing element below the
floor. See the `v0.3.51` changelog and `scripts/testing/check_audit_regressions.py`,
which re-runs each finding's reproduction. Read the per-slice validation notes below
as the state at `v0.3.49`, not as an independent verdict.
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
| `server_ui_fixture.py` | fixture readiness contract, receipt extraction, determinism verdict (P0.2) |
| `server_ui_region_explain.py` | failed-region to node stitching, coordinate transform, semantic lane (P1.3) |
| `server_ui_device_lane.py` | device context normalization and the device acceptance lane (P2.3) |

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
unproven or the fixture evidence has any determinism gap, so a verdict that is
correct today but not reproducible cannot be filed as durable evidence.

## Delivered surface (P0.2): the fixture readiness contract

A similarity score answers "does this capture look like the reference". It cannot
answer "would the same capture happen again". P0.2 adds the second question as a
separate, project-owned contract.

### Envelope

`xuunity.ui-fixture.v1` is emitted by a project hook inside its normal payload,
exactly as `xuunity.mutation-delta.v1` already is:

```json
{
  "ui_fixture": {
    "schema_version": "xuunity.ui-fixture.v1",
    "fixture_id": "example_popup_available",
    "state_id": "available_with_timer",
    "data_source": "fixture",
    "payload_hash": "",
    "clock": { "frozen": true, "value_utc": "2026-01-01T00:00:00Z" },
    "locale": { "id": "en", "pinned": true },
    "viewport": { "width": 1080, "height": 2400 },
    "safe_area": "full_screen",
    "ready": { "predicate": "popup_visible_and_idle", "satisfied": true, "waited_ms": 240, "timeout_ms": 5000 }
  }
}
```

The base MCP owns the envelope and the safety rules; projects own their fixtures.
`project-hook-scaffold --ui-fixture` generates a compliant hook whose block ships
**unsatisfied**, so a scaffold that was never filled in validates as `unproven`
rather than silently reporting readiness.

### Two independent verdicts

| Field | Question | False when |
| --- | --- | --- |
| `established` | Did the fixture actually reach the state before the capture? | schema invalid, ready predicate unsatisfied or timed out, or the reporting hook step failed |
| `visual_determinism` | Would the same capture happen again? | anything above, plus live/mixed data without a recorded payload hash, unfrozen clock, unpinned locale, fixture or viewport mismatch against the reference, or caller-asserted evidence |

A fixture can be established and still not deterministic — that is the common
real case (the screen was right, but a live response or a running clock means the
next capture may differ). The two are reported separately so the operator sees
which one is missing.

### Evidence has to be a receipt

`compare` accepts fixture evidence two ways, and they are not equivalent:

- `fixtureResultPath` — a scenario result JSON the editor wrote. The host reads the
  `ui_fixture` block out of the hook step and records a receipt: result path,
  SHA-256, run id, scenario name, step id, hook name, step status. This is the
  only path that can reach `visual_determinism: proven`.
- `fixtureEvidence` — an inline block supplied by the caller. Accepted for
  authoring a hook before a scenario exists, but permanently carries
  `evidence_not_receipt_backed` and can never make a comparison `decision_ready`.

That distinction is the point of the slice: before P0.2 a caller could assert
`established: true` and buy decision readiness with a dict literal.

### Where it surfaces

| Surface | Behaviour |
| --- | --- |
| `unity_ui_fixture_validate` / `ui-fixture-validate` | Validates a report from a scenario result or an inline block; returns the contract itself when no evidence is supplied, so a project can implement the envelope without reading the source. |
| `unity_ui_reference_compare` | Every determinism gap becomes a `fixture_*` entry in `decision_readiness_gaps`, plus a `visual_determinism_unproven` warning and concrete next actions. |
| Scenario hook summaries | `project_defined_hook_summary.hooks[].ui_fixture` reports fixture id, state id, data source, `established`, and the gaps, next to the existing `mutation_delta`. |

## Delivered surface (P1.1): semantic uGUI and prefab read

The comparator can say *a region differs*. It cannot say *why*. P1.1 adds the
read-only semantic surface that answers the second question, on the envelope
already specified in
[`XUUNITY_MCP_READ_ONLY_UI_PRIMITIVES_DESIGN_2026-05-23.md`](XUUNITY_MCP_READ_ONLY_UI_PRIMITIVES_DESIGN_2026-05-23.md)
(`schemaVersion: xuunity.ui.read.v1`, `proofClass`, normalized nodes, AND-combined
selectors, explicit ambiguity and truncation).

| Tool | Purpose |
| --- | --- |
| `unity_prefab_snapshot` | Prefab asset hierarchy as normalized nodes, loaded read-only through `AssetDatabase`. |
| `unity_prefab_validate` | Typed pre-PlayMode defects, so a broken binding is caught before it becomes a blank region in a capture. |
| `unity_ui_tree_snapshot` | Live uGUI hierarchy of the active scene or a named subtree. |
| `unity_ui_query` / `unity_ui_exists` / `unity_ui_get_text` / `unity_ui_get_bounds` | Selector-driven reads over that same node model. |

### Two deviations from the 2026-05-23 design, both deliberate

1. **uGUI first, UI Toolkit later.** The originating incident and the whole
   reference-acceptance loop are uGUI. Phase 1 there proposed UI Toolkit first;
   this ships the phase-2 backend first because it is the one that unblocks the
   acceptance question.
2. **Flat node list, not nested `children`.** `JsonUtility` — the serializer every
   operation in this package uses — cannot serialize a self-referencing type. Nodes
   therefore carry `path`, `parent_path`, `depth`, `sibling_index`, and
   `child_count`; the tree is reconstructable by the host and truncation stays
   explicit per node (`children_truncated`). A repo test pins this so the shape is
   not "fixed" back into a recursion that would silently truncate at depth 7.

### Optional backends without a package dependency

The core editor assembly declares **zero** package references, and the design has
to keep it that way: a project without `com.unity.ugui` must still compile the MCP.
So component-level detail comes through a registry seam
(`IXUUnityLightMcpUiComponentReader`) filled by two constraint-gated satellite
assemblies, using the pattern the Test Framework module already established here:

| Assembly | Gate | Adds |
| --- | --- | --- |
| `com.xuunity.light-mcp.Editor` | none | hierarchy, active state, CanvasGroup alpha chain, raycast blocking, canvas order, screen bounds, prefab defects |
| `…Editor.Ugui` | `com.unity.ugui` | `Text`/`InputField` text, resolved font, `materialForRendering`, `Selectable.IsInteractable`, `Graphic` alpha, `RectMask2D` clip state |
| `…Editor.Tmp` | `com.unity.ugui ≥ 2.0.0` or `com.unity.textmeshpro ≥ 3.0.0` | `TMP_Text` text, resolved font asset and shared material, TMP alpha |

When no reader is registered the surface does not fail — it reports
`proof_class: semantic_ui_partial`, a `ui_component_details_unavailable` warning
with the remedy, and `lanes_not_evaluated: [unresolved_font_or_material]` on
prefab validation. Degraded evidence is labelled, never disguised as complete.

## Delivered surface (P1.3): joining the visual and semantic lanes

P0.1 could say *this region differs*; P1.1 could say *this node's font did not
resolve*. Nothing joined them. `compare` now takes `uiSnapshotPath` and stitches
the two automatically.

### The transform is the whole risk

Unity's screen bounds are **bottom-left origin, in capture pixels**. Reference
regions are **top-left origin, in reference-viewport pixels**. Getting that wrong
produces confident, precisely wrong explanations — worse than none. The mapping is
therefore explicit, recorded in `coordinate_transform` on every payload, and pinned
by tests that assert a bottom-left node lands bottom-left and a top-of-screen node
lands at `y = 0`:

```
ref_x = x * reference_width / capture_width
ref_y = (capture_height - (y + height)) * reference_height / capture_height
```

The capture viewport is read from the snapshot itself (`target.capture_width/height`,
added in P1.3), not assumed. If the snapshot was taken at a different resolution than
the compared capture, that is a warning, not a silent rescale; if the snapshot records
no viewport, the fallback is stated as `ui_snapshot_viewport_assumed`; and a prefab
snapshot with no screen bounds refuses to stitch rather than inventing geometry.

### What a failed region now returns

Each failed region gains `explained_by`: candidate nodes ranked by defect count then
coverage, each with `region_coverage`, `node_coverage`, and a `suspicions` list drawn
from `missing_script_component`, `font_unresolved`, `material_unresolved`,
`empty_text`, `inactive`, `alpha_zero`, `fully_clipped`, `partially_clipped`. The
highest-priority suspicion becomes `likely_cause`, and the summary is plain language:

> `'Canvas/Body' overlaps this region and its font asset did not resolve.`

Two negative cases matter as much as the positive one. **No node covers the region** →
"the screen renders nothing where the reference expects content", which is itself the
finding. **Every covering node is healthy** → "the difference is visual (wrong sprite,
colour, or layout), not a broken binding", which stops the operator hunting for a
binding bug that does not exist.

### The semantic lane stops being a placeholder

With a snapshot present, the reference's declared `required_ui` selectors are checked
against it, so `acceptance_lanes.semantic` reports `passed`/`failed` with typed
failures instead of a permanent `not_evaluated`. A required-lane failure fails the
reference **even when the pixels match** — a screen can be pixel-correct and still be
missing the component the design requires.

## Delivered surface (P1.2): isolated prefab render

`unity_prefab_render` opens a preview scene (`EditorSceneManager.NewPreviewScene`),
builds a controlled Canvas and orthographic camera sized to the declared viewport,
applies safe-area insets as a RectTransform inset, instantiates the prefab, forces a
layout rebuild, renders to a `RenderTexture`, and writes a PNG — with no application
boot and no change to any open scene. Everything is created `HideAndDontSave` and torn
down in a `finally`, and the preview scene is always closed.

Because the canvas is `ScreenSpaceCamera` against that camera, the snapshot returned
alongside the PNG is already in **render-pixel space at the declared viewport**, so it
feeds straight into `compare`'s `uiSnapshotPath` with the transform reduced to
identity. That is the loop the retro asked for: render → compare → explain, in
seconds, without a 30–45 s boot.

## Delivered surface (P2.1): guarded prefab mutation

`unity_prefab_mutate` is a typed transaction, never raw YAML. It loads prefab contents
through `PrefabUtility.LoadPrefabContents`, applies the operations in order, and only
then decides whether anything is written.

| Guardrail | Behaviour |
| --- | --- |
| Preview by default | `previewOnly` defaults true, and `approve=false` forces preview regardless — the delta is returned without touching the asset. |
| Atomic | Any failing operation aborts the batch; the asset is byte-identical afterwards (asserted by test). |
| Re-validated | The mutated contents are run through the P1.1 prefab validator; failed bindings discard the batch instead of saving. |
| Reversible | An inverse patch (`xuunity.prefab-mutation-patch.v1`) with before-values and the pre-mutation hash is emitted. |
| Stale-safe | An optional `expectedSha256` precondition refuses a transaction built against an older version of the file. |
| Unambiguous | A selector matching more than one object is refused, never resolved by "first match". |
| Type-safe | Object-reference fields are out of scope entirely, so no operation can swap a component for a different type. |
| Allowlisted | `add_component`/`remove_component` only touch a layout allowlist plus whatever the caller explicitly allows for that transaction. |

## Delivered surface (P2.2): guarded semantic interaction

`unity_ui_click` requires `approve=true` and the explicit action `click`, resolves a
**unique** selector, and delivers through `ExecuteEvents` on the EventSystem. It
refuses — before delivering anything — an ambiguous selector, a hidden target, a
non-interactable target, a target whose CanvasGroup does not block raycasts, and a
target with no `IPointerClickHandler` in its ancestry. The response records the matched
node, the handler that received the event, the delivery mechanism, and before/after
snapshot signatures so a state change is evidence rather than assumption. Coordinate
clicks and OS automation are not offered.

## Delivered surface (P2.3): device lane

`captureLane` is `game_view` or `device`. A device capture must declare model, OS,
resolution, orientation, and build revision; an incomplete descriptor **blocks** the
device lane rather than passing it, and a missing safe-area declaration is warned
because notch differences would otherwise be indistinguishable from layout defects.
A Game View comparison always reports `acceptance_lanes.device` as `not_evaluated`
with the reason — Game View parity is structurally incapable of claiming device
parity.

## Delivered surface (P3.1): the AI-vision lane

A cell-similarity score is blind to whole classes of "wrong screen". It cannot see a
placeholder icon in the right place at the right average colour, a different type family
at the same weight, or a mirrored arrangement whose cells average out. So acceptance
gained a fourth lane where a multimodal judge answers the question the grid cannot:
**is this recognisably the same screen, in style, placement, and size?**

`unity_ui_vision_packet` renders one side-by-side sheet — reference left, candidate right,
scaled to a shared panel height so a resolution difference is not read as a design
difference — and outlines the failed regions on both panels. It ships the rubric with it.
`unity_ui_vision_submit` records the judgement and returns the lane.

Four properties make this evidence rather than an opinion:

1. **Bound to one image pair.** `packet_hash` covers both image digests, the reference id,
   and the bar. Change either capture and every prior review is rejected as
   `vision_packet_stale` — a review cannot silently outlive what it judged.
2. **The arithmetic is checked.** Every required criterion needs a score *and* a one-line
   observation, and the overall score is clamped to `worst_required + 1`. A judge cannot
   claim a strong overall while scoring layout as wrong.
3. **Provenance is recorded.** `judge.role` is `authoring_agent`, `independent_agent`, or
   `human`. A self-review is stored and counted but permanently flagged
   `vision_review_self_reviewed_only`; the agent that wrote the UI is not independent
   evidence that the UI is right.
4. **Not anchored.** Numeric scores are withheld from the packet by default. Failed regions
   are marked so the judge knows where to look, but a judge told "the grid said 94%" is
   measurably less useful than one who looked first.

The bar moves with the same profile dial as the numeric comparison (`strict`/`balanced`/
`lenient`) and can be overridden per reference through `vision_policy`, including waiving a
criterion — `typography` is legitimately out of scope when the fonts differ by design. **No
profile requires the top score.** Pixel equality is not the acceptance bar in this lane
either, by construction.

### Disagreement is the most useful output

The two lanes measure different things, so their disagreement carries information neither
carries alone:

| Grid | Review | Verdict | Signal |
| --- | --- | --- | --- |
| passed | failed | `failed` | `vision_contradicts_similarity` — trust the review; the grid cannot see this class of defect |
| failed | passed | `failed` | `similarity_may_be_over_strict` — with a named looser profile that would have passed |

The second row is the one that matters for a standing constraint of this design: the
acceptance bar must be adjustable and sane. When a judge says the screen is recognisably
right and the number says otherwise, the tool now names the profile that matches the
observed similarity instead of leaving the operator to guess — and says to change it on the
reference deliberately, not per comparison.

## Delivered surface (P3.2): interaction lane from a Play-mode receipt

P2.2 delivered a guarded click, but the comparison verdict still hardcoded
`interaction: not_evaluated`, because a click delivered from the Edit-mode operation proves
handler wiring, not a running user path. The lane is now real, and it is fed the same way
the fixture lane is: by a receipt the editor wrote.

A new scenario step kind `ui_click` delivers the click inside a Play-mode scenario and emits
a `xuunity.ui-interaction.v1` block into the step payload. The step lives in the core
assembly and reaches `unity.ui.click` **by operation name**, so a project without
`com.unity.ugui` gets a clear unavailable-operation failure rather than a compile break. It
requires `interactionId` and `approve=true` in the scenario JSON, so the guard is visible in
the artifact a reviewer reads.

`required_interactions` on the reference declares what must be proven
(`[{id, selector, expect:{delivered, state_changed}}]`), and `interactionResultPath` on the
comparison reads the receipt — defaulting to `fixtureResultPath`, so **one Play-mode run can
establish the fixture and prove the interactions**.

The distinction that gives the lane its value:

- delivered in Play mode, expectations met → lane `passed`;
- delivered in Edit mode → lane **`blocked`**, never `passed`. `runtime_proven` is false and
  the reason says why. Blocking is the honest verdict: the wiring works, the user path is
  unproven;
- refused, undelivered, or delivered with no state change → lane `failed`, because that is
  evidence of a broken path rather than a missing measurement.

### An optional lane that ran and failed still fails

Adding two lanes exposed a latent looseness: `failed_lanes` only counted lanes marked
`required`, so an `optional` lane that was actually evaluated and failed was silently
ignored. That conflates two different questions. `optional` now means "you do not have to
run it"; it does not mean "its failures do not count". Only `not_required` opts a lane out of
the verdict. The vision lane defaults to `optional` for exactly this reason — the host cannot
summon a judge, so it must not block, but a review that was submitted and failed is a real
failure.

### Guardrails implemented from the retro

1. No score for a non-comparable capture — refusal plus recommended resolutions.
2. Masks require an id, a rect, and a stated reason; total mask area is capped at
   25% of the viewport and 50% of any required region, audited in every payload.
3. Visual score is never semantic proof: `acceptance_lanes` reports each lane's own
   status and reason, and an unevaluated required lane keeps acceptance out of `passed`.
4. A pass requires proven capture stability (two captures of the same frozen
   fixture). Waiving it is possible, recorded, and forfeits `decision_ready`.
5. The supplied reference is copied byte-for-byte and hash-pinned; a later edit
   fails validation as `ui_reference_expected_image_hash_mismatch`.
6. `pixel_diagnostics` is reported only when resolutions match, is labelled
   supporting evidence, and never gates the verdict.

## Validation evidence

- `python3 -m unittest discover -s tests`: **532 passed**, 13 platform skips
  (macOS host, 2026-07-30). 56 of those are the new
  `tests/test_ui_reference_acceptance.py`, covering the retro's acceptance matrix
  plus scale invariance, tolerance profiles, layout findings, and the P0.2 fixture
  contract (receipt versus assertion, live-data downgrade, ready-predicate timeout,
  failed hook step, schema rejection, scenario-summary surfacing, scaffold
  fail-closed).
- Production-scale check (synthetic 1440x3200 popup, host timing):
  - same design captured at 1080x2400 -> `passed`, global similarity `0.997`,
    per-region 0.98-1.00, 0.7 s including artifact rendering;
  - wrong illustration colour + body copy not rendered at 1080x2400 -> `failed`,
    illustration 0.10, body 0.59 with `content_moved_or_resized`, global 0.79,
    0.8 s;
  - `comparison_not_comparable` for a 240x420 capture against a 240x480
    reference, with `1440x3200 / 1080x2400 / 720x1600` recommended.
- Parity baselines (`tests/fixtures/server_parity_baseline.json`) regenerated for
  the eleven new tools and four new CLI commands.
- P1.1 was validated in a real editor, not only by compile. Two throwaway Unity
  `6000.0.58f2` projects mount the package by path:
  - **with `com.unity.ugui`**: all three assemblies compile; `-runTests -testPlatform
    EditMode` over the package self-test category reports **47 passed, 0 failed**,
    including 17 new UI-read tests (canvas hierarchy and paths, screen bounds,
    CanvasGroup alpha, explicit truncation, typed target-not-found, selector
    ambiguity, prefab pass/blocked/invalid-path, unassigned-reference opt-in) and 6
    uGUI reader tests (text, resolved font/material, non-interactable `Selectable`,
    alpha-0 graphic, `get_text`, text and interactability selectors).
  - **without `com.unity.ugui`**: only `com.xuunity.light-mcp.Editor.dll` is built,
    the two satellite assemblies are skipped by their define constraints, and the
    import exits with zero compile errors.
- That editor run earned its keep twice: it caught `internal` seam types being
  invisible to the satellite assemblies (fixed with `InternalsVisibleTo`), and an
  ordering bug where component readers ran before the alpha/bounds pass, so a
  fully transparent `Graphic` reported `effective_alpha: 1.0` and clip detection
  never saw bounds. Both were invisible to static review.
- P1.2/P1.3/P2.x were validated the same way. The package self-test suite is now
  **70 EditMode tests, all passing** in Unity `6000.0.58f2` with uGUI and TMP, and
  the core-only project without `com.unity.ugui` still imports with zero compile
  errors and only `com.xuunity.light-mcp.Editor.dll` built.
- Rendered pixel content is verified, not assumed: the render test decodes its own
  PNG and asserts the prefab's blue `Image` dominates the centre pixel. Under
  `-nographics` there is no graphics device, so that test declares itself ignored
  rather than passing vacuously; it was run separately **with** a graphics device
  (11/11 passed) to prove the pixels are real.
- Host side: **575 tests passing**, including 26 that pin the region/node coordinate
  transform, the semantic lane verdicts, and the device lane, plus 17 cross-language
  contract tests that hold the Python/C# seam (every declared `bridgeOperation`
  resolves to a registered editor operation, the uGUI-only operations are owned by
  the constraint-gated assembly, mutation never reaches for raw YAML or object
  references, and the click path keeps all seven refusals).

### P3.1/P3.2 validation

- Host: **634 tests ran — 621 passed, 13 platform skips**. 59 are the new
  `tests/test_ui_vision_and_interaction.py`: the rubric clamp, per-profile bars, packet
  staleness, judge provenance and self-review flagging, judge disagreement, the sheet
  geometry (reference left, shared panel height, markers on both panels, decodable PNG with
  each panel's own colour at its centre), the interaction contract's edit-mode downgrade,
  the lane verdicts, and a packet -> judge -> submit -> compare round trip over real files.
- The round-trip test earned its keep immediately: storing the *normalized* review made it
  fail re-normalization on the next comparison, because the normalized record carries
  `contract_version` and not `schema_version`. Every submitted review was silently invalid
  as soon as it was read back. Fixed by storing a canonical submission block alongside the
  evaluated record, with an idempotency test pinning it. Unit tests on the normalizer alone
  would never have found this.
- Editor: validated on **two Unity versions**, same result on both — `2021.3.45f2` and
  `6000.0.58f2`, **78 EditMode tests, 77 passed, 0 failed**, 1 correctly ignored (the pixel
  test declaring itself unrunnable without a graphics device). Seven of those are the new
  `ui_click` scenario-step tests: validator refusals for a missing id / missing approval /
  empty selector, the step's own approval refusal, the emitted `ui_interaction` receipt with
  differing before/after signatures, the `edit` play-mode report, the no-state-change
  failure, and refusal pass-through.
- Run separately **with** a graphics device: 11/11 render/click tests passed.
- Core-only project without `com.unity.ugui`: **zero compile errors**, only
  `com.xuunity.light-mcp.Editor.dll` built. The `ui_click` step handler lives in the core
  assembly and reaches the click by operation name, so the satellite gating still holds.
- Cross-language contract tests were extended to hold the new seam: the interaction schema
  version and step-kind string must match between `XUUnityLightMcpUiRead` and the host
  scenario schema, the step must be dispatched *and* validated in the editor package, and
  approval must be required in both layers.

## Remaining slices, in delivery order

| Order | Slice | Status | Done when |
| --- | --- | --- | --- |
| 2 | P0.2 UI fixture contract | shipped 2026-07-30 | A project action/scenario reports `ui_fixture` evidence that `compare` reads from the editor-written scenario result; live data, a running clock, an unpinned locale, or caller-asserted evidence downgrade decision readiness automatically instead of by convention. |
| 3 | P1.1 prefab validation + uGUI semantic tree | shipped 2026-07-30 | `unity.prefab.validate` fails a missing/obsolete script GUID or an unassignable serialized reference before PlayMode; `unity.ui.tree_snapshot` answers visibility, bounds, text, resolved font/material, and interactability so a failed region can be explained. |
| 4 | P1.3 region/node stitching + semantic lane | shipped 2026-07-30 | A failed region names the nodes covering it and the likely cause; declared `requiredUi` selectors decide the semantic lane instead of a permanent `not_evaluated`. |
| 5 | P1.2 isolated prefab/Canvas render | shipped 2026-07-30 | A prefab renders at the declared viewport in seconds without app boot, in an isolated preview scene, and returns the same evidence schema plus its own snapshot. |
| 6 | P2.1 guarded prefab mutation | shipped 2026-07-30 | Typed transaction with preview-by-default, atomic Editor apply, post-mutation binding validation, rollback on any failure, and a reversible inverse patch. |
| 7 | P2.2 guarded interaction | shipped 2026-07-30 | `unity.ui.click` delivers once through the EventSystem to a unique selector and refuses ambiguous, hidden, disabled, raycast-transparent, and handler-less targets. |
| 8 | P2.3 device lane | shipped 2026-07-30 | A device capture is a separate lane carrying model/OS/resolution/orientation/safe-area/build revision; Game View parity never claims device parity. |
| 9 | P3.1 AI-vision lane | shipped 2026-07-30 | A multimodal judge rules on style/placement/size against a side-by-side sheet under a checked rubric, bound to one image pair, with judge role recorded; disagreement with the grid names which lane to trust and, when the number is the stricter one, which profile matches. |
| 10 | P3.2 Play-mode interaction lane | shipped 2026-07-30 | A `ui_click` scenario step delivers the click in Play mode and writes a `ui-interaction.v1` receipt; `required_interactions` decides the lane, and Edit-mode delivery blocks it instead of passing. |

P1.1 produced that diagnosis; P1.3 joins it to the comparator automatically, so a
failed region arrives already named. The originating incident is now answerable
end to end: render the prefab in isolation, compare it against the reference,
and read which node explains the failing region — without booting the app.

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
