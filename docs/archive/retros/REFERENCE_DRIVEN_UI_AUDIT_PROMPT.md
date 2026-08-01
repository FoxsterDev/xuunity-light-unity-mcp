# External audit prompt — reference-driven UI acceptance implementation

Paste the block below into a fresh session with repository access to
`AIRoot/Operations/XUUnityLightUnityMcp`. The auditor should be a different agent
from the one that wrote the implementation.

---

You are an independent external auditor. Audit the reference-driven UI acceptance
implementation in the XUUnity Light Unity MCP repository against the retro that
specified it. Your job is to find where the shipped system fails to deliver what was
demanded, and where the claims outrun the evidence. You did not write this code and you
owe its author nothing.

Repository: `AIRoot/Operations/XUUnityLightUnityMcp`
(nested public repo inside the host monorepo checkout).

## The two documents, and their different standing

**The specification — treat as authoritative:**
`docs/archive/retros/2026-07-30_reference_driven_ui_completion_and_visual_acceptance_retro.md`

It was written after a real failure in which a UI task was reported complete on
technical execution while the screen did not match its reference. Section 8 lists seven
critical design guardrails, section 9 gives a twelve-case acceptance matrix, and section
10 gives per-slice definitions of done. These are the requirements you audit against.

**The claim — treat as an assertion under test, not as evidence:**
`docs/architecture/designs/XUUNITY_MCP_REFERENCE_DRIVEN_UI_ACCEPTANCE_DESIGN_2026-07-30.md`

Its status line asserts `P0.1, P0.2, P1.1, P1.2, P1.3, P2.1, P2.2, P2.3, P3.1, P3.2
implemented and validated`, and it contains a `Post-implementation self-review` section.
That document was written by the same agent that wrote the code. A self-review is not an
independent audit; read its reasoning, verify every number in it yourself, and treat any
claim you cannot reproduce as unproven.

## Scope

Commits `v0.3.48..v0.3.49` — `5349370`, `df337a3`, `635d8fc`, `c7bdc74`. Roughly 96 files
and 15.9k inserted lines under `templates/`, `packages/com.xuunity.light-mcp/`, and
`tests/`.

Out of scope: the consumer-project UI task that motivated the retro. You are
auditing the tooling, not the screen.

## What the system is supposed to do

A supplied design image becomes a hash-pinned acceptance contract. A Game View or prefab
capture is compared against it on a resolution-independent similarity grid. The verdict is
decided across lanes — visual, semantic, interaction, vision, device — each `required`,
`optional`, or `not_required`, with a separate `decision_ready` flag.

One standing product constraint frames everything: **pixel-exact matching must never be the
acceptance bar.** Game View resolution is switchable and will differ from the reference.
What is required is that the result is recognisably the same screen in style, placement,
and size, and that the bar is configurable and sane. Audit both directions of this — a
system that quietly demands pixel equality is broken, and so is one that will accept
anything.

## Method

Do not review by reading the design document and agreeing with it. Read the retro, form
your own expectation of what each requirement means, then go to the code and the tests and
check.

Verify by execution wherever execution is possible.

**Tier 1 — mandatory, cheap, deterministic:**

- `python3 -m unittest discover -s tests` from the repo root. The claim is 634 passing with
  13 platform skips. Report what you actually observe.
- `python3 scripts/testing/check_release_version_consistency.py`
- `python3 scripts/testing/check_release_docs_freshness.py`
- `python3 scripts/testing/check_public_release_safety.py`
- `python3 scripts/testing/report_server_template_size_ownership.py`

**Tier 2 — do it if you can; if you skip it, say so explicitly and mark the affected
findings unverified:**

- Unity EditMode package self-tests. The claim is 78 tests, 77 passed, 0 failed, 1 correctly
  ignored, reproduced identically on `2021.3.45f2` and `6000.0.58f2`, plus 11/11 with a
  graphics device, plus a core-only project without `com.unity.ugui` importing with zero
  compile errors and only `com.xuunity.light-mcp.Editor.dll` built.
- End-to-end exercise of the tools through MCP against a real project.

A test suite passing tells you the assertions hold. It does not tell you the assertions are
the right ones. Read the tests as evidence to be judged, and ask what a test would have to
look like to catch the failure you are imagining.

**Tier 3 — when the audit includes bringing a real screen to parity, iterate by measurement,
not by eye.** Eyeball iteration was the slowest part of the session this prompt came from;
measured iteration converged in three passes.

- Before measuring anything, derive the canvas-to-reference scale. Read the reference
  resolution and match mode off the `CanvasScaler` that will actually be in effect. One check
  of the scaler settings is cheaper than a full correction pass: assuming a scale the project
  did not use produced a whole set of target values that had to be discarded.
- Take the render and the reference frame, measure the same feature in both, and derive each
  correction from the ratio. Do not nudge a value and re-render to see whether it looks better.
- Measure the sprite the prefab actually references, including its sub-rect and its
  transparent margins — not the source PNG. A `spriteMode: 2` sheet's sub-rect can crop the
  artwork and change its aspect, which renders as what looks like a layout bug and is not one.
  Padding baked into a frame sprite likewise offsets every child by a constant that must be
  converted, not guessed.
- Read `acceptance_lanes.*.status`, `failed_lanes`, `pending_lanes`, and `decision_ready`
  rather than the similarity scalar. The layout sub-verdict (`offset_x_ratio`,
  `offset_y_ratio`, `width_ratio`, `height_ratio`) is what proves parity; a high similarity
  number with a shifted layout verdict is not parity.
- Do not mask the region under review to make a score pass. A broad mask hides the very area
  being judged; the correct fix for a non-deterministic region is a low weight plus a
  deterministic fixture.

## Questions the audit must answer

Treat each as open. Do not assume the answer is the reassuring one.

**Can a lane report success it has not earned?**
Trace every path to `passed` and to `decision_ready`. Can caller-supplied evidence reach
either without a receipt? Can a `not_evaluated` lane be mistaken for a passing one at any
call site or in any summary? Is `pending_manual_style` reachable from, or promotable to,
acceptance? The retro's guardrail 7 says manual styling is a handoff state that is never
auto-promoted — is that structurally enforced, or merely conventional?

**Is the receipt actually a receipt?**
Scenario evidence is supposed to be receipt-backed with SHA-256 and unforgeable by the
caller. Check whether the hash is verified when read back, or only recorded when written.
Check whether `playmode_state` can be forged by a caller so an Edit-mode delivery reports as
Play-mode. Check what happens when a receipt file is edited after the fact.

**Does the similarity grid measure what it claims?**
Read the cell math. Can a uniformly shifted layout, a mirrored arrangement, or a
same-average-colour substitution score high? Does the aspect/orientation refusal
(`comparison_not_comparable`) actually fire before any score is produced, per guardrail 1?
What happens at extreme scale ratios, single-pixel images, and empty regions?

**Is the mask policy reviewable, per guardrail 2?**
A mask may hide dynamic content only when declared. Is a broad or full-card mask actually a
failed policy validation, or just a warning? What is the largest mask that still passes?

**Does the coordinate transform hold?**
Unity screen pixels are bottom-left origin; reference pixels are top-left. The region-to-node
stitching converts between them. Check off-by-one, non-square viewports, differing capture
and reference resolutions, and nodes partially outside the viewport. A silently mirrored
transform would produce confident, wrong explanations.

**Is the hand-rolled PNG codec safe?**
There is a custom decoder and encoder in `templates/server_ui_reference_png.py` with no
third-party dependency. Test it against bit depths it does not expect, palette and grayscale
images, interlaced PNGs, truncated files, and enormous dimensions. Does it fail closed with a
typed error, or produce garbage, hang, or exhaust memory?

**Is the vision lane's arithmetic sound and its provenance real?**
The overall score is clamped to the worst required criterion plus one. Verify the clamp
cannot be evaded — through waived criteria, an empty required set, or a policy override. Check
exactly what `packet_hash` covers and what it does not; anything outside the hash can change
without invalidating a review. Verify a review genuinely expires when either image changes.
Confirm no tolerance profile requires the top score. Check whether self-review is flagged in
every path that surfaces the verdict, not only at submission.

**Does `optional` mean what the code says it means?**
The implementation states that a lane marked `optional` which actually ran and failed now
fails the comparison, and only `not_required` opts out. Confirm this holds at every decision
point, including summaries, next-actions, and CLI output.

**Does the constraint gating actually degrade rather than break?**
The uGUI and TMP readers are constraint-gated satellite assemblies and the core asmdef is
supposed to keep zero package references. Verify the core `.asmdef` really has an empty
`references` array, that `InternalsVisibleTo` does not leak the seam wider than needed, and
that a project without `com.unity.ugui` gets a typed unavailable-operation failure rather
than a compile break or a silent pass.

**Do the Python and C# sides agree?**
There are cross-language contract tests. Judge whether they are sufficient: every declared
`bridgeOperation` resolving to a registered editor operation, schema-version and step-kind
strings matching across the seam, approval required in both layers. Find a seam they do not
cover.

**Is there a class of bug the tests structurally cannot see?**
One real defect was found late by a round-trip test: storing the *normalized* review record
made it fail re-normalization on the next read, because the normalized form carries
`contract_version` rather than `schema_version`. Every submitted review was silently invalid
as soon as it was read back, and unit tests on the normalizer alone could never have caught
it. That is a class, not an incident: write-then-read-back asymmetry across a persistence
boundary. Look for others — artifacts, manifests, comparison records, scenario results.

**Does the twelve-case acceptance matrix in retro section 9 have real coverage?**
Go case by case. For each, name the test that covers it or state that none does. A case
covered only by a test that asserts the happy path is not covered.

**Are the definitions of done in retro section 10 met?**
Six rows, each with an explicit "done when". Judge each independently.

## Reporting

Rank findings by severity, most severe first. For each: the file and line, a one-sentence
statement of the defect, and a concrete failure scenario — specific inputs or state leading
to a wrong output, a false pass, or a crash. A finding without a failure scenario is an
opinion; either turn it into one or drop it.

Separate clearly:

- **Confirmed** — you reproduced it.
- **Plausible** — the code path looks wrong but you could not execute it. Say what would
  settle it.

Then give:

- a verdict on each of the seven guardrails in retro section 8: enforced, partially
  enforced, or not enforced, with evidence;
- a coverage table for the twelve acceptance cases in section 9;
- a judgement on whether the status line `implemented and validated` is honest, overstated,
  or understated, and precisely which slice claims are not backed;
- anything in the design document's `Post-implementation self-review` that you found to be
  wrong, incomplete, or self-serving.

If the implementation is sound in some area, say so plainly and briefly — a padded finding
list is worse than a short one. Manufactured findings waste more time than missed ones.

Do not fix anything. Do not commit. This is an audit; the remediation decision belongs to the
maintainer.
