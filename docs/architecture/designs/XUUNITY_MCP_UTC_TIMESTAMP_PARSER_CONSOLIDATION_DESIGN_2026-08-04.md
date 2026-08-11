# XUUnity MCP Design: Consolidate The UTC Timestamp Parser

Date: `2026-08-04`
Status: `implemented in current source` — 2026-08-11. Recorded because the failure it prevents already happened once.
Size: small. One shared helper, five thin call sites, no behaviour change intended.

## Why This Exists

Timestamps are produced as UTC everywhere in this system and always have been: the host writes
`time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`, the editor package writes
`DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")`, and the `Z` on the wire means what it says. Parsing them back
into epoch seconds is therefore a one-line operation with one correct answer, `calendar.timegm`.

That answer was already established in five modules. A sixth parser was then added to `server_health.py` using
`time.mktime(...) - time.timezone`, which reads the struct as *local* time. It was exact on a development host
whose standard time runs year-round, and wrong by 3600 s wherever daylight saving applies — in the opposite half
of the year in the southern hemisphere. The unit suite passed on that host, and the error fed the log-lane
staleness threshold and the log-rotation guard, both of which decide whether evidence is accepted.

The convention was not missing. It was uncentralised, so diverging from it cost nothing at author time and was
invisible at review time. Five copies are five opportunities to write the wrong one again.

## Current State

| Module | Function | Empty input returns |
| --- | --- | --- |
| `templates/server_bridge_journal.py` | `parse_journal_utc_timestamp` | `0.0` |
| `templates/server_operation_evidence.py` | `parse_utc_timestamp` | `None` |
| `templates/server_scenario_polling.py` | `parse_utc_seconds` | `None` |
| `templates/server_bridge_state.py` | `parse_utc_timestamp` | `None` |
| `templates/server_bridge_state.py` | inline conversion in `heartbeat_age_seconds` | n/a |
| `templates/server_health.py` | `_parse_stamp_utc` | `0.0` |

Four names, one conversion, and two different contracts for absent input.

## Proposal

Add one canonical helper and reduce every site to a call. `server_core.py` is the cycle-free home and now owns the
conversion; per-module wrappers retain their established empty-input contracts.

```python
def parse_utc_timestamp(value: Any) -> float | None:
    """Epoch seconds for a `...Z` stamp, independent of the host timezone and DST rules."""
```

**Keep the differing empty-input contracts at the call sites, not in the helper.** `0.0` and `None` are
load-bearing: `0.0` is falsy and flows through arithmetic, `None` forces an explicit check. Merging them silently
would change behaviour in callers that currently rely on one or the other, which is a larger change than this is
worth. Thin per-module wrappers preserve each contract:

```python
def parse_journal_utc_timestamp(value: Any) -> float:
    return parse_utc_timestamp(value) or 0.0
```

## What This Buys

- One place where the conversion can be wrong, instead of six.
- The forced-timezone regression test in `tests/test_tool_argument_contract.py`
  (`HostileTimezoneStampTests`) then guards every consumer rather than one. Today it covers only the
  `server_health.py` copy; the other four are correct but unguarded by any timezone test.
- A reviewer can see the convention exists, which is the part that failed here.

## Non-Goals

- Changing the wire format. It is already UTC and correct on both sides.
- Changing any empty-input contract.
- Introducing a datetime library dependency. `calendar.timegm` plus `time.strptime` is sufficient and matches the
  existing style.

## Risk

Low, but not zero: five call sites across modules with different absent-value semantics, and
`heartbeat_age_seconds` performs its conversion inline rather than through a named function. The verification bar
is the full host suite plus the three-OS CI matrix, and no payload field may change value. If any test needs
editing to accommodate the refactor, that is a signal the refactor changed behaviour and should be reconsidered
rather than accommodated.

## Note On The Timezone Test

`HostileTimezoneStampTests` asserts *invariance across timezones*, which no same-zone test can do — the defect
above passed the entire suite on a host without daylight saving. It forces `Europe/Berlin`, `America/New_York`,
`Australia/Sydney`, and `UTC`, and requires an exact match against `calendar.timegm`. It skips on Windows, where
`time.tzset` does not exist, so the guarantee comes from the Linux and macOS legs of the matrix. Keep the test
after consolidation; its value rises when it covers one shared helper instead of one of six copies.
