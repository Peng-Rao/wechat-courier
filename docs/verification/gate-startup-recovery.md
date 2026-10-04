# Abnormal Shutdown: Agent and Gate Recovery Verification

Date: 2026-10-05 (Asia/Shanghai).
Branch: main. Baseline: ef3aee68131559a6064256db61ce7260cd024e73.
Product version remains 1.0.0. The results below were captured before delivery;
the user subsequently requested a commit and package on main, without a push.

## Implemented Behavior

- Keep the existing Agent mutex and stable lease path. File presence alone is
  no longer treated as evidence of a live owner.
- Record schema version 2, owner PID/creation time, Windows session, token
  AuthenticationId and LSA login time before modifying the gate. No COM
  apartment is created to obtain this identity.
- Preflight all stable, legacy and orphan temporary lease records before
  applying changes. Archive exited/reused process records without patching
  another process. Restore live gates only after identity, version, writable
  RVA and byte validation, followed by readback.
- Restore the screen-reader flag only when recorded ownership and the current
  login identity are both proven. Legacy records cannot authorize this change.
- Corrupt/conflicting evidence is preserved. Only a uniquely verified,
  supported Weixin in the current login can be restarted automatically once.
  Persist the reservation before closing, then archive after confirmed exit.
  Relaunching the GUI or Agent does not reset the unfinished fault's budget.
- Persist cancellation even before the first restart. Cancelled or expired
  login waiting does not resume automatically on relaunch; manual recovery
  detection can confirm a later safe login without another restart.
- Start Named Pipe and heartbeat before asynchronous native recovery. Create
  no UIA engine until lease recovery completes, and block tasks until the
  subsequent actual health check permits them.
- Bound native recovery with an independent service-thread watchdog. Keep
  `--recover-gate` UIA-free and prohibit automatic Weixin restart in that mode.
- Reconnect an unexpectedly exited idle Agent at most once. Other live Agent
  ownership and normal GUI shutdown cannot start a reconnect loop.
- Publish ordered `gateRecovery` health state; expose recovery, login,
  cancellation, occupation and failure states with consistent task locks.
  Export lease classifications, process identities and archive metadata.
- Do not read, clear or replay the task safety journal in Gate recovery.
  Gate-scoped cancellation does not acknowledge a destructive task boundary.

## Automated Results

Final commands were run against the completed implementation:

| Check | Result |
| --- | --- |
| `python -m pytest -o addopts= -q` | 1249 passed, 1 skipped; 92.15 seconds |
| Lease/recovery/runtime/client/process tests | 53 passed |
| PySide6 `QUICK_TEST_MAIN`, entire `tests/qml` directory | 119 passed, 0 failed, 0 skipped |
| Real QML + BackendController GUI smoke | Passed at 960x680 and 1320x880 |
| `python -m compileall -q app tests` | Exit 0 |
| `git diff --check` | No whitespace errors |

The single pytest skip is the existing external `qmltestrunner` availability
check. The full QML suite was separately executed through the bundled PySide6
QuickTest runner, rather than treated as covered by that skip. Existing mock
and deprecated signal-parameter QML warnings remain; the new banner tests have
no failures.

Coverage includes exited/reused PIDs, changed logins with reused session
numbers, legacy formats, corrupt/truncated records, orphan temporary files,
conflicting originals, live Agent ownership, permission failure, preserved
task boundaries, restart reservation crashes, login timeout/cancellation,
manual recovery, ordered health and direct RPC task blocking.

Real child-process tests run AgentRuntime and authenticated Named Pipe RPC
with an isolated fake Win32 backend. They verify heartbeats during recovery,
task rejection, abrupt process exit, durable attempt limits across a new
Agent, and watchdog termination of a hung native call. A production
`--recover-gate` invocation also archives an isolated old-schema lease whose
recorded process has exited, without UIA or Weixin restart.

The GUI smoke uses the actual QML and controllers, temporary QSettings and a
fake Agent client. It confirms the recovery banner/top-bar state, disabled
start during recovery, and restored start permission after newer verified
health. It makes no RPC call and starts no business task. Screenshots were
visually checked; local evidence is under the ignored
`.superpowers/sdd/gate-startup-recovery/` directory and is not packaged.

## Real-Machine Scope and Remaining Validation

Read-only Win32 inspection confirmed the installed Weixin 4.1.13.65 process
and documented token/LSA identity access. Its native window class is
`Qt51514QWindowIcon`, not the UIA class `mmui::MainWindow`; recovery uses native
window styles only as login preflight, never as proof of automation readiness.

This run did not restart or kill the user's Weixin, modify its gate, send a
message, or submit a friend request. No blue screen was induced. The user's
original blue-screen incident still requires its diagnostic evidence and a
field restart/login acceptance check. Process simulations and GUI smoke do
not constitute proof that that specific incident has been reproduced.

The implementation verification did not include a build, commit or push.
The authorized delivery follow-up uses the same product name and version,
without QSettings migration or business-policy changes.
