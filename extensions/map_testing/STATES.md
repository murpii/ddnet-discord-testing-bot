# Map Testing Channel - states & transitions

The state machine lives in `states.py` (`resolve_transition`). It's a pure function:
given the current state + an event + context, it returns a `Transition` (allowed?, next
state, new votes, ...). The callers - the buttons in `views/testing_menu.py` /
`views/rating_select.py` and the upload handlers in `manager.py` - dispatch events and
apply the result.

## States (`MapState`)

| State | Icon | Meaning |
|---|---|---|
| `TESTING` | (none) | Default after creation. Actively being tested. |
| `RC` | ☑ | Release Candidate: one ready vote cast, awaiting a second. |
| `WAITING` | 💤 | Waiting on the mapper (bugs to fix, or a moderator parked it). |
| `READY` | ✅ | Approved for release (>= 2 votes incl. a full Tester). Auto-optimized. |
| `DECLINED` | ❌ | Rejected. |
| `RELEASED` | 🆙 | Published on DDNet. |

## Events (`TestingChannelEvent`)

| Event | Trigger |
|---|---|
| `READY_VOTE` | "Ready" button -> RatingSelect (casts a vote) |
| `MOVE_WAITING` | "Waiting Mapper" button |
| `RESET` | "Reset" button |
| `RELEASE` | "Set to Released" button |
| `DECLINE` | "Decline" button -> modal |
| `AUTHOR_CLEAN_UPLOAD` | The map author's passing upload becomes the current map (a direct trusted upload, or one approved via the Approve-Upload button) |
| `AUTHOR_BUGGY_UPLOAD` | The map author's failing upload, with a matching filename |

The five button events are **not** gated by state - any tester can press any button in any
state; `resolve_transition` decides whether to allow or reject it. The two `AUTHOR_*`
events are triggered by the author uploading a `.map`, not by buttons.

Not events (handled elsewhere): initial creation -> `TESTING` (or -> `WAITING` when
force-accepting a buggy submission, `creator.py` `build_channel(state=...)`); a
non-author / filename-mismatch upload -> held for manual approval via
`ChannelUploadApproval`; channel archive / deletion (lifecycle).

## Transitions by state

Every `(state, event)` outcome. `reject` = guarded, the user gets a reason; `no-op` =
allowed but the derived state equals the current one, so the caller applies nothing.

| From \ Event | `READY_VOTE` ⁷ | `MOVE_WAITING` | `RESET` | `RELEASE` | `DECLINE` | `AUTHOR_CLEAN_UPLOAD` | `AUTHOR_BUGGY_UPLOAD` |
|---|---|---|---|---|---|---|---|
| `TESTING`  | -> RC ¹           | -> WAITING   | -> TESTING ⁰ | -> RELEASED | -> DECLINED | no-op            | no-op       |
| `RC`       | -> READY / RC ²   | -> WAITING   | -> TESTING   | -> RELEASED | -> DECLINED | no-op / TESTING ³ | -> WAITING |
| `WAITING`  | reject (reset first) | reject (already waiting) | -> TESTING | -> RELEASED | -> DECLINED | RC / TESTING ⁴ | no-op |
| `READY`    | reject (already ready) | -> WAITING | -> TESTING | -> RELEASED | -> DECLINED | -> RC ⁵          | -> WAITING |
| `DECLINED` | reject            | -> WAITING ⁶ | -> TESTING   | -> RELEASED ⁶ | reject (already declined) | RC / TESTING ⁴ | no-op |
| `RELEASED` | reject            | -> WAITING ⁶ | -> TESTING   | reject (already released) | reject (can't decline released) | RC / TESTING ⁴ | no-op |

Notes:

0. `RESET` from `TESTING` is still a transition - it clears any standing votes.
1. First ready vote -> `RC`.
2. Second vote -> `READY` once there are **>= 2 distinct votes including >= 1 full
   Tester** (this also triggers a map re-check + optimize before finalizing); otherwise it
   stays `RC` (e.g. a second Trial vote while no full Tester has voted - the voter is told
   a full Tester is still required).
3. `AUTHOR_CLEAN_UPLOAD` from `RC`: **no-op** if the standing vote is a full Tester's;
   drops to `TESTING` if `RC` was held only by Trial vote(s).
4. `AUTHOR_CLEAN_UPLOAD`: -> `RC` if a full Tester had voted (one placeholder Tester vote
   is kept, so a single confirming vote re-readies it), else -> `TESTING`. From `DECLINED`
   / `RELEASED` this uses whatever votes were standing - an edge case, but reachable while
   the channel still exists.
5. `READY` always includes a full Tester vote, so a clean author upload always drops it to
   `RC`.
6. **Permissive edge:** the buttons aren't state-gated, so the code allows these from a
   terminal state even though they're unusual. Only the rejects listed above block an
   event.
7. `READY_VOTE` additionally rejects, in any state, if the actor **is the map's author**
   ("can't ready your own map") or has **already voted** ("a different tester needs to cast
   the next vote").

## Transitions by event (what each event does + vote effect)

| Event | Allowed from | Rejected from (reason) | Next state | Votes |
|---|---|---|---|---|
| `READY_VOTE` | `TESTING`, `RC` | `WAITING` (reset first), `READY` (already ready), `DECLINED`/`RELEASED` (can't ready in state X); plus author / already-voted guards | `state_from_votes(votes + {actor})` -> `RC` or `READY` | add `{actor: tier}` |
| `MOVE_WAITING` | any except `WAITING` | `WAITING` (already waiting) | `WAITING` | unchanged |
| `RESET` | any | (none) | `TESTING` | **cleared** (`{}`) |
| `RELEASE` | any except `RELEASED` | `RELEASED` (already released) | `RELEASED` | unchanged |
| `DECLINE` | any except `DECLINED`/`RELEASED` | `DECLINED` / `RELEASED` | `DECLINED` | unchanged |
| `AUTHOR_CLEAN_UPLOAD` | any (applied only if derived state differs) | (none) | `state_from_votes(vote_fallback(votes))` -> `RC` or `TESTING` | `vote_fallback` |
| `AUTHOR_BUGGY_UPLOAD` | `RC`, `READY` -> `WAITING`; any other state is a no-op | (none) | `WAITING` (from RC/READY) else unchanged | `vote_fallback` (when moving) |

`AUTHOR_CLEAN_UPLOAD` and `AUTHOR_BUGGY_UPLOAD` never reject; `resolve_transition` returns
the derived state and the caller (`manager.apply_author_update` / `waiting_for_bugs`)
simply does nothing when that equals the current state.

## Vote model

Votes are a `dict[user_id -> tier]` where tier is `"tester"` or `"trial"`
(`role_tier(member)`).

- **`state_from_votes(votes)`** derives the state from the vote set:
  - `READY` iff **>= 2 distinct votes including >= 1 full Tester**,
  - `RC` iff **>= 1 vote**,
  - else `TESTING`.
- **`vote_fallback(votes, bot_id)`** keeps **one placeholder Tester vote** (owned by the
  bot) if any full Tester had voted, else returns `{}`. Used by the author-upload events so
  an evaluated map drops to `RC` needing just one more vote (no real tester is locked out),
  or to `TESTING` if only Trials had voted.

### READY_VOTE composition

- First vote -> `RC`; a second qualifying vote -> `READY`.
- An extra Trial vote while only Trials have voted -> stays `RC` with a "a full Tester is
  still required" notice.
- Intentional: a Trial **may** cast the deciding vote once a full Tester has voted; two
  Trials alone never reach `READY`.
- Reaching `READY` sets `requires_map_recheck`, so the finalize path re-runs the map check
  and optimizes the map before the channel is set to `READY`.
