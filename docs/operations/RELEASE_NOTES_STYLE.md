# Release Notes Style

Use this guide for the top `CHANGELOG.md` release section and for the matching
GitHub Release. The audience includes Unity developers who are new to MCP and
may not know XUUnity's internal names.

## Source Lock

Build the notes only from the release commit, the diff from the previous tag,
the matching changelog section, test results, and known release-gate gaps.

- Do not turn a successful callback into proof that the requested Unity change
  happened. Name the result or state that was actually measured.
- Do not call a test passed when it was skipped, waived, blocked, or not run.
- Preserve Unity versions, counts, error codes, commands, limitations, and
  compatibility boundaries exactly.
- Keep private project names, workstation paths, run ids, screenshots, and
  internal product details out of public notes.

## Required GitHub Release Structure

```markdown
# vX.Y.Z — <one concrete developer outcome>

## Why this matters

Explain the previous failure or wasted step in two or three sentences. Describe
what a developer could misread, wait for, repeat, or ship incorrectly.

## What changed

- Name the tool or Unity workflow and the new behavior.
- Explain important refusal, recovery, or compatibility behavior.

## What this gives developers

- Connect each behavior to a practical result: fewer false passes, a clearer
  next action, a smaller response, or a faster validation loop.

## Validation

- List exact test suites, Unity versions, projects only when public-safe, and
  pass/skip/waiver outcomes.

## Known limitations

- Include every release-gate waiver or unverified platform lane. Omit this
  section only when there is no known release-specific gap.
```

The changelog can combine `What changed` and `What this gives developers` when
one compact bullet explains both. The GitHub Release should keep the full
structure because it is the first page many developers will read.

## Junior Unity Developer Check

Before publication, reread every bullet as a Unity developer who has not seen
the implementation:

1. Does it name the Unity action, MCP tool, file, log, test, or state involved?
2. Does it explain the old pain before introducing an internal field name?
3. Does it say what changes in the developer's next action or conclusion?
4. If a technical term is necessary, is it explained in the same sentence?
5. Could the sentence be mistaken for a stronger validation result than the
   release actually earned?

Rewrite any bullet that fails one of these checks.

## Fact Review Prompt

```text
Review these draft release notes against the supplied release diff, changelog,
tests, and CI results. List every unsupported claim, missing limitation,
incorrect version or count, and any sentence that converts partial evidence,
a skipped test, or a waived gate into a pass. Do not rewrite the notes yet.
Return "fact_lock_passed" only when every claim is supported.
```

## Language Review Prompt

```text
Rewrite the fact-locked release notes for Unity developers, including juniors.
Keep every fact, version, count, limitation, error code, and level of certainty.
Start with the concrete developer pain, then explain what changed and how it
helps. Define an MCP-specific term in plain language the first time it appears.
Use normal engineering language and medium-length sentences. Remove marketing
claims, corporate wording, repeated paraphrases, decorative contrasts, and
phrases such as robust, seamless, game changer, unlock value, decision-grade,
evidence-led, or bounded surface. Do not add examples, experience, metrics, or
benefits that are not present in the verified source. Return only the revised
Markdown.
```

