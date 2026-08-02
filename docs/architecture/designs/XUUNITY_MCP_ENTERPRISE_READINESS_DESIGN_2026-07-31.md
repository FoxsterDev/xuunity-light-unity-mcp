# XUUnity MCP Enterprise Readiness Design

Date: `2026-07-31`
Status: `active implementation; B5 runtime-interaction proof partially closed`
Scope: `Operations/XUUnityLightUnityMcp`
Source: gap assessment following the external audit of the reference-driven UI acceptance
surface and its remediation in `v0.3.51`

## Problem

The toolchain works as an internal instrument for a single maintainer on a portfolio of
similar casual mobile titles. The question this document answers is different: what has to
be true before a large studio — the kind with a platform team, a security review, and a
procurement process — can adopt or buy it.

The gap is not code quality in the core. The comparison engine discriminates correctly
under adversarial input, the acceptance vocabulary is unusually honest, and the assembly
architecture is genuinely dependency-free. The gap is a different **class** of work:
continuous integration, concurrency, throughput, breadth of proof, and the commercial
surface around the artifact.

This plan ranks the blockers by **where the deal dies first**, not by engineering interest.
An evaluator meets them in roughly this order, and each one ends the conversation before
the next is reached. Work them in order; parallelising past a blocker wastes effort on
something nobody will get to evaluate.

## Evidence base and its limits

Stated plainly so the plan is not read as broader than it is.

- The audit and remediation covered the reference-driven UI acceptance surface, roughly 96
  files. The server exposes on the order of 67 tools; the batch orchestrator alone is
  ~2800 lines and was not audited.
- Field evidence is one maintainer, one monorepo, twelve broadly similar 2D casual titles,
  uGUI on the Built-in render pipeline.
- There is no evidence for URP or HDRP, Addressables, console platforms, large codebases,
  or more than one engineer working concurrently.

Nothing below should be read as "the rest is fine". It is unmeasured.

## Blockers, in the order a deal dies

### B1 — There is no CI that builds and tests the Unity package

**Where it dies.** First technical question of due diligence: "show me the build." The
answer today is that the package is never compiled by automation. GitHub Actions runs the
Python host suite only. No consuming project references the package sources by path — all
twelve pin it by git tag — so a change to the editor assemblies can be committed, released
and tagged without ever being compiled.

This was not hypothetical. `v0.3.50` shipped a TMP test assembly that did not compile.
`v0.3.51` repaired that defect and was compiled and tested locally on two Unity lines before
tagging, but the repository still has no automated Unity gate. Local release discipline is
evidence; it is not the CI control this blocker requires.

Compounding it: the integration workflow was already failing on all three runner platforms
from the `v0.3.49` release onward, for two separate platform-portability defects in tests,
and nobody noticed until the failure was read by an outside party.

**Done when**

- A workflow compiles `com.xuunity.light-mcp` on at least two Unity LTS lines and runs the
  EditMode and PlayMode suites, on a schedule and on every pull request.
- A second job imports the package into a project **without** `com.unity.ugui` and asserts
  the core assembly still compiles, which is the constraint-gating claim the architecture
  rests on.
- The Python suite runs on Windows, macOS and Linux and is green; a red default branch
  blocks the release script rather than being discovered later.
- Tagging is gated on all of the above rather than being a manual step.

**Notes.** Unity licensing on hosted runners is the real cost here, not the YAML. A
self-hosted runner with a seat, or one of the established Unity CI actions with a license
secret, are both acceptable; pick one and document the constraint. Until this exists, every
other claim in this repository is asserted rather than demonstrated, which is why it is
first.

**Current local evidence (2026-08-02).** The clean-package matrix is green on Unity
`2022.3.62f3` and `6000.0.58f2`: each passes EditMode `62/62` and dependency-free PlayMode
`5/5`, with post-settle compile green and verified editor closeout. This closes the local
release-gate failure but does not close B1: the same matrix still needs to run automatically
on pull requests and gate tags.

**Effort.** Small-to-medium, dominated by licensing and runner setup rather than code.

### B2 — Evidence provenance is directory containment, not identity

**Where it dies.** Security review, as soon as someone asks what the acceptance verdict is
worth against a motivated or merely careless process.

`v0.3.51` closed the acute hole: a scenario result is only treated as an editor receipt
when it is read from the editor's own results directory, and anything else is reported as
an unverified path that cannot reach proven determinism. That is a real improvement — the
prior behaviour let a hand-written JSON file earn a full pass on every lane — but the
security boundary is now "which directory the file is in". Any process that can write into
the project's `Library/` tree can still mint evidence.

The correct construction already exists in this codebase. The SDK package-restore lane has
the host generate a run identity, dispatch it, and refuse any receipt whose
`{schema_version, operation, run_id, project_root}` does not match what was dispatched. The
UI evidence path does not do this, even though the host already owns the request journal
and the scenario results directory.

**Done when**

- The host generates a per-run nonce, records it in the request journal, and refuses a
  receipt whose run identity does not match a run it actually dispatched.
- The recorded SHA-256 is re-verified when the receipt is read, not only computed at write
  time, so post-write tampering is detected rather than silently re-hashed.
- `playmode_state` is corroborated against host-side bridge state for that run rather than
  trusted from the payload.
- The threat model is written down: what the receipt does and does not prove, and against
  whom. A studio's security reviewer will ask, and "it is in the right folder" is not an
  answer they will accept in writing.

**Effort.** Medium. The pattern is already in the repository, so this is consistency work
rather than invention.

### B3 — The model assumes a single writer

**Where it dies.** The moment the buyer says "we have a shared CI and forty people on this
title." Everything after that is academic.

Scenario results, comparisons and vision reviews are files in a directory. A review is
keyed by a judge id the submitter chooses for itself. There is no locking, no identity, no
tenancy, and no notion of concurrent runs. Two agents against the same project race; two
CI jobs against the same reference collide. `v0.3.51` made a duplicate submission an
explicit refusal rather than a silent overwrite, which prevents the worst outcome but does
not make concurrency work.

**Done when**

- Runs and comparisons are namespaced so that concurrent executions against one project
  cannot collide, and a stale run cannot be mistaken for a live one.
- Writes to shared state use a documented locking or atomic-swap discipline, with the
  failure mode specified rather than emergent.
- Judge identity is attributable to something the submitter does not choose for itself, at
  least to the extent of distinguishing a human, an independent agent and the authoring
  agent in a way that cannot be self-asserted.
- A documented answer to "what happens when the same reference is compared by two jobs at
  once", proven by a concurrency test rather than reasoned about.

**Effort.** Medium-to-large. This is a design change, not a patch, and it interacts with
B2: run identity is the natural key for both.

### B4 — Comparison throughput is not industrial

**Where it dies.** The pilot, on the buyer's real content — the first moment the tool is
pointed at something that is not a synthetic fixture.

The PNG row-unfilter is a per-byte loop in pure Python. Measured: a real 1290x2796 capture
decodes in 3.34 s, against 0.03 s for the same image with no row filtering. A comparison
decodes three images, so ordinary retina captures cost roughly ten seconds before any
comparison work happens. At the current 16-megapixel decode budget the ceiling is about
15 s for a single image.

The published performance figure of ~0.7 s for a production-scale comparison is real but
unrepresentative: it was measured on fixtures written by this repository's own encoder,
which emits filter type 0, the one case the slow path never hits. That number should not
appear in a sales conversation without the qualification, and the benchmark should be
replaced with one built from real engine captures.

**Done when**

- Decoding uses a native path where available, with the pure-Python implementation kept as
  a dependency-free fallback and both covered by the same tests.
- A benchmark exists that uses engine-produced captures, is run in CI, and fails on
  regression.
- Published performance claims are restated against that benchmark.
- The pathological cases already refused (decompression bombs, captures below the grid) stay
  refused, verified by the existing audit-regression harness.

**Effort.** Small-to-medium, and the highest ratio of perceived improvement to work in the
list. Worth doing early for demo quality even though it ranks fourth for deal survival.

### B5 — The lane that matters most is not proven, and a major UI stack is missing

**Where it dies.** Technical fit evaluation, when the evaluator maps the tool onto their
actual UI stack and asks what the interaction verdict is worth.

Two distinct problems.

*Play-mode interaction is untested by execution.* Every guarded-click test runs in Edit
mode; one of them asserts precisely that. The Play-mode delivery path — the only one that
yields a passing interaction lane — has no PlayMode test anywhere. The lane whose entire
purpose is proving a runtime user path is the lane with no runtime proof.

*UI Toolkit is absent.* The read surface is uGUI-first with a TextMeshPro satellite. UI
Toolkit is not implemented. A studio with editor tooling or a modern runtime UI on UI
Toolkit gets no semantic lane at all, and the tool degrades to pixels.

Related coverage state at the time of the audit: of the twelve acceptance cases the
originating retro defined, five were covered, five partially, two not at all. `v0.3.51`
improved several but did not close the matrix.

**Done when**

- A PlayMode test delivers a guarded click in Play mode and asserts the receipt, the
  before/after state change and the refusal paths, running in the B1 workflow.
- The TMP tests added in `v0.3.51` have actually executed on both Unity lines.
- Either UI Toolkit has a read provider behind the same constraint-gating pattern as the
  uGUI and TMP satellites, or the limitation is stated prominently in the public
  positioning so no evaluator discovers it during a pilot.
- The twelve-case matrix has a published coverage table, honestly marked, kept current.

**Current progress (2026-08-02).** Current source adds a uGUI-gated PlayMode test assembly
that drives the real scenario-step dispatcher and proves exactly-once guarded-click
delivery, the `ui.interaction.v1` receipt, before/after semantic state change,
`playmode_state=playing`, and refusal without a receipt. It passes `7/7` package PlayMode
tests in Unity `2022.3.62f3` and `6000.0.58f2` consumer projects; a no-uGUI clean project
retains the dependency-free `5/5` core lane. The reusable runtime-interaction execution gap
is therefore closed locally, but B5 remains open for the B1 CI workflow, UI Toolkit scope,
the published coverage matrix, and per-consumer fixture/interaction proof.

**Effort.** Medium for the tests, large for UI Toolkit. Deciding *not* to do UI Toolkit is a
legitimate answer, but it must be a stated scope boundary rather than a silence.

### B6 — The evidence base is one author, one portfolio, one stack

**Where it dies.** Procurement, at the reference-check stage, and earlier in any serious
architecture review.

Everything demonstrated so far comes from twelve broadly similar 2D casual titles built by
one person on one render pipeline. A studio evaluating this will ask who else runs it, at
what scale, and on what. There is currently no answer.

**Done when**

- The toolchain is proven on at least one project that is materially unlike the current
  portfolio: a scriptable render pipeline, Addressables, a large asset graph, or a 3D title.
- At least one deployment exists outside the author's own control, with a written account of
  what broke on first contact.
- Known-unsupported configurations are listed explicitly rather than left to be discovered.

**Effort.** Calendar-bound rather than effort-bound. This cannot be compressed by working
harder, which is a reason to start it in parallel with B1 even though it ranks sixth.

### B7 — Release and supply-chain engineering is hand-rolled

**Where it dies.** IT and security onboarding, which in a large studio is a gate with its
own queue.

The distribution is a git-tag UPM URL. The host server installs itself into a
platform-specific application-support directory via a bespoke launcher and refresh script.
There is no signing, no checksum published against the artifact, no SBOM, and no documented
supply-chain story. A live server keeps running old code until the install is refreshed and
the process restarted, which is a correctness hazard as well as an operational one: during
this very remediation, verification against the running server reported stale behaviour
until that was recognised.

Documentation honesty is part of this. The prior release documentation reported test counts
that included skips as passes in three separate places, and claimed validation on a UI stack
that had no tests. Both were corrected in `v0.3.51`, but the process that produced them is
unchanged.

**Done when**

- Releases publish a signed, checksummed artifact with an SBOM, produced by the B1
  workflow rather than by hand.
- The installed server reports its own version and refuses, or loudly warns, when it is
  older than the source it was installed from.
- A documentation gate rejects a release whose stated validation numbers do not match the
  run that produced them, in the spirit of the existing release-consistency checks.

**Effort.** Small-to-medium, and largely mechanical once B1 exists.

### B8 — There is no commercial surface

**Where it dies.** Legal, which is where an otherwise successful evaluation stalls
indefinitely.

The artifact is a public repository under an individual account. There is no support model,
no SLA, no security disclosure process with a response commitment, no named legal entity,
and no reference customers. A studio cannot put a dependency with those properties on a
shipping title without an exception process, and the exception process is where enthusiasm
goes to die.

**Done when**

- The licensing and support model is decided and published, including what is free and what
  is paid.
- A security disclosure policy exists with a stated response window, and an owner.
- A commercial entity can sign an agreement.
- Positioning states supported Unity versions, render pipelines and UI stacks as a
  compatibility matrix rather than as prose.

**Effort.** Not engineering. It is nonetheless a hard gate, and it has a long lead time, so
it should start before the engineering work finishes.

## Sequencing

The ranking above is deal-survival order, which is not the same as execution order. Two
items have long lead times and should start immediately even though they rank late.

**Phase 0 — make the existing claims true.** B1 in full, plus the B7 items that fall out of
having a pipeline. Start B6 outreach and B8 legal work in parallel because both are
calendar-bound. Nothing else should be built until a machine other than the author's laptop
can build and test this. Exit criterion: a green, scheduled, three-platform pipeline that
compiles the Unity package and gates the tag.

**Phase 1 — make the verdict trustworthy under scrutiny.** B2 then B3, in that order,
because run identity from B2 is the natural key for the namespacing B3 needs. Take B4 within
this phase as well: it is cheap and it is what a demo feels like. Exit criterion: a written
threat model, a concurrency test, and a benchmark on real captures.

**Phase 2 — make the coverage match the pitch.** B5. Decide UI Toolkit explicitly: build it
or scope it out in writing. Publish the acceptance-matrix coverage table and keep it
current. Exit criterion: no lane claims proof it does not have.

**Phase 3 — close the commercial surface.** Finish B8, publish the compatibility matrix,
and convert the Phase 0 outreach into at least one referenceable deployment.

## Non-goals

- Rewriting the comparison engine. It survived adversarial testing; the audit's findings
  were about the machinery around it, not the cell mathematics.
- Broadening the tool surface. Nothing here argues for more tools; several blockers argue
  for proving the existing ones.
- Chasing pixel-exact comparison. The standing product constraint is unchanged and correct:
  recognisably the same screen, never pixel equality.

## Risks

- **Unity licensing on CI runners** is the single most likely thing to stall Phase 0. Decide
  self-hosted versus licensed hosted early; do not discover it late.
- **B3 is a design change.** Attempting it as a patch on the current file-per-artifact model
  will produce a worse system than doing it deliberately.
- **UI Toolkit is a fork in the road.** Building it is a large investment; not building it
  narrows the addressable market. Either is defensible, drifting is not.
- **The honest-verdict discipline is the differentiator and is easy to erode.** Every
  blocker above creates pressure to soften a claim. The audit-regression harness exists
  partly to make that erosion visible; keep it in the release gate.

## What must not be claimed until the matching blocker closes

Recorded so the positioning does not outrun the engineering, which is the failure mode the
originating retro was written about in the first place.

- No "CI-verified" or "continuously tested" claim until B1 closes. The editor assemblies are
  currently unbuilt by automation.
- No "tamper-evident" or "auditable evidence" claim until B2 closes. Containment in a
  directory is not tamper evidence.
- No "team" or "CI-ready" claim until B3 closes.
- No performance figure that was measured on self-generated fixtures until B4 closes.
- No "validated on Unity X with TMP" claim for a configuration whose tests have not executed.

## Related

- [`XUUNITY_MCP_REFERENCE_DRIVEN_UI_ACCEPTANCE_DESIGN_2026-07-30.md`](XUUNITY_MCP_REFERENCE_DRIVEN_UI_ACCEPTANCE_DESIGN_2026-07-30.md)
  — the surface this readiness plan follows from, and the audit note on its status line.
- `scripts/testing/check_audit_regressions.py` — the executable record of what the audit
  found and what keeps it closed.
- [`ROADMAP.md`](../ROADMAP.md) — capability direction, which this plan deliberately does not
  extend.
