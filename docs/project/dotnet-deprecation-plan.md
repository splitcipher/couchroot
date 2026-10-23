# Couchroot .NET deprecation plan

Accepted 2026-10-17; status clarified 2026-10-19. Implementation and validation of
this telemetry integration are local only. No TV or NAS deployment or hardware acceptance
has occurred for these changes. Earlier device trials remain historical evidence.

## Accepted scope

QN90A basic telemetry uses the existing C collector, signed managed settings
adapter and shared Python setup engine. Keep CPU, memory, network, storage,
uptime, collector overhead and receiver history. Continuous QN90A app/process
inspection is retired, including on the managed fallback. S90D's current behavior
and inspector support remain supported.

Telemetry stays optional. Preserve preferences, pairing, Samsung Home and web
fallback, exact recovery inputs, firmware/identity checks and journals. Launcher
operation must not depend on telemetry, the NAS or a management computer.
Full .NET removal is not a home-use requirement; the settings adapter and existing
provisioning/recovery helpers retain their pinned managed builds and tests.

## Implemented and locally tested

- Component-specific build prerequisites, separate identity/managed guards,
  explicit assembly manifests, and separate web/offline and managed CI checks.
  See [validation commands](release-readiness.md). Hosted CI is separate evidence.
- Opt-in QN90A native telemetry preparation, verified staging, marker handoff,
  boot submission and journaled rollback through the existing setup engine.
  The existing adapter handles settings; no CLR-free runtime is claimed.
- QN90A inspector retirement in the managed collector, receiver and dashboard.
  Older senders' basic counters remain accepted and stored inventory is hidden.

Use the [native telemetry guide](../guides/native-telemetry.md) for the installation,
recovery and local-test contract, and [shared monitoring](../guides/telemetry.md)
for the receiver and settings context. Local maintenance is tracked in the
[cleanup tracker](qn90a-cleanup-plan.md).

## Remaining QN90A acceptance

A separately authorized hardware session must establish:

- Reliable firmware admission and private-file access, boot, physical power cycle,
  standby/wake, and normal TV/remote use without startup delays or regressions.
- Exactly one sampler, correct enable/disable and endpoint changes, and no duplicate
  sampler after repeated Hub entry. Invalid preferences/credentials fail safely.
- Fresh receiver data and correct history, bounded crash restarts and restart-rate
  exhaustion, and recovery after loss of the management connection.
- Exact rollback plus verified resumed managed transmission. Restoring a marker
  alone is not proof that collection resumed.
- Several days of normal use without restart loops or unexplained resource growth.
  Measure combined managed/native cost; individual collector RSS is insufficient.

Stop after this acceptance and recovery rehearsal. Further rewrites are not
prerequisites for personal home use.

## Deferred work and limits

Defer one-shot helper consolidation, QN90A web boot-helper replacement, S90D
AT-HUB/saver/splash rewrites, S90D telemetry migration/native graphical launcher,
and removal of all .NET dependencies.
Revisit an item only for a demonstrated reliability, resource or maintenance issue.

The root agent now packages only the native worker/acquisition path. The small
managed entry bridge remains, but the managed worker and its automatic fallback
have been removed; see the [agent support contract](../../agent/README.md#support).
Historical managed-return recovery requires the retained previous signed package,
checkout and journals. Native-only entry work remains deferred. The
[current acceptance record](release-readiness.md) separates recorded root-agent
results from open hardware checks and telemetry acceptance.

Keep existing helpers, manual diagnostics, exact artifacts and executable paths
needed by installations and recovery journals. Preserve current S90D recovery;
see its [boot assessment](../lab/devices/s90d/native-boot-assessment.md). Keep only the
active candidate and known-good rollback as supported choices, without deleting
retained recovery evidence. Freeze new managed features while allowing necessary
compatibility fixes. Do not add a backend, supervisor, message bus, capability
registry, native webview host or general-purpose control channel. Reuse the
existing build recipes and private-library hash checks.

## Historical review findings — 2026-10-16

These observations explain the scope decision; they are not unfinished tasks.

1. The web UI and C/EFL native Hub already ran without a CLR in the UI itself.
   Their different startup paths addressed actual firmware differences.
2. The existing [C collector](../../telemetry/native-collector/README.md)
   had passed short ingestion/rollback trials on both TVs. Recorded RSS was
   2.98–3.88 MiB versus managed snapshots of 22.77–24.29 MiB. Those were individual
   process measurements, not total-TV savings or long-term acceptance; see the
   [trial evidence](../lab/research/native-service-research.md).
3. Native counters lacked managed inspector snapshots, and startup/settings
   integration was unfinished. The accepted scope subsequently retired QN90A
   inspector collection and integrated the existing settings adapter locally.
4. Managed code handled both brief privileged acquisition and a resident
   authenticated worker. Replacing either would be separate work; see
   [root-agent research](../lab/autonomous-root/README.md).
5. SDK and runtime checks were broader than necessary. Component prerequisites
   and separate identity/managed guards subsequently narrowed that coupling.
6. Older bootstrap research and later native-Hub results described different
   stages of progress. A working launcher boot path did not establish acceptance
   of the new telemetry integration or installer. Keep those evidence boundaries.
