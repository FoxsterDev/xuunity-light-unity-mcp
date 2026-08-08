# Structural Compile Diagnostics Retro

Date: `2026-08-06`
Status: `implemented and live-validated in current source`

## Finding

Unity can reject an assembly definition before `csc.exe` runs. Duplicate or
unresolved references and invalid `.asmdef` JSON are written to `Editor.log`,
while the compilation callback can retain older C# diagnostics. A post-settle
envelope that reports only those callback rows can therefore hide the current
root cause and send an operator toward an unnecessary cache rebuild.

## Implemented Contract

- Refresh, compile, and direct-test post-settle normalization scans the
  editor-reported log only when Unity's `scriptCompilationFailed` flag is set.
- The read is bounded to the current bridge-generation offset. An unavailable
  or rotated anchor is refused; the wrapper never widens silently to a
  prior-session tail.
- Structural rows are typed, deduplicated, and placed before secondary compiler
  diagnostics so compact output keeps the decision-bearing root cause.
- The envelope reports `assembly_definition_error`, scope provenance, structural
  count, and an action to inspect `.asmdef` references and the scoped log before
  considering cache cleanup.
- If Unity proves failure but no current diagnostic is available, the response
  says `compiler_diagnostics_unavailable` rather than inventing a cause.

## Validation

- Focused host contracts cover stale C# rows plus a current structural error,
  previous-session exclusion, unusable-anchor refusal, compact preservation,
  deduplication, and shared refresh/compile/test behavior.
- A live Unity `2022.3.62f3` project received a temporary assembly definition
  with one duplicate reference. Refresh returned a session-scoped
  `asmdef_duplicate_reference` verdict; after removing the probe, the next
  refresh returned authoritative compile green.
- Package self-tests passed EditMode `68/68` and PlayMode `18` passed with one
  expected skip. The editor was closed and the consumer package files were
  restored byte-for-byte.

## Reusable Lesson

Filtered diagnostics are verdict-bearing evidence, not presentation polish.
When a secondary cache can lag the current failure, merge the authoritative
source into the compact envelope and disclose its scope. Never trade a missing
diagnosis for an unscoped guess.
