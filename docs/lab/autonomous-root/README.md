# Autonomous TV administration prototype

A separate signed web service reacquires a temporary namespace root context over
loopback SDB and keeps an authenticated worker alive. This is autonomous
reacquisition, not a firmware root patch. It is prepared for the existing QN90A
(.NET Core 3.1) and S90D (.NET 6) profiles. The experimental native worker retains
its small .NET entry bridge and managed fallback. Earlier managed releases passed
reboot and service recovery trials; those results do not qualify the current
native candidate's complete lifecycle. Both TVs ran native-selected 0.7.52 in
bounded trials; clean boot, standby/power interruption and full endurance remain
open. See the [current release scope](../../project/release-readiness.md) and
[dated qualification snapshot](native-worker/MIGRATION.md#current-qualification-snapshot).
Signed-package success is not proof of on-boot entitlement, Node
runtime support, SDK admission, SMACK access or full privileged API coverage.

Firmware mismatch diagnostics report the JSON-quoted expected line and observed
`Version` lines from `/etc/prd_info.ini`. Whitespace and control characters remain
visible; no other identity-file fields are included. Long diagnostics are marked
`[truncated]`. The exact-match firmware guard is unchanged. Authenticated status
retains the latest failed attempt in `last_acquisition_error` even when
`last_error` becomes the retry-budget message. This is historical error evidence,
not a worker-health result; an explicit new start clears it.

See [persistent worker capabilities](CAPABILITIES.md) for the new transfer, job,
app-user, result and readiness API, its CLI commands, and validation limits.

## Components

- `agent/service/main.js`: signed service, configured on-boot/auto-restart; starts the
  maintenance endpoint before attempting root. Disabled by default.
- `agent/service/agent.js`: exact firmware/runtime/SDK-launcher hashes, per-attempt
  ephemeral keys and token, loopback SDK, private mount namespace, detached worker.
  At most eight acquisitions per service lifetime, with capped exponential delay.
  Runtime hashes are checked by SDK before executing the payload: the S90D's
  package label cannot stat `/usr/bin/dotnet` directly. The guarded script is
  staged on the TV, and its invocation is bounded below the SDK command limit.
- `agent/service/api.js`: HTTPS port 28443 with a required, exactly pinned client
  certificate. No unauthenticated routes, browser CORS or dashboard integration.
  Root protocol listens only on loopback and authenticates frames with HMAC.
- `agent/service/policy.js`: bounded requests and durable intent journal. A duplicate
  request ID is rejected even after restart. A lost response remains uncertain;
  commands are never automatically replayed. Logs store command hashes, not text.
- `agent/client.py`: enrolled computer client with server certificate validation and an
  exact certificate pin. No network retries. Explicit command files allow owner
  administration with full shell semantics inside the agent's privilege context.
- `tvsetup.autonomous_root`: local per-device preparation using the shared
  Builder, signing pins, source hashes and independent package verification.
  It does not install, change Developer Mode, reboot or touch existing apps.

Vendor source is pinned in `UPSTREAM.json`: Vetro's MIT-licensed SDK/protocol/tar
modules and the upstream Samsung TV root project's Unlicense C# payloads.
Licenses are beside their source. Payloads are compiled locally for each TV;
upstream precompiled DLLs and certificates are not used.

## QN90A pilot observations — 2026-10-11

Version 0.1.2 was installed separately on firmware `T-NKM2AKUC-2301.1`.
With Developer Mode Host PC IP set to loopback and SDB restarted, the manually
started service acquired an authenticated UID/EUID/GID/EGID 0 worker. Both
disable/re-enable and deliberate termination of that worker resulted in a new
authenticated worker. Production telemetry continued reporting during these tests.
Restoring the former developer host and restarting SDB restored computer access;
it also terminated the worker and prevented subsequent loopback acquisition.
Thus this firmware supports the TV-local connection described by Vetro; the
earlier failed connection did not establish a different firmware constraint.

The installer registered this service's on-boot/auto-restart flags as false,
despite the manifest. After a consistent database backup, a guarded transaction
changed only `MiniRoot01.Service` to true/true. Readback and database integrity
passed. Two subsequent boot IDs were observed: the submitted reboot and an
additional owner-operated reboot. The owner confirmed using only power controls,
not manually launching the administration app. Root returned on both boots with
the loopback host retained. The intervening loss of connectivity coincided with
the additional reboot; an early 90-second check was insufficient to reject startup.

On the second boot, Samsung TV viewer was foreground and telemetry had not
started through Hub. Opening the unchanged Hub restored fresh telemetry. This
verifies coexistence, not reliable Hub foreground startup on every boot.
Terminating the administration service with SIGKILL then produced a new service
and authenticated root worker before a 45-second rescue launch. The rescue unit
had never executed and its timer was canceled. All 54 checked installed and
protected-file hashes matched. Physical AC-power removal was not tested.

The private deployment journal retains signed recovery packages, command intents,
results and the database backup location. A database flag is not proof of boot
entitlement, and these observations do not establish which signing tier suffices.

## S90D pilot observations — 2026-10-11

Version 0.1.5 was verified on `T-PTMDAKUC-0090-2130.0`; QN90A remains on its
verified 0.1.2 build. Two compatibility fixes were needed on S90D: its
`User::Pkg::MiniRoot01` label cannot stat the runtime binary, so the pinned hash
checks execute in SDK before the payload; the resulting script must be staged
because an inline command exceeds the SDK transport's safe 510-byte limit.
No SMACK permissions were relaxed. Both guards have regression tests.

The S90D acquired authenticated UID/EUID/GID/EGID 0, recovered after disable/enable
and deliberate worker termination, and restored external SDK access during the
timed trials. Its boot flags required the same guarded, backed-up registration
change as QN90A. After reboot, both root and telemetry returned without manual
app launches. Root was confirmed at approximately 119 seconds of uptime; do not
treat a 90-second observation cutoff as proof that startup failed.

Terminating registered service PID 5158 produced PID 5709 at 149.84 seconds
uptime, before the rescue launch at 194.924 seconds. On this firmware the separate
JavaScript runtime remained alive and kept the same root worker. This verifies
registered-service process restart, not termination/recovery of that separate
runtime. The rescue timer was subsequently inactive/unloaded. All 50 checked
installed and protected-file hashes matched, and both TVs had fresh telemetry
and authenticated root connections at final verification. Physical AC-power
removal was not tested.

## Service restart during maintenance

Use [restart-service.sh](../../../agent/restart-service.sh) through the existing admitted SDK
transport, with the per-device setup lock, pending-run check and independent SDK
rescue already in place. On S90D the app-user launcher cannot read the WRT
process identity; do not relax its permissions to run this check.

Before opening SDK maintenance, bind the **HTTPS listener's WRT PID and start
ticks** through the authenticated root connection, and record the boot ID,
selection, enrollment and retained-job hashes in the private operation journal.
The PID printed by `app_launcher -k` belongs to the registered service wrapper
and is not sufficient to identify the JavaScript host.

Run the exact reviewed script with `BOOT_ID WRT_PID START_TICKS` as its three
arguments. It stops the registered service once, waits up to 120 seconds for the
bound WRT host to disappear, confirms the wrapper is stopped, then submits one
launch. It refuses changed identities, unreadable process state, timeout and
unexpected application status. Keep the SDK window long enough for this wait
and arrange guarded restoration of loopback before native acquisition; preserve
the independent rescue until acceptance. A failed or lost response requires
inspection, not another invocation.

`SERVICE_START_SUBMITTED` is only a launch acknowledgment. Acceptance requires a
different WRT host and ready native worker on the same boot, unchanged selection
and protected state, and continued readiness after owned helper cleanup and
rescue retirement. Keep the signed fallback and original journals. This procedure
does not qualify reboot, standby or unattended recovery.

The local regression uses a real Linux process whose exit lags behind the
wrapper's stopped status. Run it with `python3 -m unittest discover -s tests -p
service_restart_test.py` on Linux; it also covers stale identities, a host that
does not exit, and unexpected application status.

S90D passed this procedure on unchanged signed 0.7.52: stop, host-exit wait and
launch took about 115 seconds. A different WRT host and native worker remained
ready before and after helper cleanup. See the
[restart evidence](native-worker/s90d-service-restart-fix-results.json).

## Local preparation and tests

From the repository root:

```
python3 -m tvsetup.autonomous_root --device qn90a
python3 -m tvsetup.autonomous_root --device s90d
node --test tests/autonomous-root.test.cjs
node tests/autonomous-root/protocol.test.cjs
```

Preparation places packages, provisioning, certificates and a content manifest
under the private toolkit's `autonomous-root/DEVICE/RUN/`. Keys/configuration are
not embedded in the WGT or committed to source. The provision folder contains
only the server key, server certificate, client public certificate and disabled
configuration. The client private key remains on the computer. Credentials expire
in one year; renewal requires deliberate re-enrollment, not bypassing TLS checks.

The request journal admits at most 1,000 unique operations before maintenance is
required. It stores pending intents across restarts, not command output. An
uncertain operation requires inspection; a new request ID is not a safe retry.

## Request phase timing

Authenticated, validated worker requests (`/v1/exec`, `/v1/op` and the binary
file endpoints) return a `Server-Timing` header. Fixed metric names report
milliseconds from the service's monotonic clock:

- `journal_begin`: durable intent publication, including automatic archive work
  if needed. A thrown publication is timed too.
- `worker`: dispatch through the resolved/rejected worker response, including
  worker persistence, transport and scheduling delays.
- `journal_finish`: attempted durable result publication, including confirmed
  worker refusal handling. Uncertain operations do not acquire a completion just
  to supply this metric.
- `handler`: request-handler entry through header preparation. It includes body
  receipt, validation and response preparation, and contains the phase intervals.

Journal phases also contain `journal_begin_file_sync`,
`journal_begin_directory_sync`, `journal_finish_file_sync` and
`journal_finish_directory_sync` metrics when those barriers were attempted.
Their `dur` is the aggregate elapsed time in the corresponding synchronous sync
calls; `desc` gives the call count. Automatic archive work aggregates its file,
archive-parent and active-journal syncs into the begin phase. A failed sync counts
as an attempted call. These are nested measurements: do not add them to their
containing journal phase when calculating a total. They include descheduling and
runtime overhead, so they are not CPU time or proof of flash latency. The journal
JSON and archive formats remain unchanged for existing recovery packages.

Only attempted phases appear. Read-only operations omit journal metrics, and
pre-dispatch journal failure omits worker/result metrics. Values reset for each
keep-alive request. Headers contain no commands, paths or request identities.
Enrollment and browser restrictions apply before timing is enabled. Status and
asynchronous native-administration routes do not report these worker phases.
The [Server Timing format](https://www.w3.org/TR/server-timing/) carries durations;
clients must not treat them as outcomes, clock synchronization or safe-retry
receipts. Journal semantics and sync barriers are unchanged.

`handler` excludes TLS setup before handler entry and response transmission after
header preparation. Its difference from client-observed request time is not a
pure network measurement. These intervals can locate a delay but cannot by
themselves distinguish storage latency from descheduling or prove causality.

## Required device acceptance, in order

1. Use the shared deployment engine/device lock and an immutable source checkout
   for a separately scoped package/provisioning run. Record original package
   registration, Developer Mode host, signing trust and all owned file hashes.
   The current preparation command intentionally has no ad hoc install path.
2. Install disabled. Provision private app data with reviewed ownership/SMACK.
   Manually start only this service, then verify mutual TLS from the Mac, reject a
   foreign certificate, and verify disabled state before changing SDK admission.
3. Establish a timed rollback for a short loopback-host trial using the existing
   temporary root transport. Save the exact former Host PC IP. Do not assume an
   IP write affects the running SDK without readback and connection testing.
4. Require authenticated UID/EUID/GID/EGID 0, fixed identity commands, unchanged
   real passwd/key hashes and still-fresh production telemetry. Disable must
   stop reacquisition and terminate the authenticated channel/worker.
5. Restore the original host and verify ordinary Mac SDK access before canceling
   the rollback. Test service failure and recovery before enabling across boots.
6. Only after that, perform an explicitly scheduled reboot and observe a new
   boot and agent without manually launching either service or Hub. Test both
   devices independently; do not infer S90D support from QN90A.

Loopback Developer Mode can reject the Mac's direct SDK connection. If the signed
service fails before acquiring root, its disable endpoint cannot itself restore
SDK admission. Physical fallback is Samsung Apps → Developer Mode → restore the
Mac's Host PC IP and restart. Automatic worker/service recovery does not replace
this physical fallback when boot execution or TLS provisioning fails.

Root is still constrained by firmware, SMACK and mount namespaces. Do not claim
universal access or a writable firmware filesystem. Existing Hub routing,
telemetry, pairing, debloat choices and the read-only dashboard are unchanged.

## Client examples after device acceptance

```
python3 agent/client.py --config PRIVATE_RUN/client.json status
python3 agent/client.py --config PRIVATE_RUN/client.json requests
python3 agent/client.py --config PRIVATE_RUN/client.json exec --command-file PRIVATE_SCRIPT
python3 agent/client.py --config PRIVATE_RUN/client.json disable
```

`enable` persists enabled state and permits boot-time attempts; `disable` persists
disabled state. Neither command changes the Developer Mode host. Closing the root
channel does not roll back settings made through administrative commands.


## Optional QN90A Hub boot handoff — 2026-10-11

QN90A administration service 0.1.6 adds opt-in `boot_launcher: true` in private
configuration. It is disabled by default and rejected for S90D. After root is
ready, a bounded once-per-boot action requests the existing signed Hub relay;
it respects other apps, records intent before submission, and never replays an
uncertain launch. A claim under `/tmp` survives service restarts within that boot.
Commands are encoded to preserve shell bytes through the older root worker.

This action alone does not select a startup source or suppress Live TV. Combined
with the signed ISP-bound Hub trial, one supervised QN90A reboot reached Hub at
about 118 seconds without Live TV picture/audio or user intervention. The long
blank wait remains a limitation. See the [direct-boot results](../devices/qn90a/direct-boot.md#supervised-isp-source--autonomous-agent-trial--2026-10-11)
for exact boundaries, status-window limitations and recovery.

`tvsetup.agent_transport.AgentTransport` is an explicit certificate-pinned
transport for scoped administration trials. Its SDK-shaped inspection methods
run as the enrolled root worker, so they are not proof of SDK-user permissions.
It journals commands before submission, never retries uncertain writes, and
verifies staged file hashes. Package installation still requires the normal
SDK installer and shared setup engine.


QN90A follow-up: a separately journaled metadata override gives only
`MiniRoot01.Service` on-boot priority 99. Two software reboots reached Hub at
109.63 and 109.61 seconds, about eight seconds faster, with background source
initialization retained. Physical panel/audio observation of these two boots
is pending. The override is in the local registration database, not the signed
0.1.6 manifest, and may need deliberate reapplication after package replacement.
The exact AMD library contains a 90-second user-login fallback consistent with
the remaining delay; its execution was not dynamically traced. See the
[queue investigation](../devices/qn90a/direct-boot.md#startup-queue-investigation--2026-10-11).

## Journal rotation update — QN90A 0.1.7

The updated agent automatically archives a full command journal before accepting
another command. It commits a complete SHA-256-addressed archive before reducing
the active journal to unfinished requests plus the latest 100 completed entries.
Unfinished requests are never discarded or replayed. Archived IDs (including
legacy SDK maintenance archives) remain replay-protected across restarts. Archives
contain command hashes and outcomes, not shell command text. Archive files are
retained; deleting them would remove their replay history.

An enrolled administrator can also archive explicitly:

```sh
python3 agent/client.py --config /absolute/private/client.json archive-journal
```

The client reads `/v1/requests` and submits its digest to
`POST /v1/journal/archive`. The existing mutual TLS enrollment pin and browser
origin rejection apply. A stale digest is rejected; maintenance is serialized
with command execution and works without a connected root worker. Storage failure
blocks further execution until diagnosis/restart. A journal consisting entirely
of unfinished requests still refuses new commands rather than discarding them.

Host tests cover full-journal rotation, pending records, archived replay after
restart, stale digests, interrupted file replacement, corrupt archives, symlinks,
legacy archives, and authenticated maintenance while the root worker is disabled.
Version 0.1.7 was installed and its signed contents verified on QN90A. With the
root worker disabled, authenticated maintenance archived its 1,000-entry journal
and retained 101 active entries: 100 completed requests and one unresolved
request. The complete archive was verified on-device by its SHA-256. Existing
enrollment certificates were preserved. S90D has not received this update.

The upgraded service returned automatically after a software reboot. All 22
package members, enrollment certificates, archive digest and restored service
boot flags passed readback. An archived request ID was rejected after restart.
Native Hub recorded its first-render callback at 12.914 seconds with web Hub
autolaunch suppressed. This is software timing, not a fresh physical panel/audio
observation or an isolated performance comparison.
