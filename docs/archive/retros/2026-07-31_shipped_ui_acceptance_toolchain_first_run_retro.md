# XUUnity Light Unity MCP Retro — First Post-Release Run of the UI Acceptance Toolchain

Date: `2026-07-31`
Status: `completed public retro; reusable residuals released in v0.3.51`
Source line under test: `v0.3.49`
Retro prompt: [`CHAT_RETRO_PROMPT.md`](CHAT_RETRO_PROMPT.md)

Closure update (`2026-08-02`): all nine reusable priority improvements from
this retro shipped in `v0.3.51`. Current source additionally executes the
generic guarded uGUI click in Play mode and proves delivery, semantic state
change, receipt fields, and refusal. Consumer-specific fixtures, interaction
scenarios, and independent vision judges remain consumer adoption work rather
than reusable MCP implementation backlog.

## Why this retro exists

`RETRO_REGISTRY.md` records on 2026-07-31 that `v0.3.49` "implements every
reference-driven UI acceptance slice added on 2026-07-30", and that the
2026-07-30 and 2026-07-17 rows were therefore moved to completed history.

This session is the **first production consumer run of that shipped slice** by an
operator who had not designed it. It is not a design retro and it does not
restate the capability gaps those two retros already specified. It reports what
the *implemented* surface got right, and the defects that only a real run could
expose.

The task was ordinary UI work: bring a shared UI-package popup and a nav button
in a consumer project into visual parity with four supplied 1440x3200 design
frames, at the acceptance bar "recognisably the same screen", not pixel equality.

## Related existing work

| Existing artifact | Established scope | What this retro adds |
| --- | --- | --- |
| [Reference-driven UI completion and visual acceptance retro](2026-07-30_reference_driven_ui_completion_and_visual_acceptance_retro.md) | Specified the reference manifest, fixture contract, semantic tree, isolated render, guarded mutation/click, and device lane. Registry marks all slices shipped in `v0.3.49`. | Post-release verification: the protocol holds end to end, but four implementation defects survive, one of which emits a success receipt for a write that did nothing. |
| [Prefab/UI authoring and visual-iteration gap retro](2026-07-17_prefab_ui_authoring_and_visual_iteration_gap_retro.md) | Identified missing prefab structure read, guarded mutation, and isolated render. Registry marks these shipped. | Confirms all three exist and are good, and identifies the one authoring case still forced onto raw YAML: asset-typed object references. |
| [Token-efficiency response envelope retro](2026-06-02_token_efficiency_response_envelope_retro.md) | Compact-by-default across MCP tool surfaces. | Names two UI-surface responses that are not compact-by-default and one that is pure noise at ~57 findings. |
| [PlayMode lifecycle-reset trust classification retro](2026-05-11_chat_retro_playmode_lifecycle_reset.md) | `result_trust_class` and reclassification-as-confirmation. | Independent confirmation that reclassification behaved correctly twice under domain reload, with zero false negatives. |

## 1. Executive summary

**The shipped toolchain worked.** A shared UI prefab was brought from visibly
broken to a card-region similarity of `0.9952` with an exact layout verdict
(`offset 0,0 / size 1.0,1.0`), global `0.9983`, capture stability `proven`
(drift `0.0`), and a vision lane passing 4/4 on all six criteria. Thirty-one
requests, all completed. Zero abandoned requests, zero false negatives, zero
Unity-side execution failures.

Nothing failed on the Unity side, and nothing failed in the wrapper or
transport. The distinction the retro prompt exists to resolve did not arise in
this session, and the evidence to prove that was available without effort.

The value is elsewhere: **four implementation defects in the newly shipped UI
surface**, and a measurable efficiency tax.

- **P0 — `set_serialized_field` returned `status: "applied"` for an enum write
  that changed nothing.** Enum fields are addressed by `enumValueIndex`, not by
  the enum's underlying value. Passing the semantically correct value was
  silently discarded and reported as applied. This is a false-positive receipt on
  a mutation surface, the exact failure class this retro corpus treats as most
  serious.
- **P1 — the semantic acceptance lane is unreachable from the isolated-render
  lane.** `unity_prefab_render` returns its `ui.read.v1` snapshot inline only,
  while `unity_ui_reference_compare` requires `uiSnapshotPath`. A reference
  declaring `semantic: required` therefore can never leave
  `not_evaluated / no_ui_snapshot_supplied` on that lane.
- **P1 — no transient state override for rendering.** Rendering a second
  runtime-driven UI state required mutating the shared asset and restoring it.
  Seven of thirteen mutation calls (54%) existed only to work around missing
  capability, not to author anything.
- **P2 — a passing comparison is delivered on the error channel**, and
  `reportUnassignedReferences` returns ~57 findings that are all
  standard-empty uGUI/TMP optional fields.

Verdict: **PASS with reopened sub-items.** The registry should keep the
reference-driven UI slice in completed history but add this retro as an active
row covering the four residuals.

## 2. Evidence base

Request-journal window isolated to this session (`2026-07-31T11:39Z` to
`12:26Z`); the journal is cumulative, and the 2 error-bearing and 9 abandoned
entries in the folder belong to the 2026-07-30 session, not this one.

| Evidence | Value |
| --- | --- |
| Requests submitted / started / completed | `31 / 31 / 31` |
| Abandoned in window | `0` |
| Reclassified in window | `2`, both `settled_after_lifecycle_reset` |
| Operations | `13` `unity.prefab.mutate`, `11` `unity.prefab.render`, `4` `unity.project.refresh`, `1` each `unity.prefab.validate`, `unity.prefab.snapshot`, `unity.compile.player_scripts` |
| `bridge_state.json` at close | `bridge_version 9`, `generation 143`, `health_status healthy`, `transport file_ipc`, `playmode_state edit`, `compiler_error_count 0`, `pending_request_count 0` |
| Bridge generations traversed | `138 → 139 → 140 → 143` |
| Editor | one PID for the whole session, Unity `6000.0.58f2` |
| Comparison artifacts | `expected/actual/overlay/diff/metrics/verdict` plus `vision/vision_sheet.png`, `vision/vision_review.*.json` |

Reclassification evidence, both on `unity.project.refresh` immediately after C#
edits triggered a domain reload:

```json
{"operation": "unity.project.refresh",
 "reason": "bridge_generation_changed_during_post_request_settle",
 "reclassified_status": "settled_after_lifecycle_reset",
 "previous_bridge_generation": 138, "bridge_generation": 139,
 "retryable": false}
```

Both refreshes still returned `post_settle_compile: "passed"` with
`post_settle_error_count: 0`, and flagged the derived Play Mode field as
`playmode_state_after_settle_trust_class: "stale_risk"` with
`recommended_next_action: "confirm_via_unity_playmode_state"`.

## 3. Timeline

1. `unity_status_summary` reported `editor_running: false`, `health offline`,
   `discovery_classification: host_launchable_not_active`, and emitted an exact
   `recommended_recovery_command`. Running that command verbatim produced a
   healthy bridge on the first attempt.
2. Two `unity_prefab_mutate` probes were spent discovering input conventions:
   `componentType` matches by **short** type name, and object-reference fields
   are refused outright. Both probes rolled back cleanly.
3. Four productive mutation batches (`41`, `6`, `13`, `6` ops) authored the
   geometry. Raw file edits carried the four asset-reference swaps the
   transaction API cannot express.
4. `unity_prefab_render` at `1440x3200` drove three measure-and-correct
   iterations. Programmatic measurement of render versus reference, not eyeball
   comparison, produced every correction value.
5. Two mutate/render/restore round trips inspected the second popup state and
   the second nav state, because no transient-override render mode exists.
6. Register, compare, vision packet, vision submit. Visual and vision lanes
   passed; interaction failed for want of a Play-mode fixture; semantic stayed
   `not_evaluated`.
7. Compile and console verification closed the session clean.

## 4. What worked well

| Capability | Evidence | Value |
| --- | --- | --- |
| Offline diagnosis to recovery | `blocking_reasons`, `host_prerequisite_blocking_codes`, and a literal `recommended_recovery_command` that worked first try | Zero-guess recovery; no polling loop. |
| Atomic mutation rollback | Both failed probes: `status: "rolled_back"`, `applied: false`, `rollback_reason` naming the exact failing operation index and error code | A malformed batch cost nothing and taught the schema. The asset was provably untouched. |
| `expectedSha256` precondition | Accepted on the first productive batch | Cheap protection against editing an asset that moved underneath the session. |
| `reversible_patch_json` | Emitted on every write, with ordered inverse operations | Made the mutate/restore inspection workaround survivable at all. |
| Post-write validation | Every batch reported `post_validation.status: "passed"` with reference counts | Structural regressions could not ship silently. |
| Lifecycle reclassification | Two domain reloads recorded as `settled_after_lifecycle_reset`, `retryable: false`, compile verdict preserved | No false negative. Directly validates the 2026-05-11 retro's shipped work. |
| Derived-field honesty | `playmode_state_after_settle_trust_class: "stale_risk"` with a named next action | The tool declined to present a stale derived value as authoritative. |
| Mask policy | Refused a 75.1% mask: *"a broad mask hides the very area under review"* | Caught the operator doing the wrong thing. The correct fix was a low-weight region plus a deterministic fixture. |
| Layout sub-verdict | `offset_x_ratio 0.0, offset_y_ratio 0.0, width_ratio 1.0, height_ratio 1.0` | This, not the similarity scalar, is what actually proved parity. |
| Capture stability gate | `status: "proven"`, `cell_drift_ratio 0.0` against a second render | Cheap and decisive on a non-animated surface. |
| Vision self-review flagging | `self_reviewed_only: true`, `vision_review_is_self_reviewed`, and a next action to obtain an independent judge | The lane passed without letting the author claim independent proof. |
| Refusal to over-claim | `decision_ready: false`, `decision_readiness_gaps: ["fixture_evidence_absent"]` | The strongest behaviour in the whole surface: high similarity plus a passing vision review still did not buy an acceptance verdict. |

## 5. What worked poorly

### 5.1 P0 — a success receipt for a write that did nothing

Setting a TMP font weight to its semantic value produced:

```json
{"index": 7, "op": "set_serialized_field", "status": "applied",
 "component_type": "TextMeshProUGUI", "property_path": "m_fontWeight",
 "before": "6", "after": "6"}
```

The transaction reported `status: "applied"`, `rolled_back: false`, and
`post_validation.passed: true`. No warning, no `no_op` classification. A later
call proved the cause: passing `3` moved the field `"6" → "3"`, so the field is
addressed by `SerializedProperty.enumValueIndex` while the caller naturally
supplies the enum's underlying value. Out-of-range input was clamped or
discarded instead of rejected.

Why this is P0 and not cosmetic: every other guardrail on this surface exists to
stop a mutation lying about what it did. `expectedSha256`, atomic rollback,
`post_validation`, and `reversible_patch_json` are all defeated by a change
report that says `applied` when `before == after`. An operator who did not
happen to re-measure the render would have shipped the wrong weight believing
the receipt.

### 5.2 P1 — the semantic lane cannot be reached from the isolated-render lane

`unity_prefab_render` returns its snapshot as an inline `snapshot` object.
`unity_ui_reference_compare` accepts only `uiSnapshotPath`, a file. There is no
supported way to hand one to the other, so on this lane the comparison
permanently reports:

```
"semantic_lane": {"status": "not_evaluated", "evidence": "no_ui_snapshot_supplied"}
```

A reference registered with `acceptance.semantic: "required"` is consequently
unsatisfiable outside Play mode, and `pending_lanes: ["semantic"]` is
structural rather than an operator omission. The render already writes a PNG
artifact and returns its path; the snapshot should be written beside it the same
way. In this session `includeSnapshot` was ultimately set to `false` because the
inline payload was large and unusable.

### 5.3 P1 — no transient state override for rendering

A popup whose per-state styling is applied at runtime cannot be rendered in its
second state without changing the asset. Inspecting the two secondary states
required mutate → render → measure → inverse-mutate, twice, on a prefab shared
by twelve projects.

Mutation-call accounting for the session:

| Purpose | Calls |
| --- | --- |
| Productive authoring | 5 |
| Schema discovery (both rolled back) | 2 |
| Transient state inspection and restore | 5 |
| Correcting a value from an operator mis-measurement | 1 |

**7 of 13 (54%) of mutation calls were capability workarounds.** Each carried a
full change table and a `reversible_patch_json` in the response, so the token
cost scaled with the workaround, not with the work. The tool already owns the
right primitive — the typed operation list plus its own computed inverse — it
simply cannot apply one to a preview scene only.

### 5.4 P2 — a passing comparison arrives on the error channel

`unity_ui_reference_compare` delivered `acceptance_lanes.visual.status:
"passed"` inside an `<error>` envelope, because overall `reference_acceptance`
was `failed` on an *optional* interaction lane and a *pending* semantic lane.
The payload already carries `reference_acceptance`, `failed_lanes`,
`blocked_lanes`, `pending_lanes`, and `decision_ready`; the error channel adds
nothing and forces the operator to re-read a large response to confirm the tool
itself did not malfunction. Reserve transport/tool errors for the error channel.

### 5.5 P2 — `reportUnassignedReferences` is noise at full volume

One `unity_prefab_validate` call with the flag on returned ~57
`serialized_reference_unassigned` findings at `info`. Every one was a
standard-empty uGUI/TMP optional field: `m_Material`, `m_fontMaterial`,
`m_baseMaterial`, `m_StyleSheet`, `m_spriteAsset`, `m_fontColorGradientPreset`,
`m_linkedTextComponent`, `parentLinkedComponent`, four `m_Navigation.m_SelectOn*`
and four `m_SpriteState.*` per `Button`. Signal was zero, and the one genuinely
interesting empty field in the prefab — a deliberately spriteless button image
acting as a hit area over artwork baked into the parent sprite — was
indistinguishable from the noise.

### 5.6 P3 — `unity_console_grep` has no build-pipeline suppression

A grep for the feature keyword returned 159 matches, all
`CopyFiles .../<compile-job-name>-Android/*.dll` lines, because the compile job
had been named after the feature. A second, narrower pattern was needed to reach
the real answer of zero defects.

## 6. What was not explicit enough

- **Enum field addressing.** Nothing in the tool description says enum
  properties are set by index. The generic `numberValue` input invites the
  semantic value.
- **`componentType` matching.** Fully-qualified names fail with
  `prefab_mutation_component_not_found`. The error was clear; the schema does
  not state that matching is by short name, and snapshot output shows short
  names, which is the only available hint.
- **Ordering hazard when combining lanes.** Because asset references must be
  edited on disk while everything else goes through the Editor API, a
  `unity_prefab_mutate` after a file edit without an intervening
  `unity_project_refresh` will overwrite the edit from the editor's in-memory
  copy. Nothing warns about this. The tool already reads `sha256_before` and
  could refuse on drift.
- **`includeInactive` scope on render.** Documented for the snapshot; its effect
  on the rendered image is unstated, which is part of why mutation was reached
  for instead.
- **Region rect origin.** `regions` and `dynamicMasks` take `rect{x,y,...}` with
  no stated origin, while snapshots declare `bounds_origin: bottom_left`. Image
  top-left proved correct, but only by inference from the resulting scores.

## 7. What the operator needed but did not have

1. A snapshot **path** from the render, to close the semantic lane off-Play-mode.
2. A **transient override** input on the render, so a second UI state costs one
   call instead of a mutate/restore pair on a shared asset.
3. A **`no_op` change status**, so an ineffective write is visible.
4. **Enum-by-name input**, so weights and modes can be set semantically.
5. **Asset-typed object-reference writes** (Sprite, TMP_FontAsset, Material) so
   the whole edit fits one transactional lane. Excluding *component* references
   is the correct guardrail; excluding asset references is what forces raw YAML.
6. A **default-quiet** unassigned-reference report.

## 8. Scoring

| Category | Score | Basis |
| --- | --- | --- |
| Unity-side execution stability | 10/10 | 31/31 completed, 0 abandoned, one editor PID, healthy at close. |
| Request journaling quality | 10/10 | Session window isolable; reclassification captured generation and session id on both sides. |
| Bridge health observability | 10/10 | Offline state, blocking codes, prerequisite checks, and recovery command all present before any work. |
| Wrapper-to-operator clarity | 6/10 | Rollback reasons excellent; a passing comparison on the error channel and a silent enum no-op are the deductions. |
| Recovery guidance quality | 10/10 | The emitted recovery command worked verbatim, first attempt. |
| Transport lifecycle transparency | 10/10 | Two domain reloads reclassified, not failed; derived fields marked `stale_risk`. |
| End-to-end trustworthiness during churn | 7/10 | No false negatives anywhere. Deducted only for the false-positive mutation receipt, which is a trust defect even without churn. |
| Parallel request handling | n/a | Requests were effectively serial; not exercised. |
| Token efficiency of the default operator path | 5/10 | 54% of mutation calls were workarounds, each returning a full change table plus inverse patch; ~57 useless validate findings; large inline snapshot unusable by the consumer tool. |
| Time-to-diagnosis | 9/10 | Every failure self-explained except the enum no-op, which was only caught by re-measuring the render. |
| Validation workflow discipline | 9/10 | Compile-first, structural validation, isolated render, comparison, vision, console sweep. Interaction and fixture lanes left open and declared rather than skipped quietly. |

## 9. Priority improvements

### P0.1 — classify ineffective writes

In `set_serialized_field` and `set_rect_transform`, when the serialized value is
unchanged after the write, report `status: "no_op"` rather than `"applied"`, and
carry a `no_op_count` on the transaction. Reject out-of-range enum input with a
typed error naming the valid names and indices instead of clamping.

Acceptance: a batch that sets a font weight to an out-of-range numeric value
fails with `prefab_mutation_enum_value_invalid`; a batch that writes a value
equal to the existing one reports `no_op` and the transaction still succeeds.

### P0.2 — accept enum values by name

Allow `stringValue` on enum properties, matched against enum member names, and
document that `numberValue` on an enum is an index. Keeps existing callers
working while making the natural call correct.

### P1.1 — write the render snapshot as an artifact

Have `unity_prefab_render` and `unity_prefab_snapshot` persist the `ui.read.v1`
snapshot next to the capture and return `snapshot_path`. Keep `includeSnapshot`
for the inline copy, defaulting to `false`.

Acceptance: a prefab-render capture plus its returned `snapshot_path` satisfies
`acceptance.semantic: "required"` in `unity_ui_reference_compare` with no
Play-mode run.

### P1.2 — transient render overrides

Add an `overrides` input to `unity_prefab_render` taking the same typed
operation list as `unity_prefab_mutate`, applied to the preview-scene instance
only and never written to the asset. Report them in the response as
`applied_overrides` so the capture is self-describing.

Acceptance: both states of a two-state popup are captured in two render calls
with zero mutations, and the asset `sha256` is unchanged afterwards.

### P1.3 — refuse mutation on on-disk drift

`unity_prefab_mutate` already computes `sha256_before`. When the file on disk
differs from the editor's loaded copy, fail with a typed
`prefab_mutation_asset_drifted` error naming
`unity_project_refresh` as the remedy, rather than silently overwriting
out-of-band edits.

### P2.1 — allow asset-typed object references in the transaction

Permit writes to `Sprite`, `TMP_FontAsset`, and `Material` fields addressed by
project path or GUID, keeping the existing refusal for component and
`GameObject` references. This removes the only remaining reason to hand-edit
prefab YAML, and with it the drift hazard in P1.3.

### P2.2 — comparison result is not an error

Return a successful envelope whenever the comparison itself ran. Let
`reference_acceptance`, `failed_lanes`, `pending_lanes`, and `decision_ready`
carry the verdict.

### P2.3 — quiet the unassigned-reference lane

Default `reportUnassignedReferences` to suppressing fields that are empty by
uGUI/TMP default. Add `unassignedReferenceScope: project_scripts | required |
all`, defaulting to `project_scripts`, so the report surfaces unfilled
`[SerializeField]` members of project components — the case operators actually
care about.

### P3.1 — console grep noise control

Add `excludePattern`, and default-exclude build-pipeline progress lines
(`CopyFiles`, `[n/m ...]`) unless explicitly requested.

## 10. Public-promotion recommendations

| Target | Change |
| --- | --- |
| `../../../README.md` | Document the two-lane authoring reality until P2.1 lands: Editor-API transaction for typed fields, file edit for asset references, `unity_project_refresh` mandatory between the two. |
| `../../operations/SMOKE_TESTS.md` | Add a mutation-receipt honesty case (out-of-range enum must fail; unchanged value must report `no_op`) and a prefab-render-to-semantic-lane case proving `snapshot_path` closes the semantic lane without Play mode. |
| `../../architecture/DESIGN.md` | Record that enum properties are index-addressed, and state the object-reference policy split: component references refused by design, asset references permitted once P2.1 lands. |
| `../../architecture/ROADMAP.md` | Add P0.1/P0.2 (receipt honesty) above the remaining UI work; they invalidate mutation evidence rather than merely slowing it. |
| `../../operations/CONTINUATION.md` | Note that a `visual`-only pass with `decision_ready: false` is a handoff state, not acceptance, and that `self_reviewed_only: true` requires an independent judge before closeout. |
| `REFERENCE_DRIVEN_UI_AUDIT_PROMPT.md` | Add a step: measure render against reference programmatically and derive corrections from ratios. Eyeball iteration was the slowest part of the prior session; measured iteration converged in three passes here. |

Reusable operator lesson worth promoting verbatim: **derive the canvas-to-
reference scale before measuring anything.** This session's reference frames
matched the canvas reference resolution 1:1, and an early assumption of a
different scale produced a set of wrong target values that had to be discarded.
One check of the canvas scaler settings is cheaper than a full correction pass.

Second reusable lesson: **a sprite is not its file.** Two apparent geometry bugs
were sub-rect and padding artifacts of `spriteMode: 2` sheets, not layout
errors. Measure the sprite the prefab actually references, including its
sub-rect and transparent margins, before changing any RectTransform.

## 11. Final verdict

**PASS — the shipped UI acceptance slice is fit for purpose, with four
residuals.**

The `v0.3.49` surface took a genuinely broken screen to a defensible,
artifact-backed parity verdict, and its most valuable behaviour was refusing to
call that verdict acceptance while fixture and interaction evidence was absent.
Nothing in this session produced a false-negative validation conclusion, and the
distinction between Unity-side and wrapper-side failure never became ambiguous.

The one defect that matters disproportionately is the mutation receipt that
reported `applied` for a write that changed nothing. Every other guardrail on
that surface presumes the change report is truthful. P0.1 and P0.2 should land
before further UI authoring work leans on this lane.

Registry action (updated `2026-08-02`): keep this retro in completed public
history. Track consumer-specific fixture, interaction, and independent-judge
work only in the appropriate host-private registry.
