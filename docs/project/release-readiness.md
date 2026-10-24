> Phase 4 removes the managed root worker. Historical managed-return acceptance
> rows below require the retained previous package. The native-only package must
> be accepted on both TVs, including restart/job recovery, bounded native bootstrap
> recovery, foreign-certificate rejection and independent SDK rescue.
>
> Phase 4 retires the pure-native experiment. Its historical acceptance rows below
> remain recovery context, not a new installation plan. WebView is the experimental
> native option and still requires fresh hardware acceptance.

# Current acceptance — 2026-10-24

| Component / workflow | Recorded hardware result | Still open |
| --- | --- | --- |
| Signed web Hub and shared telemetry | Hub/service updates and reboot startup verified on both reviewed TV profiles in the recorded rollout | Fresh-user enrollment and full setup/recovery matrix |
| Privileged setup staging (#31) | Validated on QN90A and S90D | Broader interruption/failure scenarios remain separate |
| S90D native agent 0.7.54 (#33) | Forward/reverse handoffs, root command/job, retained-job preservation, native gate and unattended reboot passed | Interrupted-upgrade fault injection and physical UI/standby/endurance checks |
| QN90A native agent 0.7.54 on exact 2310.0 | Guarded recovery, verified native executable, root command/job, retained-job preservation and owner-confirmed unattended reboot passed; see [qualification record](../lab/devices/qn90a/firmware-2310-agent-trial.md) | Standby, AC-power loss, physical Home/fallback, full setup/cleanup and interrupted-upgrade acceptance; ordinary setup profile remains 2301.1 |
| QN90A WebView launcher | Experimental; prior measurements are revision-specific | Fresh hardware acceptance |

The S90D final reboot verified the actual native executable hash, stable selection,
no pending markers and both service startup flags enabled. Original on-demand
entries and metadata were preserved; Hub/telemetry files and registrations were
unchanged, and telemetry uploaded on the new boot without errors. The successful
package trial is closed with its original journal, signed prior package and every
recovery field/file retained. Private evidence stays outside Git.

**Known installation gap:** the S90D service registration had on-boot and
auto-restart disabled despite the signed manifest. A separately approved correction
with a database backup and inverse script preceded successful reboot acceptance.
The installer and recovery verifier now inspect the exact owned registration
and refuse completion if required startup flags or enabled state are wrong.
They do not automatically repair registration or prevent the package manager
from resetting it. Verify registration after each agent package update; do not
declare unattended startup ready until a new-boot check passes. A guarded
correction remains an offline prototype requiring separate hardware acceptance;
never blindly restore a whole package database. See the
[registration guide](../guides/service-registration.md).

A successful reverse native handoff and an observed automatic SDK-host restore
are not hardware proof of interrupted-upgrade recovery. That path has local test
coverage only. Retain recovery packages, original checkouts and journals until the
rollback window is explicitly closed. Old boot-bound scripts require fresh review.

## Current acceptance gates: merged Phase 2

The rows below retain the original per-scenario checks and historical baselines.
They are not a claim that every path has been accepted. The dated results above
supersede blanket statements that no current code has run on either TV.

## Native-only pre-deploy gate (#30)

Run this read-only check against the **currently installed previous package**,
using each TV's existing enrolled client credentials, before deploying #30:

```sh
python3 -m tvsetup.native_gate --device qn90a --credentials PRIVATE_QN90A_RUN/client.json
python3 -m tvsetup.native_gate --device s90d --credentials PRIVATE_S90D_RUN/client.json
```

Exit status 0 and `"ok": true` require stable selection, `pending: null`,
`selected_implementation: "native-prototype"`, and an authenticated ready root
worker. A list-only root EXEC checks the private `worker-state` directory for
`retirement-launch.pending`, `production-launch.pending`, `state-install.pending`,
`managed-restore.pending`, `managed-launch.pending`, and **every**
`*.activation.json.pending`. Missing/unreadable directories, incomplete replies,
marker symlinks and a selection change during inspection fail the gate. The tool
never deletes markers, changes selection, acquires root or retries a request.
The agent may retain its ordinary request audit record for this read-only EXEC.

**If either gate fails or cannot complete, do not deploy #30. Recover with the
previous signed package and its matching checkout; preserve all journals and
rerun the gate afterward.** Keep that package available for rollback. A passing
gate is a snapshot, not deployment approval: avoid concurrent maintenance and
rerun it immediately before a separately authorized deployment. After deployment,
validate acquisition, restart/jobs and recovery on **both TVs**; restore the
captured previous package if acceptance fails, without clearing pending journals.

Owner-reported evidence from **2026-10-20**: both TVs reported `phase=stable`,
`pending=null`, `native-prototype`, and candidate verified. **Marker files were
not checked**, so those observations do not establish that this gate passes.
No new device inspection was performed for this change.

Remaining #28 hardware checks: inspect the private staging capture's
`stat -c '%U:%G:%a'` result and an actual SDB upload, credential cleanup, and the
10-second systemd-run reboot form with explicit root/SMACK/kdbus properties on
both models. Keep the signed web Hub and independent SDK rescue available.

## Preconditions and recovery baseline

For each model separately, record the exact candidate commit, firmware/profile,
boot ID, package hashes, signing trust and current worker/backend selection in a
private journal. Keep the original checkout for every unfinished recovery run.
Capture the existing hooks, packages, preferences, enabled markers and Developer
Mode Host PC IP; verify the independent SDK rescue and physical fallback before
changing loopback admission. Retain the signed web Hub and managed fallback.
Do not overwrite an unfinished run, enroll new trusted bytes merely to pass a test,
or publish raw logs/tokens. Use the shared setup engine, lock and journal.

In the tables, **restore baseline** means use that journal and its original
checkout to restore the captured state, verify hashes and normal SDK access, and
only then retire the timed rescue. If root is unavailable, use the
[agent recovery procedure](../../agent/README.md#recovery). Stop on an uncertain
result; inspect evidence rather than replaying an operation. Capture physical
picture/audio and remote-button behavior separately from process acknowledgements.

## QN90A owner-run checks

Use the enrolled QN90A firmware profile and its .NET Core 3.1 bridge/fallback.
All rows also require the baseline above.

| Check / PR | Preconditions | Steps | Expected result | Rollback |
| --- | --- | --- | --- | --- |
| Loaded cold boot greeting — #10 | Independent rescue armed; current native-selected agent plus retained managed fallback; agreed bounded load | Cold boot under normal load, then with owner-approved bounded startup load; record listener/worker greeting timestamps and acquisition outcome | The 10 s greeting deadline is enforced; a worker arriving in time authenticates. A late worker fails within the bound without hanging or silently exhausting recovery. Record actual root readiness; do not raise the limit to pass | Stop the load, restore the captured worker selection/package and SDK admission; verify rescue and root status |
| Normal-mode Live TV boot — #11 | A separately reviewed dispatch that actually starts native-hub in normal mode; current public installer does **not** do this | Record the normal marker and foreground; cold boot from Live TV, observe signed-Hub handoff and native presentation; repeat with another app/source taking focus | Native waits for screen/ISP/compositor and signed-Hub foreground; another app/source cancels. No premature overlay or unexplained picture/audio interruption. Mark blocked if using only the background-only installer | Restore baseline hook/dispatch and saved source; use signed web Hub |
| Standby wake and app return — #11 | Owner-approved native dispatch, Home option and saved-source policy recorded | Sleep/wake while Live TV is selected; then launch an app from native and leave it using the physical remote; repeat while another app owns foreground | Return occurs only when admission permits it; no foreground theft, duplicate native process, stuck Home grab or silent audio continuation | Restore baseline launcher/hook, preferences and source; verify physical Home and web Hub |
| Background cold boot regression — #11 | Captured ISP source/owner and background boot hook; known-good web fallback | Cold boot into background mode; record first physical render and markers; repeat after failed/disabled native admission | Existing background behavior survives; native failure falls through to the original boot chain, without stranded admission markers | Restore baseline hook and source; verify original boot chain and rescue |
| Home fallback and rearm via posix_spawn — #11 | Native Home/rearm enabled explicitly; web Hub installed | Open Live TV, press Home, observe web-Hub detour and rearm; repeat with app/source change and a delayed helper | The bounded Home attempt completes or cancels safely; no inherited-descriptor hang, duplicate launch or late focus takeover. Saved source readback matches the journaled policy | Restore baseline source/settings/hook; confirm stock Home and web fallback |
| WebView CLOEXEC startup — #11 | Existing supported QN90A WebView deployment and recoverable hook, separate from pure-native trial | Exercise background start, normal-mode handoff, standby wake and app return; inspect helper exit/FD evidence | EWK starts, remote input works and the shared helpers complete without leaked descriptors holding pipes open. Rendering and focus guards remain intact | Restore prior WebView package/hook and preferences; fall back to signed web Hub |
| Root result capture and serial scoping — #12 | Both TVs connected to SDB; explicit QN90A serial; exact package/SDK SMACK labels recorded | Run an innocuous privileged identity/read operation; inspect the 0700 staging directory and result capture; verify the pull command targets QN90A and the S90D is unchanged | Root can write result.txt under the real SMACK policy; serial-scoped pull obtains the correct result. Temporary token/result files are removed without broadening permissions | Stop on capture failure; reconcile staging through the journal, restore baseline, and verify both targets |
| Snapshot → apply → rollback — #12 | Reviewed small reversible change with known prior value; no pending run | Capture a privileged snapshot, apply once, verify readback, then roll back through the same engine; repeat recovery after an intentional interruption at an agreed boundary | Journal remains recoverable; rollback restores the exact captured state and clears only owned staging. Pairing/preferences and other apps remain intact | Resume/rollback the existing run with its original checkout; use independent rescue if transport is lost |
| Failure evidence and preferences — #12 | Private output directory, synthetic non-secret failure command and saved preference backup | Run a deliberate nonzero operation that prints a marker to stdout/stderr; inspect private session evidence and cleanup. Separately try missing and malformed native preference inputs in a controlled import trial | Failure output is retained privately, no hex token/downloaded-result remains, and no failure is reported as success. Missing vs format failures are logged distinctly; invalid native import is refused as a whole | Remove only journal-owned staging; restore captured preference files and WebView storage; keep private failure evidence |

## S90D owner-run checks

Use the enrolled S90D firmware profile and its .NET 6 bridge/fallback. Never apply
QN90A offsets, hook enrollment or writable-file assumptions to S90D. All rows also
require the common baseline.

| Check / PR | Preconditions | Steps | Expected result | Rollback |
| --- | --- | --- | --- | --- |
| Loaded cold boot greeting — #10 | Independent rescue armed, retained managed fallback, agreed bounded load | Cold boot normally and under bounded startup load; record the real worker greeting and acquisition timing on S90D | Same 10 s wire deadline and bounded failure semantics as QN90A, independently measured on the S90D runtime; no hang or unrecoverable retry exhaustion | Stop load; restore captured package/selection and Developer Mode host; verify SDK/root access |
| Native normal/background boot, standby and app return — #11 | **Blocked:** no supported S90D native-hub/WebView installation or enrolled hook exists in this release | Do not install the QN90A backend. Verify setup refuses unsupported S90D native selection and that existing signed-web boot, wake and app return remain unchanged | Explicit unsupported result for native selection; no claim of S90D graphical acceptance. A future port needs its own reviewed dispatch and the QN90A scenario matrix repeated on S90D | Keep/restore existing signed-web setup and captured boot helper; never copy QN90A recovery artifacts |
| Home/rearm posix_spawn and WebView CLOEXEC — #11 | **Blocked** for native graphical paths until a separately accepted S90D port | Record the unsupported scope; exercise existing signed-web Home as a regression baseline, without deploying native graphics | Existing S90D Home/web behavior is unchanged; native helper/descriptor acceptance remains open, not inferred from host tests or QN90A | Restore the S90D web/helper baseline and confirm stock Home |
| Root result capture and serial scoping — #12 | Both TVs connected to SDB; explicit S90D serial; S90D package and SDK SMACK labels recorded | Run a benign privileged identity/read command, inspect 0700 staging/result capture and the serial-scoped pull; verify QN90A is untouched | Root writes and the SDK pulls the intended S90D result under real SMACK policy; no permission relaxation or cross-device result | Reconcile journal-owned staging, restore baseline and verify both targets |
| Snapshot → apply → rollback — #12 | Reviewed reversible S90D change, captured before state and no pending run | Snapshot, apply once, verify, then roll back; interrupt once at an agreed journal boundary and recover using that run | Exact captured state restored; no lost pairing, preferences or recovery guard. A failed snapshot blocks mutation cleanly | Use the original checkout and pending journal; if needed restore SDK admission physically, then finish rollback |
| Nonzero failure evidence — #12 | Private evidence directory and synthetic non-secret failure command | Print distinct stdout/stderr markers, exit nonzero, inspect the saved session evidence and local/remote cleanup | Nonzero status and output survive; downloaded-result/token and build staging are cleaned, with no replay or accidental QN90A pull | Preserve private evidence, reconcile owned staging and restore the S90D baseline |

## Owner decisions currently expressed by defaults

The owner has selected these policies. They do not authorize deployment:

- **TV Plus allowlists:** pure native, WebView and the signed web Hub permit the
  explicit TV Plus consumer exception. The pure-native change needs acceptance
  on hardware before deployment; `platform_consumer` itself is unchanged.
- **Normal-mode native boot:** pure-native installation remains background-only.
  Its shared core can handle normal-mode handoff, but the public dispatch and
  watchdog require the background marker. WebView retains its separate normal-mode
  dispatch. Do not describe the pure-native installer as enabling normal mode.
- **Invalid native favorites import:** WebView rejects the entire malformed file
  (`skipped=format`); a missing file logs `skipped=missing`. The source file and
  existing preferences are retained. This differs intentionally from the web
  model's per-entry filtering; no salvage or migration UI is planned.
- **Signing trust:** `scripts/sign.py` continues to require a loadable private
  site.json and independently enrolled trust. Omitting `--site` selects
  `TV_SETUP_SITE` or the standard location; an SDK certificate profile alone is
  insufficient.

---

# Historical combined release candidate — 2026-10-19

Status: locally validated experimental source candidate on `codex/release-candidate`. Combines
public main `83906b4`, release preparation `4a2325a`, and native worker/restart work
`85ba4ab` in merge `0ae6a29`. No push, signing, TV/NAS contact or deployment is part
of this reconciliation. Prior branch test/device results below are historical;
they do not validate this combined source state.

## Supported scope and limits

- Existing signed web Hub and experimental QN90A native launchers remain intact.
- QN90A basic native telemetry uses the existing managed settings adapter and
  setup journals. Continuous QN90A inspection is retired. S90D keeps its existing
  collector/inspector. The new QN90A telemetry/install transaction is locally
  tested; its hardware acceptance remains separate.
- Experimental native root worker includes bounded operations, saved-job
  preservation, managed return, interrupted-transition recovery and SDK rescue.
  Keep the small .NET entry bridge, firmware runtime, packaged managed fallback
  and captured rollback packages. New preparations remain disabled and managed
  by default; this merge does not promote native selection.
- Earlier native-selected 0.7.52 trials passed bounded operations/recovery on
  both models. QN90A passed maintenance restart; S90D passed the corrected wait
  for the old WRT host to exit (about 115 seconds). The combined candidate is not
  deployed. Clean boot, standby/power interruption, unattended restart reliability
  and a complete 24-hour endurance run on the current version remain open.

## Reconciliation and simplicity tracker

- [x] Merge both branches, retaining timing/authentication assertions in the one
  test conflict and both changes to transport/runtime guards.
- [x] Preserve the existing setup engine, durable receipts, identity/hash checks,
  no-replay behavior, managed return and independent rescue. No new coordinator,
  supervisor, installer or configuration framework.
- [x] Limit ordinary worker source snapshots to required inputs; benchmark,
  observation and acceptance controllers remain research/test tooling.
- [x] Remove `--native-entry-probe` from normal package preparation. Keep its
  builder, source and evidence for explicitly scoped research and keep immutable
  historical recovery packages. Native-only entry and fallback removal are deferred.
- [x] Reconcile current README, changelog and scope; mark old migration/parity
  instructions historical instead of maintaining competing active plans.
- [x] Run native worker protocol/fault tests in the existing Linux native CI job,
  reusing its compiler image. Keep the SDK-free and managed jobs separate; no new
  test framework or job matrix. The disposable native test needs ptrace for its
  guardian; it has no network or device credentials.
- [x] Run combined local setup, JavaScript, managed/native and recovery checks;
  record actual passes/skips and reproducible-build results below.
- [x] Check final diff, documentation links, workflow syntax and publishable-tree
  privacy; preserve the original branch tips and private recovery inputs.

## Local validation of the combined candidate

Validated on 2026-10-19 with Python 3.14 and Node 22.23.3 on macOS, plus
disposable network-isolated Linux containers. Logs and the non-Markdown input hash
map are ignored under `test-results/release-candidate/`. The source/configuration
digest is `4f3ffde81345a01f673de8194ba6618f5098881478fde4b308554f13ecbe4ce3`.

| Boundary | Local result |
| --- | --- |
| Setup/recovery Python suite | 668 discovered: 443 passed, 225 platform/integration skips; .NET blocked and unused, private toolkit/state absent |
| JavaScript/browser on Node 22 | 612 discovered: 434 passed, 178 Linux/integration skips; .NET blocked and unused |
| Linux worker, parity, files, retained records, pidfd and restart script | 89 passed; worker built with ASAN/UBSAN and fault controls |
| Linux acquisition, SDK rescue and cross-boot/startup recovery | 35 passed |
| Real-process restart and managed/native/managed rehearsal | 37 restart cases and six rehearsal cases passed; zero skips |
| New CI native-worker command | 49 passed, one mount-dependent storage case skipped; that case passed in the separate mount-capable worker run |
| Receiver / collector | 22 receiver tests and 16 native collector tests passed |
| WebView | 61 Python tests passed, two Linux-only skips; shim and diagnostic JavaScript checks passed |
| Managed compatibility | Settings adapter, inspector scope, 18 boot-relay scenarios and root-worker harness passed |
| Reproducibility | All 42 declared managed assemblies and unsigned web package matched across source paths; ARM launcher embedding matched for both models |
| Native and bridge builds | Six ordinary native components per model built twice and matched; setup/service entry bundles also matched twice for both models (6 KiB setup / 7 KiB service bridge) |
| Review checks | Workflow syntax, restart ShellCheck, changed-document relative links and whitespace checks passed |

The initial Python run overlapped a source edit and hit the recovery source guard;
the unchanged-source rerun and all 19 focused S90D recovery tests passed. The first
native CI trial lacked ptrace permission; the corrected disposable-container
command passed without changing runtime guards. Existing SQLite ResourceWarnings
remain; neither was hidden by relaxing a recovery check.

The tracked-tree privacy audit found no matches in 789 inspected text files.
Gitleaks on the source-only snapshot reported ten generic-key matches: manual
review found only 64-character SHA-256 file hashes (including the two existing
passwd-file hashes and eight source/API-file hashes). No credential was identified.
These are limited scanner/review results. Ignored binaries, logs and generated
keys are outside the proposed source commit. Historical research and immutable
private recovery inputs were not removed or rewritten.

Local validation does not establish TV-library compatibility or hardware lifecycle
acceptance. The exact combined candidate has not run in hosted CI or on either TV.

## Before merging or publishing

Review the final combined diff and obtain hosted CI on the exact proposed commit.
Keep experimental labeling and outstanding hardware limits in the release notes.
Hardware acceptance requires a separately authorized session using the existing
[telemetry guide](../guides/native-telemetry.md),
[agent recovery procedure](../lab/autonomous-root/README.md) and
[hardware checklist](../guides/hardware-acceptance.md). Do not rebuild or delete
artifacts referenced by existing recovery journals. Full .NET removal, new boot
architectures and S90D native telemetry/graphical ports are outside this release.

---

# Earlier release-prep review — 2026-10-19

Scope: an **experimental source merge**, not stable hardware acceptance. The
release branch preserves the locally tested installer/telemetry/recovery work in
checkpoint `28c0054` and incorporates public main `83906b4`, including its WebView
launcher and root-agent transfer/native-launcher work. Nothing is pushed or
installed as part of this review. Keep the original checkout for existing recovery
runs: their source guards deliberately reject a different revision.

## Findings tracker

- [x] Reconcile current public main without dropping its third launcher, managed
  root projects, binary transport or worker-readiness checks.
- [x] Run the root-worker managed harness explicitly in the managed CI job;
  SDK-free discovery no longer invokes it. Keep the existing Linux worker job.
- [x] Add the collector's host build/tests to the existing Linux native job;
  no new CI framework, vendor libraries or deployment steps.
- [x] Fix Node 22 TLS test reuse: generate a localhost certificate and use normal
  hostname verification. A per-request verification override isolated sockets on
  Node 22. Preserve authentication, replay and connection-limit assertions.
- [x] Clarify QN90A basic telemetry versus S90D inspection, pure-C installer versus
  WebView tools, and preference retention. Historical release decisions below
  remain dated evidence, not current merge blockers.
- [x] Validate committed candidate `e16616d` in a clean checkout and scan the
  publishable tree/history. The follow-up commit records documentation only.

## Local validation evidence

Executable source/CI candidate: `e16616d`; the follow-up record changes Markdown
only. Logs are private, ignored files under `test-results/public-release/`.

- Python 3.14: 325 setup tests passed with a failing `dotnet` stub first on PATH.
  The stub was never invoked. The receiver passed 22 tests.
- Node 22.23.3: all 118 tests passed, including the corrected mutual-TLS/replay
  test. Both separate WebView JavaScript checks passed.
- WebView Python tests: 63 discovered, 61 passed, two Linux-only cases skipped on
  macOS. The separate Linux root-worker harness passed its process-group
  cancellation, timeout, reboot-interruption, transfer and protocol checks.
- Managed checks: settings adapter, QN90A inspector exclusion/S90D cadence,
  18 relay scenarios and explicit root-worker harness passed. Source-built ARM
  launcher embedding reproduced for QN90A and S90D.
- Native collector: host build and all 16 tests passed in network-isolated Linux
  containers. This exercises the host collector, not TV library compatibility.
- All 42 declared managed assemblies and unsigned web packaging reproduced across
  source paths. `actionlint`, changed-document links and `git diff --check` passed.
- A source-only clone of the committed branch passed fresh `npm ci`, Node 22,
  receiver, WebView and web reproducibility checks with private toolkit/state
  absent. The explicit managed worker harness also passed there. Python 3.12
  setup validation passed all 325 tests in a new virtual environment with pinned
  requirements and .NET blocked. Its first attempt without those requirements
  failed on missing `lxml`; the correctly provisioned rerun passed.

The tracked-tree privacy heuristic found no matches in 491 source files. The
source archive excludes ignored/private files. Gitleaks 8.30.1 found the same two
existing passwd-related SHA-256 file hashes in both source and reachable history;
manual review confirmed hashes, not credentials. The scoped history heuristic
found two room-label fixture strings already reachable from public main and only
public GitHub/noreply author addresses. No history was rewritten. These are
limited scanner/manual-review results, not a guarantee that every disclosure risk
has been detected. No new sensitive artifact or identity was found.

## Device validation boundary

Read-only checks on both enrolled TVs matched physical identity, exact firmware,
architecture, managed runtime/host hashes and the protected root launcher hash.
Both pinned agents were connected and ready; signed Hub and telemetry package
paths were present. Both had the managed `enabled` marker, no `native-enabled`
marker, and no loaded native telemetry unit. No setup journals were pending.
Raw identities, credentials and command evidence remain in private storage.

These observations validate the existing baseline and transport compatibility.
They do **not** validate this candidate's native installation, opt-in/out, reboot
startup or rollback on hardware. No TV/NAS deployment, restart, power transition
or telemetry handoff was performed. S90D retains its managed collection and
inspector path; a native S90D telemetry rewrite is outside this candidate.

Before merging, review this branch's final diff and obtain a passing hosted CI
run on the exact proposed commit. Hosted CI is still pending; this local review
performs no push. Keep the experimental label and hardware limits in the release
notes. Before calling the native integration hardware-accepted, complete the
existing [native telemetry checks](../guides/native-telemetry.md) and
[hardware acceptance procedure](../guides/hardware-acceptance.md) with separately
authorized install/recovery/reboot trials. The later combined candidate includes the separately developed native root
worker. Settings, boot and S90D telemetry rewrites remain deferred.

# Historical publication scope — 2026-10-11

Couchroot is published as experimental source with 0BSD licensing for original
work and retained upstream notices. The owner authorized a fresh source snapshot,
not the old development history. See [publication review](publication-review.md),
[licensing](licensing.md) and [Security](../../.github/SECURITY.md). Historical licensing
and publication decisions below are superseded; incomplete hardware acceptance
and portability work remain limitations, not completed tests.

# Public release readiness — 2026-09-20

Historical status (2026-09-20): **not ready for a stable release**. Work starts from main `7af6886`. No TV/NAS
mutation, live reboot, push, release publication or history rewriting was used
for this preparation. Historical hardware observations remain separate from the
new orchestration's automated tests.

**2026-09-21 update:** the [shared telemetry rollout](../guides/telemetry.md#service-unification-validation--2026-09-21)
subsequently validated Hub/service deployment and automatic startup after full
reboots on both TVs, plus recovery from an initial failed S90D install. The
remaining full-setup/recovery acceptance matrix is still open. The preparation
record below describes the earlier 2026-09-20 state.

## Implemented

- Removed personal addresses, local user paths, room names and historical boot
  UUIDs from current source, examples, fixtures and evidence. Historical scripts
  now contain documentation addresses and are outside the public setup path.
- Split exact model/firmware safety profiles from site addresses, physical TV
  UUIDs, SSH configuration, NAS endpoints and per-user signing trust. There is
  no default personal destination, embedded signer identity or implicit first-run
  telemetry opt-in. Model and protected-package guards remain mandatory.
- Replaced the CLI's untracked S90D dump-collector dependency and private Python
  imports with checked-in wrappers and a source-built bounded namespace runner.
  Both models retain separate namespace selection and resource guards. Temporary
  keys are generated locally; private keys are never pushed to the TV.
- Fixed the toolkit requirements path, pinned lxml and the build SDK, added offline
  dependency checks, deterministic native/path-independent builds and a build
  manifest. Removed implicit searches through historical private artifact trees.
- Bound journals to physical destination/site/trust, moved source checks before
  reconciliation side effects, blocked applying a run after rollback starts,
  preserved later edits and retained newly installed apps for manual review.
  Missing managed-app reinstall packages no longer prevent other configuration
  from being restored. Added per-file NAS checks and temporary-file protections.
- Hardened archive verification against symlink/noncanonical entries and DTDs;
  redacted preference extensions and unexpected tool exceptions from console/JSON.
- Added offline CI, failure-injection/identity fixtures, installation/support
  matrix, recovery/security guidance, development version and changelog.
- Added schema 2 recovery for saved choices and the ownership ledger: mutations
  stay pending until both local records are durable; resume can finish locally
  without contacting the TV. Rollback restores earlier local records and refuses
  later edits. Old journals require their original checkout.
- Added interrupted inverse reloads and digest-checked run-specific staging
  recovery. Unknown/partial staging bytes and symlinks remain for inspection.
- Supervised reboot observations share one remaining host deadline, including
  nested SDK/root/NAS tools. Timeout stops observation processes and records
  unverified startup/uncertain diagnostic cleanup; no launch or reboot retry is
  introduced. Snapshot/request transport budgets precede the observation budget.

## Privacy audit (redacted findings)

The audit inspected tracked working-tree files, all 37 reachable commits available
at task start, 385 unique reachable file blobs, and author/committer metadata.
The tree included source, documentation, fixtures, inventory and two PNG icons.
The history heuristic found 99 file versions containing personal addresses, three
containing personal filesystem paths, and 49 containing UUIDs (historical boot
identifiers and fixtures). Author/committer metadata contains one personal name
and email identity. Signing-profile names and public certificate fingerprints in
the old profiles also identify the original installation; they are not private
keys. The private remote URL is local Git configuration, not source content.

No private-key blocks, obvious long credential literals, tracked signing
containers, database archives, MAC literals or DUID/serial literals were detected
by these checks. This is a **limited negative result**, not secret-scanner or
manual-disclosure certification. Boot timelines, exact firmware hashes, app
inventory, screenshots/artwork and exploit details still need owner disclosure
review. No credential rotation is prescribed without evidence of exposure.

Current examples/evidence use synthetic identities; they must not be mistaken for
raw hardware captures. The latest-tree heuristic scan is clean. Old values remain
in Git history and author metadata. **Owner decision required:** authorize a
separately reviewed history sanitization or a clean public source export, and
choose public author metadata. Neither action was performed. Audit tooling prints
only paths/categories/counts, never matched values:

```sh
python3 scripts/privacy-audit.py --check
python3 scripts/privacy-audit.py --history
```

Reachable refs are the audit boundary; unknown remote refs, server backups,
reflogs/dangling objects and earlier copies are not certified. Historical findings
make `--history --check` fail by design. Do not upload raw audit inputs or journals.

## Validation and reproducibility

Local macOS validation uses Python 3.14, the SDK pinned by global.json, OpenSSL and
Chromium. The Python suite, telemetry suite, Node suite and native relay harness
run without device access: **128 Python tests, 14 telemetry tests, 51 Node tests,
and 12 native relay scenarios passed**. All **36 manifested native assemblies**
built successfully. A separate source snapshot in a new directory and
fresh virtual environment passed with toolkit/state paths pointing to empty
locations. Its native manifest matched across source paths after removing Git
informational-version leakage and normalizing temporary compilation paths.

A disposable source-only Linux amd64 container (Ubuntu 24.04, Python 3.12,
`mcr.microsoft.com/dotnet/sdk:10.0.301-noble`) also passed all 128 Python tests,
14 telemetry tests, 12 relay scenarios, all 36 native assembly builds and unsigned
Hub packaging. No private toolkit or historical deployment files were mounted.
All 36 Linux/macOS native hashes and the unsigned Hub package matched exactly.
The Node/Chromium suite was rerun on macOS; Linux browser validation remains in
the unexecuted hosted matrix.

Emscripten 3.1.64 in its upstream container produced identical QN90A saver output
across two source paths. `shaders.js` matches its reviewed digest; **`core.js` does
not**. Reproducibility is established for this compiler output, not equivalence to
the historical binary or hardware acceptance. No profile pins were changed.
`scripts/check-web-reproducible.py` writes hashes and these separate comparisons
to `dist/saver-reproducibility.json`; CI now runs this check. The current core
output must be reviewed and tested before becoming a verified release artifact.

The repeatable check is `python3 scripts/check-reproducible.py`; it compares all
manifested DLLs (including generated model-specific runners and ten QN90A cleanup
variants) and the unsigned Hub package from two paths. It does not certify signed
package reproducibility or S90D vendor-linked renderer bytes.

The checks can also run independently. Web packaging and the Python/Node test
suites do not require .NET. The four managed harness scripts must be run
explicitly; importing them during Python discovery does not execute their tests.

```sh
python3 scripts/check-dependencies.py --component offline
python3 scripts/check-dependencies.py --component web
python3 -m unittest discover -s tests -p '*_test.py'
python3 -m unittest discover -s telemetry/s90d/tests
npm ci
npx playwright install chromium
npm test
python3 scripts/check-reproducible.py --component web

python3 scripts/check-dependencies.py --component managed
python3 tests/telemetry_service_test.py
python3 tests/inspector_collector_test.py
python3 tests/qn90a_boot_relay_test.py
python3 tests/root_agent_worker_test.py
python3 scripts/check-reproducible.py --component managed
```

`check-dependencies.py` still defaults to `--component setup`, which requires the
pinned SDK for full setup. `--component prepare` checks Python/platform only;
native source compilation and preference conversion additionally need Docker
and Node respectively. These checks do not validate device enrollment.

CI has seven job definitions (ten checks after expanding the Linux matrix):

- `web-and-offline`: Node 22/24 × Python 3.12/3.14 on Ubuntu 24.04. Dependency,
  privacy, setup/recovery, telemetry receiver, WebView and Node/Chromium tests,
  plus unsigned web reproducibility. `dotnet` calls are blocked in this job.
- `managed`: three retained C# adapter/relay harnesses and managed cross-path builds with the pinned SDK.
- `root-native-launcher`: ARM launcher builds, native collector checks, native
  protocol/fault/recovery and slow-I/O tests.
- `native-launcher-builds`: both ARM graphical launchers and native Hub host tests.
- `arm64-parity`: real native workers, process observer and storage cases
>
  protocol/fault/recovery and slow-I/O tests, plus the managed launcher harness.
- `native-launcher-builds`: WebView ARM host/sampler builds with GLIBC and startup libpthread gates.
- `arm64-parity`: real managed/native workers, process observer and storage cases
  in disposable ARM64 containers on `ubuntu-24.04-arm`. Tmpfs tests run with the
  explicit mount capability; a preflight checks the container policy. Native restart-fault and bootstrap suites each get a fresh container with a reaping init.
- `qn90a-web-saver`: pinned Emscripten reproducibility checks.
- `macos-setup`: macOS 14 ARM64/Python 3.12 setup, installer and UI-deploy tests,
  including the zombie-group `EPERM` deadline regression.

All Actions have full commit pins and exact version comments; CI-pulled container
bases/images have digest pins. Weekly Dependabot covers Actions, npm, tvsetup pip
requirements and Dockerfiles. It does not update image references embedded in
`validate.yml`; those need manual review. Docker major upgrades, the test image's
Python minor and the collector Bullseye base require deliberate review. A collector
base change requires byte-identity evidence.

Pull requests, pushes to `main` and manual dispatch run the suite. Superseded runs
are cancelled. The focused macOS job supplements the Linux version matrix; neither
CI nor a successful local build qualifies TV firmware, SMACK, boot or standby.
See the [parity coverage and remaining opt-ins](../../tests/worker-parity/README.md#ci-coverage).

Build manifests include only declared outputs, excluding stale DLLs from other
research builds. Reports are `dist/reproducibility-web.json` and
`dist/reproducibility-managed.json`; the default combined command retains
`dist/reproducibility.json`. No secrets or vendor libraries are supplied, and no
workflow signs, deploys or publishes. The S90D GLES-linked renderer is excluded
from public CI pending a reviewed vendor-library arrangement and reproducible
compiler/sysroot recipe.

## Prioritized blockers and owner acceptance

1. **P0 — Disclosure and licensing decisions.** Choose project license and confirm
   provenance/rights for original code, icons, shaders, mesh data and any third-party
   material. Approve the public scope of the privilege-chain details. Decide how
   historical identifiers and commit author identity will be handled; changing the
   current files alone is insufficient. Establish/test a private security-reporting
   contact and maintenance policy. See docs/project/licensing.md and .github/SECURITY.md.
2. **P0 — Physical apply/recovery proof on both exact TVs.** The new CLI and rebuilt
   root runner need owner-authorized tests from known recoverable states: baseline
   root invocation is read-only, privileged invocation runs once, resource hashes
   and labels remain intact, cleanup succeeds, ordinary apply is correct, second
   apply is a no-op, and interruption before/during/after each mutation reconciles
   without duplication. Exercise unreachable TV, timeout, host process death,
   corrupt/missing backup, full state disk, concurrent changes and rollback restart.
   Test recovery after a complete mutation but before saved choices/ledger writes.
   Local locks only coordinate one management host; independent-host mutation is
   unsupported. Do not conduct destructive interruption tests without recovery media.
3. **P0 — Signed installation and application recovery.** Prove independently
   enrolled author/distributor pins, device authorization, first install, forward
   updates, certificate renewal and signed forward recovery on each TV. Verify
   that in-place updates preserve newly edited app data. Confirm retained new apps
   and removed optional apps are accurately reported for manual recovery. App
   Store reinstall is an owner acceptance step, not a file-copy rollback guarantee.
4. **P1 — Fresh NAS provisioning and shared recovery.** The adapter still requires
   an existing TrueNAS app and two-device registry. Supply a reviewed provisioning
   path and isolated credentials/certificate enrollment for a genuinely new NAS.
   Physically test receiver/dashboard restart and partial-batch restore while the
   other TV continues ingesting; confirm chart history, volume ownership, registry,
   credentials and custom endpoints remain intact. Do not replay historical compose.
5. **P1 — Native artifact/toolchain portability.** Run the hosted CI matrix.
   Review why the reproducible Emscripten 3.1.64 core differs from the previously
   reviewed digest and verify generated saver bytes on QN90A. Establish a clean S90D
   ARM compiler/sysroot recipe that reproduces the reviewed renderer digest with
   user-provided GLES libraries. Review supported hosts, old TV runtime maintenance,
   dependency licenses/notices and exact dependency provenance before bundling.
6. **P1 — End-to-end hardware experience.** After explicit owner-authorized full
   reboot, observe a new boot ID and autonomous startup without launching Hub.
   Test Home and both QN90A AirPlay returns, five-minute Hub saver, S90D splash/
   screensaver, streaming, standby/wake and Samsung Home fallback. Verify reboot
   observation deadlines under slow/disconnected transport and confirm TV-side
   diagnostic cleanup after forced host cancellation. Host nested-process deadline
   coverage now passes; it does not prove remote cleanup. Record configuration and runtime
   acceptance separately, with redacted evidence.

## Release checklist

Use the [staged hardware acceptance procedure](../guides/hardware-acceptance.md) to prepare
specific owner-authorized tests. None of its mutation steps were executed here.

Resolve every P0 before a public candidate; either resolve P1 items or explicitly
reduce and label supported scope. Re-run audits against the exact publication
commit/export, run hosted CI, review the diff, record model/firmware hardware
acceptance, freeze dependency/build manifests, review third-party notices, and
inspect the proposed archive. It must exclude site/trust, logs, journals, tokens,
certificates/keys, signed packages, raw evidence, extracted resources and vendor
binaries. Confirm version/changelog, security-report route and recovery guide.
Only then request explicit owner authorization to push or publish. Nothing here
constitutes that authorization.

## Native worker upgrade acceptance

The [native upgrade workflow](../guides/native-worker-upgrades.md) separates package installation from worker activation. Local tests cover handoff and interrupted recovery; both TV models still need owner-approved upgrade, return-to-previous, job, Hub/telemetry and reboot acceptance. Resolve any unexplained preservation-inventory drift before live recovery.
