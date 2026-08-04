# Brief: Redesign the Public Site into a Credible Capability & Positioning Surface

Date: `2026-08-04`
Site: `https://foxsterdev.github.io/xuunity-mcp/`
Scope: **all seven pages** under `docs/`, plus a new user-facing "What's new" page
Branch: `site/redesign`
Status: brief, ready to execute

---

## 1. Current state — audited, not guessed

| Page | Lines | Size | Last content change |
| --- | ---: | ---: | --- |
| `index.html` | 565 | 28 KB | 2026-08-04 (actively maintained) |
| `install.html` | 153 | 7 KB | version bumps only |
| `comparison.html` | 138 | 6 KB | **2026-06-08** |
| `use-cases.html` | 128 | 6 KB | **2026-06-08** |
| `xuunity-vs-coplaydev-unity-mcp.html` | 110 | 5 KB | **2026-06-08** |
| `alternatives.html` | 109 | 5 KB | **2026-06-08** |
| `what-is-unity-mcp.html` | 100 | 4 KB | **2026-06-08** |

Five of seven pages have been frozen for two months, and the only commit touching them since was one that added a
footer. Those five are the entire competitive-positioning and discovery surface: what the category is, how this
compares, what the alternatives are, the head-to-head, and what it is for. The one page that gets attention —
`index.html` — is 5× the size of any of them and carries a different, more current visual and editorial standard.

**Consequence.** A reader who arrives on any page except the homepage sees a thin, dated, generic page and
concludes the tool is a weekend wrapper. Roughly ten releases of work is invisible there: the server exposes
**65 MCP tools** today, and these pages imply a handful of Unity commands.

## 2. Audience and job

Primary reader: a **senior Unity developer or tech lead** deciding whether to let an AI agent touch a real
project. Skeptical by default, and probably already burned by a Unity MCP demo that looked impressive and then
reported something untrue.

The site's job: **convert skepticism into a specific, testable expectation.** The reader should leave able to say
"this is what it will do, this is what it refuses to do, this is how I will know which happened, and here is where
it does not work yet."

Secondary reader: an **agent** ingesting these pages as context. Keep machine-readable structure accurate —
headings, tables, and the JSON-LD the homepage already ships.

## 3. Positioning mandate — honest on both sides

The requester's explicit ask: focus on **competitive advantages, and be straight about what is strong and what is
weak today.** This is a credibility play, not a marketing one. A page that admits limits is the only kind this
audience believes, and it is also the only kind that survives a release gate that checks claims.

### Strengths to lead with — as mechanisms, not adjectives

Every item below is verifiable in-repo. Present each with the field or code a reader can look for in a real
response, so the claim is checkable rather than asserted.

1. **Refusals are typed, not prose.** `editor_in_play_mode`, `editor_running_batch_conflict`,
   `operation_arguments_invalid`, `ui_target_out_of_scope`, `ui_scope_probe_incomplete`, `anchor_log_mismatch`,
   `anchor_log_rotated`, `anchor_stale_dead_session`, `anchor_identity_unverified` — each with a recommended next
   action. An agent can branch on a code; it cannot branch on a sentence.
2. **Evidence is labelled by trust, not merely returned.** `result_trust_class`,
   `post_settle_compile_trust_class` (`confirmed` / `editor_still_busy` / `deferred_during_playmode`),
   `line_numbering_basis`, `since_anchor_degraded`, `log_lane`, `freshness_class`. The tool tells you when its own
   answer is weak — including refusing to call a live editor's state "ready" when the editor is gone.
3. **Session-scoped log evidence.** `since=playmode_start|bridge_generation|request_id` bounds a search to the
   current run, so a wait loop cannot match a line from a previous play session.
4. **Absence is never silently treated as proof.** A zero-match answer reports whether absence could be
   established at all.
5. **Two lanes, routed automatically.** Closed projects use a real Unity batchmode lane; a project with a live
   editor is rerouted rather than failed, and a live editor is never corrupted by a competing batch run.
   Portfolio evidence: 12 projects in parallel, 11 via batch, 1 via GUI fallback, 0 failed.
6. **Multi-scene UI targeting.** `all_loaded_scenes`, `sceneName`, `includeDontDestroyOnLoad`, per-node
   `scene_name`, and a distinct out-of-scope code — the difference between "does not exist" and "not reachable
   from where I looked".
7. **Acceptance beyond compile:** scenario replay, UI reference and vision comparison lanes, prefab
   snapshot/validate/render/mutate, SDK dependency and generated-file diff guards, artifact registration.
8. **Refuses before it spends.** An invalid tool call is rejected before it can launch a Unity editor.

### Limits to publish

These are not a liability. They are why the strengths are believable.

- **macOS is the proven host.** Windows and Linux paths exist, are unit-covered, and have a dedicated
  cross-platform ruleset, but the current release line's live validation is macOS.
- **Unity `2022.3` and `6000.x`** on the versions in `docs/reference/STATUS.md`. Others are unproven, not
  unsupported.
- **UGUI is the implemented UI backend.** No UI Toolkit reader today.
- **Some verification is inherently non-authoritative and says so** — a refresh during Play Mode reports
  `deferred_during_playmode` instead of a green it cannot back.
- **Not a code generator or autonomous refactorer.** It is a validation and evidence bridge; the agent writes the
  code.
- **Editor-driven, not device-driven.** Device lanes are roadmap.

**Rule: never publish a measured number the repo cannot back.** Counts and ratios must trace to
`docs/reference/STATUS.md`, `FEATURES.md`, or `COMPARISON.md` at the current version. A version paired with a
measurement must not be bumped without re-measuring — the release gate now enforces exactly this.

### Competitor pages — fairness is a hard requirement

`comparison.html`, `alternatives.html`, and `xuunity-vs-coplaydev-unity-mcp.html` name other projects.

- Describe alternatives **accurately and neutrally**, by design intent, not by insinuation. Where another tool is
  a better fit, say so plainly — a comparison page that never concedes anything is read as advertising and
  discarded.
- Prefer "different goal" over "worse". Position on **evidence discipline and lane safety**, never on feature
  count.
- No claims about another project's internals unless they are checkable from its public docs, and date any such
  claim, since it can go stale.

## 4. Per-page mandate

**`index.html`** — the current editorial baseline. Keep its structure and the release-pinned copyable setup
prompt; align the new pages to it, not the reverse. Light refresh only; it must not regress.

**`what-is-unity-mcp.html`** — category explainer and the top-of-funnel entry. Define Unity MCP neutrally, then
place this tool inside it. Must end by routing to use-cases or install.

**`use-cases.html`** — the biggest opportunity. Replace the flat capability list with jobs. For each: the tools
involved, the evidence returned, and the refusal to expect when preconditions are missing. Add a **"failure modes
this prevents"** section with concrete before/after pairs — a wait loop matching a previous session's log line; a
UI query answering "not found" for an object in an additively loaded scene; a compile "passed" that Play Mode
deferred; a batch run colliding with an open editor. The page currently has none of this, and it is the strongest
material available.

**`comparison.html`** — keep the by-workflow framing and the feature matrix, but re-cut the matrix around
decision-relevant axes: evidence trust, refusal typing, lane safety, portfolio scale, host/Unity coverage, UI
backend. Concede rows honestly.

**`xuunity-vs-coplaydev-unity-mcp.html`** — a genuine head-to-head. Add a "choose the other one when" section
with real content; without it the page has no credibility.

**`alternatives.html`** — a useful landscape page, not a straw-man list. Group by intent, and be explicit about
where this tool is not the answer.

**`install.html`** — currently only version-bumped. Make the first five minutes unmissable, add the
verify-it-worked step, and link the smoke cases.

**Site-wide** — one nav, one footer, one typographic scale, one link style, consistent page furniture, and a
coherent internal link graph so no page is a dead end.

## 5. Design direction

Aim: infrastructure documentation from a team that ships. Confident, dense, typographic, restrained.

- Extend `docs/assets/site.css`; do not introduce a second visual language. Align to `index.html`.
- Light and dark both first-class.
- Structure over decoration: comparison tables, annotated payload blocks, status chips for trust classes and
  refusal codes. No stock illustration, no gradient hero, no fabricated dashboard screenshots.
- **Payload snippets are the visual centrepiece** — treat them as designed artifacts: syntax-toned, annotated,
  scrollable in their own container.
- Scannable in 20 seconds, rewarding at 5 minutes. Every section headline must carry meaning if the body is
  skipped.

## 6. Hard constraints — the build fails without these

- **`bash scripts/testing/run_site_ui_checks.sh` must stay green (currently 42/42).** Playwright runs
  `chromium-desktop`, `chromium-narrow`, `chromium-mobile` and asserts: no critical or serious **axe**
  accessibility violations; **no horizontal overflow** in any tested viewport; foldout `details` open without
  layout breakage; the homepage clipboard prompt matches the release-pinned setup contract; key doc routes load.
  Extend coverage to every redesigned page; do not weaken existing assertions.
- **`check_release_version_consistency.py` must pass.** Every version reference in a release-facing doc must equal
  the current package version. Use `vX.Y.Z+` for "since this version". **Never hardcode a release in a test** —
  derive it from `package.json`; a hardcoded `v0.3.45` in the site spec is exactly what froze the homepage prompt
  for ten releases.
- **`check_public_release_safety.py` must pass** with non-zero `local_denylist_tokens`. No private project names,
  host paths, pids, session ids, or internal codenames.
- **`check_public_site.py` and `check_release_docs_freshness.py` must pass.**
- Semantic HTML, real heading order, keyboard-reachable interactive elements, `prefers-color-scheme` honoured.
- No new runtime dependency. Static HTML plus the existing CSS.

## 6b. A user-facing "What's new" surface, and a release-flow rule that keeps it alive

The technical changelog is written for maintainers. A reader evaluating the tool cannot tell from
`operation_arguments_invalid` or `since=bridge_generation` what they can now *do*. Every release must therefore
also ship a **plain-language capability entry**, and the site must show it.

**Translation rule.** Each user-visible change gets one sentence in the reader's terms — the capability and why it
matters — not the field name. Examples of the register to aim for:

| Technical entry | User-facing entry |
| --- | --- |
| `unity_ui_click` gains `targetKind=all_loaded_scenes`, `sceneName`, `includeDontDestroyOnLoad` | Your agent can click a real button in the running game even when the screen lives in an additively loaded scene or a persistent overlay — and it tells you which scene the button was in. |
| `unity_ui_get_text` / `unity_ui_get_bounds` with per-node `scene_name` | It can read a label back to confirm the screen actually changed, and report where an element sits on the Game View, so a layout bug can be located instead of described. |
| `since=playmode_start` on `unity_console_grep` | Log checks are bounded to the current run, so "the marker appeared" can no longer be satisfied by yesterday's run. |
| `operation_arguments_invalid` | A malformed request is refused in milliseconds instead of starting a Unity editor first. |

**Placement.** A dedicated `changes.html` ("What's new"), newest first, grouped by release, each entry one
sentence with an optional payload snippet behind a foldout. The homepage carries the latest 3–5 entries with a
link through. Keep it skimmable: a reader should learn what changed in three releases in under a minute.

**This is a release-flow requirement, not a nice-to-have.** The gates already enforce that version references
follow the release; the same discipline must apply to the human-readable surface:

- the release checklist gains a step: every `CHANGELOG.md` entry that is user-visible has a plain-language
  counterpart on `changes.html` for the current version;
- a check fails the release when the top `CHANGELOG.md` section names a version that `changes.html` does not yet
  cover, mirroring `check_release_docs_freshness.py`;
- purely internal changes are explicitly marked as such so the check can skip them, which keeps the rule honest
  instead of encouraging filler.

## 7. Deliverables

1. Branch `site/redesign`.
2. All seven pages rewritten or refreshed per §4, plus a new `changes.html` per §6b, plus additive
   `docs/assets/site.css` changes.
3. Playwright coverage for every page in `tests/site/`.
4. All five release gates green and site checks green.
5. A claim-source table: every factual statement on the site mapped to the repo file backing it, so the
   positioning can be fact-checked line by line.

## 8. Acceptance

A skeptical Unity tech lead lands on any page, reads for two minutes, and can state unprompted: what it proves,
how it signals when a result is weak, what it refuses, where it does not work yet, and why that combination is
harder to build than a tool that merely runs Unity commands.
