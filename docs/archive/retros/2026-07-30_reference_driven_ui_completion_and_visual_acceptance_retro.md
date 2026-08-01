# XUUnity Light Unity MCP Retro — Reference-Driven UI Completion and Visual Acceptance

Date: `2026-07-30`

Status: `implemented public retro — every P0/P1/P2 slice shipped 2026-07-30`

Implementation: [`XUUNITY_MCP_REFERENCE_DRIVEN_UI_ACCEPTANCE_DESIGN_2026-07-30.md`](../../architecture/designs/XUUNITY_MCP_REFERENCE_DRIVEN_UI_ACCEPTANCE_DESIGN_2026-07-30.md)
carries the full delivered slice set (reference contract + comparator, fixture
readiness contract, uGUI semantic tree + prefab validation, region/node stitching,
isolated render, guarded mutation, guarded click, device lane) and the residual
delivery order. One correction to this retro's framing: acceptance is deliberately
**not** pixel equality. The Game View resolution in Play mode is switchable and will
differ from a supplied reference, so the comparator scores human-visible similarity —
colour, detail, placement, size — on a resolution-independent grid with configurable
tolerance profiles.

Scope: `Operations/XUUnityLightUnityMcp`; public-safe lessons from a Unity
feature session that began from supplied mobile UI reference screenshots and
ended with a technically valid, but visually non-matching, Game View result.

## Related existing UI MCP work

This is a continuation of the existing UI MCP work, not a parallel initiative.
The linked artifacts already identify the missing semantic UI, prefab, render,
and PlayMode-evidence foundations. This retro adds the still-missing final
acceptance loop: a supplied visual reference, a deterministic UI state, and a
truthful comparison verdict over the resulting render.

| Existing artifact | Established scope / status | What this retro adds |
| --- | --- | --- |
| [Prefab/UI authoring and visual-iteration gap retro](2026-07-17_prefab_ui_authoring_and_visual_iteration_gap_retro.md) | Identifies missing prefab structure read, guarded mutation, and isolated prefab/Canvas render; snapshot and typed mutation have partial follow-through, while authoring/render remain open. | Makes those primitives serve a concrete reference-driven acceptance loop, with canonical fixture state and expected/actual/overlay evidence. |
| [UI PlayMode smoke operator-speed retro](2026-06-16_ui_playmode_smoke_operator_speed_retro.md) | Defines semantic verdicts, user-path coverage, readiness classification, fixtures, and cleanup for honest runtime UI smoke. | Adds a visual-reference gate after the runtime path is proven, so a green PlayMode scenario cannot be mistaken for design acceptance. |
| [UI primitives design](../../architecture/designs/XUUNITY_MCP_UI_PRIMITIVES_DESIGN_2026-05-12.md) | Proposes safe semantic UI read/action contracts such as query, text/state read, waiting, and click. | Connects semantic inspection to visual diagnosis: it must identify which element, text, bounds, or asset explains a visual mismatch. |
| [Read-only UI primitives design](../../architecture/designs/XUUNITY_MCP_READ_ONLY_UI_PRIMITIVES_DESIGN_2026-05-23.md) | Defines the first uGUI-first read-only tree/query/exists/get-text surface; status remains design, not implementation. | Requires its output to include the semantic facts needed to bound a reference mismatch before action or mutation is attempted. |
| [ReferenceWatch design](../../../../../Modules/AIReferenceWatch/design/XUUNITY_MCP_REFERENCE_WATCH_DESIGN_2026-05-12.md) | Establishes the reference-first evidence, provenance, comparison, and explicit decision-loop discipline for public MCP capability design. | Applies the same discipline to a user-supplied UI design image; this is not competitor tracking or a replacement for ReferenceWatch. |
| [MCP roadmap](../../architecture/ROADMAP.md) | Tracks the broader snapshot, mutation, and scenario-validation direction. | Prioritizes the concrete dependency order needed to finish a screenshot-driven UI task end to end. |

The earlier combined pointer, [UI primitives and ReferenceWatch design](../../architecture/designs/XUUNITY_MCP_UI_PRIMITIVES_AND_REFERENCE_WATCH_DESIGN_2026-05-12.md), remains useful for historical routing. None of the existing artifacts supplies a P0 expected-versus-actual render comparator or a final reference-match verdict; that is the specific gap this retro owns.

## 1. Executive verdict

**The current MCP can prove that a Unity UI flow ran; it cannot prove that the
rendered screen matches a supplied design reference.**

The existing workflow has strong evidence for compilation, prefab import after
refresh, PlayMode entry/exit, network breadcrumbs, and Game View capture. It
does not have a durable reference-image contract, a deterministic UI state,
semantic uGUI inspection, isolated render, visual comparison, or a final
acceptance verdict tied to the reference. Consequently a green scenario can
coexist with obvious visual defects: wrong scale, unrendered text, incomplete
spacing, incorrect sprites, or a button that is visible but not interactable.

This is not an image-model quality problem. It is a **missing closed-loop
product-validation system**. The current capture operation is evidence for a
human; it is not an acceptance gate for an agent.

The target state is explicit:

> A reference-driven UI task is not complete until a reproducible canonical UI
> state has a semantic and visual acceptance report against the supplied
> reference, with expected/actual/overlay artifacts and a passed verdict.

## 2. Incident evidence

The session provided a 1440×3200 mobile reference for a reward popup and
requested that the resulting UI match it. The actual validation lane was able
to do the following correctly:

- refresh Unity and establish `post_settle_compile=passed`;
- compile Android player scripts;
- enter a fresh consumer-project Dev PlayMode session;
- load live feature data and log the two service calls the flow depends on;
- capture a 1440×3200 Game View screenshot;
- exit PlayMode cleanly.

It also exposed a real import/runtime break: `CloseButton` had an obsolete UGUI
`Button` script GUID, which produced a missing component and a null reference
when the presenter subscribed to it. Correcting the GUID repaired the runtime
path. This proves that compile success alone is insufficient for prefab
correctness.

However, the captured UI still materially differed from the reference:

- the popup illustration and card proportion differed;
- the body copy was not rendered;
- the layout contained a large empty region;
- typography, spacing, and state styling were not accepted against the
  reference;
- no automated action exercised the close button or CTA;
- the user ultimately took ownership of manual visual styling.

The final technical scenario passed, but no truthful reference-match verdict
could be issued. The correct end state was **functional flow passed; visual
acceptance pending**, not “the reference is implemented.”

## 3. What worked

| Capability | Evidence | Value |
| --- | --- | --- |
| Refresh/compile gate | Refresh reported zero compiler errors; Android script compile passed | Prevented shipping a source-level regression. |
| PlayMode lifecycle | Fresh enter, wait, capture, exit, and return-to-Edit all passed | Produced reproducible runtime evidence. |
| Runtime breadcrumbs | Feature logs showed the server sequence and reward-ready state | Distinguished flow/data failure from visual failure. |
| Game View capture | Captured the target 1440×3200 viewport | Made the visual discrepancy observable. |
| Human visual review | Screenshot exposed the unrendered body label and incorrect geometry | Caught issues not visible to compile/test tools. |

The existing Game View screenshot capability is therefore necessary. It is
simply not sufficient as the only UI validation primitive.

## 4. What failed in the process

### 4.1 The acceptance condition silently changed from visual parity to technical execution

The work began with a supplied visual reference, but the operational pass
condition became “scenario passed.” That is a category error:

```
compile passed + runtime flow passed + screenshot captured
!=
reference UI accepted
```

The screenshot was treated as an observation after the decision rather than as
an input to the decision. A design task needs the inverse ordering: a visual
comparison is the final gate, while compile and runtime are prerequisite gates.

### 4.2 The reference was not converted into an executable contract

The supplied screenshot had no durable manifest that bound:

- the immutable source image and content hash;
- canonical viewport, orientation, DPI policy, and safe-area policy;
- the exact product state to render (available reward, active boost, cooldown,
  error, etc.);
- required text, dynamic-value substitutions, and permitted variability;
- regions that must be compared and regions that may be masked;
- visual thresholds and the person/team owning an intentional deviation.

Without this, a screenshot can guide a human but cannot be replayed by an
agent, a CI lane, or a later developer.

### 4.3 There was no deterministic state for the screen under review

The visual proof depended on login, live Dev server responses, ad readiness,
and time. The feature contains a timer and server-selected milestone, so this
is particularly fragile. The session had no project hook/fixture that could
atomically set:

- an available reward with a known duration and reward action;
- active boost with a fixed remaining duration;
- cooldown state with a fixed unlock duration;
- known ad unit and rewarded-video readiness;
- frozen or controllable clock;
- popup already opened at a selected screen location.

A test cannot compare pixels meaningfully while its state, time, localization,
or network data changes between captures.

### 4.4 The MCP has no semantic uGUI truth surface

Current `unity.scene.snapshot` is a lightweight active-scene snapshot. It is
not a prefab snapshot, uGUI tree snapshot, component/serialized-field reader,
or screen-bounds inspector. It cannot answer the questions that mattered here:

- Is the `Body` `TMP_Text` active, enabled, visible, and non-empty?
- Which font/material is resolved, and is it missing?
- What are its calculated screen-space bounds, alpha, clipping, and sibling
  draw order?
- Does `CloseButton` contain a valid `Button`, and is the serialized presenter
  reference assignable to that component?
- Is the CTA interactable after the popup is presented?
- Which `RectTransform` produces the oversized/offset visual?

The current archived read-only UI design acknowledges this gap, but it remains
unimplemented and has not yet established a uGUI-first provider.

### 4.5 Raw prefab YAML was an unsafe substitute for UI authoring and validation

The workflow fell back to serialized YAML inspection/editing. That creates two
failure modes that C# compilation does not catch:

1. stale or invalid script/component GUIDs;
2. field references that deserialize to `null` or to an incompatible component.

The `CloseButton` incident was a concrete example. A structured prefab import
and binding validator would have reported the defect before a runtime event
subscription reached it.

### 4.6 There was no isolated render loop

The only visual preview was a complete game boot followed by a Game View
screenshot. That combines visual validation with loading, login, timing, data,
and advertisement state. It makes each iteration slow and makes every mismatch
ambiguous. For reference work, the operator needs to render one prefab or
Canvas subtree in seconds, at the reference viewport, against a controlled
background.

### 4.7 No visual-comparison or overlay artifact existed

The tool produced one actual screenshot only. It did not produce:

- a normalized expected image;
- an actual image with identical dimensions;
- a transparent expected/actual overlay;
- a heat map or region-level difference report;
- an explicit threshold result;
- an artifact that identifies the first visual mismatch.

An agent can visually inspect images, but repeated subjective inspection is not
a reliable end-to-end completion protocol. It also cannot distinguish intended
dynamic differences from regressions without a declared mask policy.

### 4.8 Interaction coverage stopped at “button is present”

The existing scenario steps do not expose a guarded semantic `ui.click` or
pointer-injection primitive. The feature therefore lacked proof that the close
button closes the popup, the CTA follows the intended branch, or the disabled
cooldown button rejects input. Presence in a screenshot is not proof of
interaction.

### 4.9 Manual ownership was not represented as an acceptance boundary

When a designer/developer takes over font, colour, or layout work, that is a
valid scope decision. The toolchain needs a first-class state such as
`visual_owner=human` and `reference_acceptance=pending_manual_style`. It must
not let a later generic “passed” report imply completed visual parity.

## 5. Capability gap map

| Needed outcome | Current support | Gap | Priority |
| --- | --- | --- | --- |
| Preserve a supplied reference as test input | None | No reference manifest, hash, viewport, masks, or ownership | P0 |
| Render a known UI state repeatedly | Project-specific ad hoc hooks only | No canonical UI fixture/clock/network-state contract | P0 |
| Decide visual parity | Screenshot only | No comparator, regions, threshold, overlay, or pass/fail verdict | P0 |
| Explain a mismatch | Human image review only | No semantic uGUI tree, bounds, text, material, clipping, or visibility read | P1 |
| Catch prefab binding errors pre-runtime | Refresh/import logs only | No structured unresolved/missing/incompatible serialized-reference validator | P1 |
| Iterate a popup quickly | Full boot + screenshot | No isolated prefab/Canvas renderer | P1 |
| Change UI safely | Raw YAML or manual Editor work | No typed, transactional prefab patch surface | P2 |
| Prove button behaviour | Screenshot/presenter logs | No selector-based guarded click and post-action assertion | P2 |
| Prove mobile rendering | Editor Game View only | No device-safe-area and device screenshot acceptance lane | P2 |

## 6. Required reference-driven UI acceptance protocol

The following protocol should be the default whenever a user provides a UI
screenshot, Figma export, or pixel-level visual target.

### Stage A — Reference intake (must happen before editing)

Create a versioned `ui-reference.v1` manifest outside the Unity asset tree or
in an explicitly approved test-artifact location. It contains:

```json
{
  "reference_id": "flying-gift-available-v1",
  "expected_image": "Artifacts/UIReference/RewardPopup/available.png",
  "sha256": "...",
  "viewport": { "width": 1440, "height": 3200, "orientation": "portrait" },
  "safe_area": "full_screen",
  "fixture": "flying_gift.available",
  "regions": [
    { "id": "popup", "required": true, "weight": 5 },
    { "id": "illustration", "required": true, "weight": 4 },
    { "id": "title", "required": true, "weight": 4 },
    { "id": "body", "required": true, "weight": 4 },
    { "id": "cta", "required": true, "weight": 4 }
  ],
  "dynamic_masks": [],
  "required_ui": [
    { "selector": "Popup/Title", "text": "Boost Earnings!" },
    { "selector": "Popup/PrimaryButton", "interactable": true }
  ],
  "owner": "agent",
  "acceptance": { "visual": "required", "semantic": "required", "interaction": "required" }
}
```

The original reference must never be silently resized, recompressed, or
overwritten. Derived normalized images are separate, hash-linked artifacts.

### Stage B — Canonical fixture and freeze

Before capture, run a project-provided fixture that establishes the exact state
named by the manifest. The fixture must report its state and freeze all
render-relevant variables: time, timer value, locale, safe area, network/model
payload, and ad readiness. It must be possible to recreate it from a clean
editor session without live server dependence.

If the feature cannot be fixture-driven yet, the visual result is
`reference_acceptance=blocked_nondeterministic`, not passed.

### Stage C — Structural/prefab validation

Validate the prefab prior to PlayMode:

- no missing scripts/components;
- serialized references resolve and are assignable to the declared field type;
- all required `TMP_Text`, `Image`, `Button`, and `CanvasGroup` nodes exist;
- required assets/materials/font assets resolve;
- RectTransform/canvas configuration is reported;
- no forbidden default/placeholder visual is left in a required region.

### Stage D — Semantic UI validation

Render the fixture and query a normalized UI tree. Assert visibility,
screen-space bounds, text, interactability, and expected component state. This
proves facts a screenshot cannot: for example, that a hidden body label is not
mistaken for “white text on white background,” and that a visible close icon is
backed by a valid clickable component.

### Stage E — Visual acceptance

Capture at the exact declared viewport, normalize using the manifest policy,
and run a region-aware comparison. It must publish:

- `expected.png`, `actual.png`, and `overlay.png`;
- `diff.png`/heat map;
- global and region scores;
- detected bounding boxes for meaningful mismatch clusters;
- mask application record;
- a clear `reference_acceptance=passed|failed|blocked` verdict.

The visual tool must reject dimension/orientation/safe-area mismatch before
computing an attractive but meaningless score. It must first establish capture
stability by comparing two consecutive captures of the same frozen fixture.

### Stage F — Interaction acceptance

From semantic selectors, invoke only explicitly permitted UI actions and assert
the resulting state. For this type of popup: close, CTA, disabled cooldown
state, and active-boost CTA must each have an expected before/after UI tree and
optional reference image.

### Stage G — Final decision

The report can call the work visually complete only when all declared required
lanes pass:

```
compile/import pass
AND fixture established
AND semantic UI pass
AND visual reference pass
AND required interaction pass
```

Any human-owned visual work creates an explicit non-passing handoff state,
never a generic success.

## 7. Proposed MCP capability slices

### P0.1 — Reference manifest and visual comparison contract

Add a host-side tool family that treats reference images as controlled test
inputs, not prompt attachments:

- `unity.ui.reference.register`
- `unity.ui.reference.validate`
- `unity.ui.reference.compare`

`compare` inputs: reference id/path, actual capture, declared viewport,
optional approved masks, and region definitions. Output: compact verdict plus
an artifact manifest for expected/actual/overlay/diff/metrics. It must be
read-only with respect to Unity assets.

This first slice should use deterministic, explainable image operations. A
perceptual score may be supplemental, but no opaque score is allowed to be the
only decision signal. Each failure must name the failed region and expose the
diff artifact. Thresholds are explicit per reference, never global magic.

### P0.2 — Fixture/readiness contract for UI states

Extend project action/scenario contracts with an opt-in `ui_fixture` result:

- fixture id and semantic state id;
- frozen clock and locale status;
- data source (`fixture`, `live`, `mixed`);
- resolved viewport/safe-area;
- ready predicate and timeout evidence;
- whether the resulting visual comparison is decision-ready.

The base MCP should define the envelope and safety rules; individual projects
own their fixtures. A live network response must downgrade the result to
`visual_determinism=unproven` unless the project explicitly records an immutable
fixture payload/hash.

### P1.1 — uGUI-first semantic tree and prefab snapshot

Implement the pending read surface for uGUI before generic UI Toolkit work:

- `unity.prefab.snapshot` by project-relative prefab path;
- `unity.prefab.validate` for missing scripts and serialized bindings;
- `unity.ui.tree_snapshot` for the active scene or a named Canvas subtree;
- `unity.ui.query`, `unity.ui.exists`, `unity.ui.get_text`, and
  `unity.ui.get_bounds`.

For each node, return a stable-within-snapshot path, active/enabled state,
component kind, render order, canvas-group alpha/interactable/block-rays,
screen-space bounds, and only the bounded fields relevant to that component.
For TMP, report text, resolved font/material identity, alpha, and clipping
status where Unity exposes it. For uGUI `Button`, report interactable state and
target graphic. This is a read-only surface and should not infer semantic truth
from OCR.

`prefab.validate` must flag the class of defect seen in this session:
`serialized_reference_missing_component`, `serialized_reference_type_mismatch`,
`missing_script_guid`, and `unresolved_font_or_material`.

### P1.2 — Isolated Canvas/prefab render

Add `unity.prefab.render` that opens a prefab in a temporary preview context,
instantiates it under a controlled Canvas, applies the declared viewport and
safe area, and captures it without application boot. It must be non-persistent
by default, isolate the preview scene, and return both a screenshot and the
semantic snapshot used to render it.

This is the tool that turns a 30–45 second boot loop into a seconds-fast design
loop. Full PlayMode remains necessary for behaviour, but not for every layout
adjustment.

### P2.1 — Guarded UI mutation transaction

After read/render prove stable, add a narrow transaction API rather than raw
YAML authoring:

- set an existing serialized field;
- set `RectTransform` anchors, pivot, position, and size;
- set existing `TMP_Text.text`/`Image.sprite`/`CanvasGroup` fields;
- create/delete a child from an approved template;
- add/remove only an allowlisted component.

Every mutation must use a prefab path plus stable selector, preview a
structured before/after delta, apply atomically in Unity, validate import and
bindings, and emit a reversible patch/reference artifact. The API must refuse
ambiguous selectors and never silently replace a component with a different
type.

### P2.2 — Guarded semantic interaction

Add `unity.ui.click` only after `ui.query` is reliable. Inputs are a unique
semantic selector and an explicit permitted action. The response records the
matched node, pointer/event-system delivery, before/after snapshot ids, and
whether the target was interactable. It refuses ambiguous, hidden, or disabled
targets. Coordinate clicks and generic OS automation are not acceptable
substitutes.

### P2.3 — Device reference lane

For mobile UI, compare a device screenshot as a separate acceptance lane. It
uses the same reference manifest but reports device model, OS, resolution,
safe-area inset, orientation, and build revision. Game View parity is not a
claim of device parity.

## 8. Critical design guardrails

1. **No “pixel perfect” claim without a defined rendering envelope.** Font
   rasterization, device scale, dynamic content, and OS safe areas require
   declared thresholds and masks. Otherwise the tool must return
   `comparison_not_comparable`, not a misleading percentage.
2. **Masks are reviewable artifacts.** A mask may hide dynamic time, ads, or
   legal text only when declared in the manifest. A broad/full-card mask is a
   failed policy validation.
3. **Visual score is not semantic proof.** A screenshot cannot prove a button
   is clickable or text is backed by the intended component. Keep visual,
   semantic, and interaction evidence distinct.
4. **Semantic tree is not visual proof.** Correct text and RectTransform values
   do not prove clipping, material failure, draw order, or wrong asset choice.
5. **Never mutate a prefab through raw text as the default tool path.** Preserve
   Unity file IDs, import behaviour, undo/rollback, and type checking by using
   the Editor API.
6. **Visual acceptance must survive a fresh session.** A cached warm Game View,
   stale screenshot, or unrecorded live payload is insufficient.
7. **Manual styling is a handoff state.** It is never auto-promoted to reference
   acceptance based on compilation or a successful runtime flow.

## 9. Acceptance tests for the toolset itself

The new capabilities need their own executable test matrix.

| Case | Required proof |
| --- | --- |
| Exact reference fixture | Comparator passes; semantic tree and interaction assertions pass; all artifacts persist. |
| Wrong viewport/orientation | Comparator refuses with `comparison_not_comparable`; no score is reported. |
| Body text hidden by font/material issue | Semantic snapshot flags unresolved/non-rendering state; visual comparison fails the body region. |
| Obsolete/missing `Button` script GUID | `prefab.validate` fails before PlayMode with a typed serialized-reference error. |
| Popup oversized or shifted | Bounds assertion and visual diff both flag the popup region. |
| Wrong sprite with same bounds | Visual diff flags illustration region even when semantic tree passes. |
| Disabled cooldown nav button | Semantic query reports alpha/interactable/block-rays; click refuses delivery. |
| Close/CTA action | Guarded click delivers once and before/after snapshots prove expected state. |
| Dynamic timer | Declared mask or frozen fixture prevents false difference; undeclared timer difference fails policy. |
| Non-deterministic live data | Fixture contract downgrades decision readiness and refuses visual completion. |
| Mutation failure mid-transaction | Prefab contents and references remain unchanged; result reports rollback. |
| Device safe-area variance | Device result records insets and either passes its device-specific reference or reports non-comparable. |

## 10. Delivery order and definition of done

| Order | Slice | Why this order | Done when |
| --- | --- | --- | --- |
| 1 | P0.1 reference manifest + comparator | Makes visual mismatch measurable before adding authoring power | A static expected/actual pair produces region verdicts, overlay/diff artifacts, mask audit, and reliable non-comparable failures. |
| 2 | P0.2 UI fixture contract | Prevents flaky comparison and live-data false passes | A clean editor session can render available/active/cooldown fixture states with fixed time and locale. |
| 3 | P1.1 prefab validation + uGUI tree | Explains mismatch and catches broken bindings before runtime | Missing script, null/incompatible field, hidden TMP, bounds, and button interactability are queryable. |
| 4 | P1.2 isolated renderer | Makes iteration cheap enough to use comparator continuously | A prefab renders at 1440×3200 in seconds without app boot and yields the same evidence schema. |
| 5 | P2.1 guarded mutation | Makes correct fixes safer than YAML surgery | A typed patch has preview, atomic Editor apply, import/binding validation, and reversible delta. |
| 6 | P2.2 interaction + device lane | Completes behaviour and mobile truth | Required CTA/close paths and declared device targets have independent pass/fail evidence. |

The first three slices are the minimum to prevent a repeat of this incident.
The first four make reference-based UI work realistically end-to-end for an
agent.

## 11. Workflow change required now, before new tooling ships

Until the new surfaces exist, every reference-driven UI task must close with a
truthful three-lane status table:

| Lane | Allowed pass evidence | Do not substitute |
| --- | --- | --- |
| Technical | refresh/compile, targeted tests, prefab-import log grep | a screenshot alone |
| Functional | deterministic scenario or documented live-state limitation, runtime logs, interaction evidence where available | component presence in the hierarchy |
| Visual | side-by-side human review of reference and same-viewport actual capture, with explicit owner/sign-off | green scenario, “looks roughly right,” or an unstated manual-styling handoff |

If visual ownership transfers to a human, the final report must say exactly
which required regions remain manual and mark reference acceptance pending.

## 12. Final verdict

`execution-trustworthy, reference-acceptance-incomplete`.

XUUnity Light Unity MCP currently does a good job of proving that Unity ran and
capturing the screen it rendered. It lacks the system needed to turn a supplied
UI reference into an executable, deterministic, semantically explained, and
visually enforced acceptance target. The top investment is not more generic
screenshots: it is the P0 reference manifest + fixture + region-aware visual
comparison loop, followed immediately by uGUI/prefab inspection and isolated
rendering. Only then can an agent honestly take a reference UI screen from
intake through implementation to a completed, reproducible match.
