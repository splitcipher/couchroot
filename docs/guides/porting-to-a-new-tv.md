# Porting Couchroot to a new TV or firmware

Couchroot ships with reviewed profiles for exactly two sets (the owner's
[QN90A and S90D](device-compatibility.md)). A profile is the per-device safety
contract the setup engine enforces: the exact model, firmware, runtime and file
hashes it will accept before it touches a TV. Every other Samsung model, region
and firmware version is unverified, so a new target needs its own profile built
from first-hand inspection of **your own** TV.

This guide is a high-level map of that work. It does not hand you a finished
profile, and it cannot: the hashes and identifiers in a profile are specific to
one firmware build, and inventing them defeats the guards that stop the engine
from running against a TV it does not understand. Expect this to be a research
project, not a config edit.

> **Own the hardware.** Only do this on a TV you own or administer. Developer
> Mode, SDB and the root chain are a powerful management path; keep the TV and
> your host on a trusted network. Nothing here is Samsung-supported, and a wrong
> profile can leave a TV needing recovery with the physical remote. Read
> [SECURITY](../../.github/SECURITY.md) and
> [owner-supervised hardware acceptance](hardware-acceptance.md) first.

## What a profile is

Each profile is one JSON file under `tvsetup/profiles/<id>.json`, loaded by
[`tvsetup/config.py`](../../tvsetup/config.py). Compare the two shipped files
side by side to see the full shape; the fields fall into these groups.

| Group | Fields | Where it comes from |
| --- | --- | --- |
| Identity | `name`, `model`, `platform`, `firmware`, `architecture` | The TV's read-only public API and `/etc/prd_info.ini` |
| Runtime pins | `framework`, `runtime`, `host_sha256`, `launcher_sha256` | The on-device .NET runtime and signed host binaries |
| Layout | `startup`, `chart_prefix`, `snapshot`, `dashboard_config_path` | How this model boots and where it stores state |
| Optional-app cleanup | `cleanup`, `reasons` | Your own inventory of removable apps and why each is listed |
| Build contract | `source_hashes`, `boot_artifacts`, `service_artifacts`, `helper_sha256`, `collector_sha256`, `saver_generated` | Reproducible builds of the components this model uses |
| Capability record | `capabilities` | Evidence summarized from the setup, installer, compatibility and per-device guides |

Two things make these values trustworthy rather than copied guesses:

- **The identity guard.** Before any privileged step, the engine checks the
  firmware string in `/etc/prd_info.ini` and `uname -m` against the profile (see
  `identity_guard` in [`tvsetup/transport.py`](../../tvsetup/transport.py)). Where
  .NET still runs, it also pins the runtime directory and the SHA-256 of the
  signed host binaries. A profile whose firmware or hashes do not match the TV in
  front of it simply refuses to proceed.
- **Immutable safety fields.** Your private `site.json` only carries addresses
  and trust material; it cannot override a profile
  ([`tvsetup/site.py`](../../tvsetup/site.py)). The safety contract lives in
  version control, not in local config.

## The honest prerequisite: code and evidence, not just JSON

The supported device list is built from the validated profile registry under
`tvsetup/profiles/`. A profile must pass the registry schema, including its
capability values; it cannot be added to private `site.json` or supplied as an
unverified skeleton. The registry removes duplicated device-name lists, but it
does not make every registered profile compatible with every command. Launcher,
startup, telemetry and transport paths can retain explicit model-specific
requirements.

The shipped profiles remain the only accepted devices. To propose another
model, first collect the read-only inventory and report exact model and firmware
evidence. The `survey` command can compare its public model/platform fields with
the registry before you install the toolkit. A same-platform-family result is
only a lead for research: the rule compares the first two underscore-delimited
platform tokens, and does not grant support. Exact model and full platform
matching still does not establish firmware support.

Add a new profile only with a reviewed capability record, original resource and
runtime hashes, model-specific transport evidence and a documented recovery
path. Keep firmware, architecture, runtime, hash, signature, package-protection
and cleanup allowlist checks strict. The registry changes which profile names
the tools can recognize; it does not weaken any safety guard or authorize an
untested model or firmware. See [CONTRIBUTING](../../.github/CONTRIBUTING.md).

## Step 1 — Inspect your TV read-only

Start without the toolkit or signing setup by running the public-API survey:

```sh
bin/couchroot-install survey TV_ADDRESS
bin/couchroot-install survey TV_ADDRESS --report /private/tv-report
bin/couchroot-install doctor --tv TV_ADDRESS
```

The survey reads model and platform once, and its report writes redacted JSON
and Markdown in a new private directory. It never contacts SDB. The optional
profile skeleton is marked `UNVERIFIED`, leaves unverified fields null and is
rejected by the profile registry. A family match is informational; it does not
grant support. `doctor --tv` checks the endpoint, Developer Mode and SDB port
reachability without using `site.json` or changing the TV. These checks can
help you decide whether to continue with a read-only inventory.

For deeper firmware and component details, use the toolkit under
[`tools/`](../../tools) and the recipes in
[tv-setup](tv-setup.md#install-from-source); the per-device notes under
[`docs/lab/devices/`](../lab/devices) show the format, and the sanitized
[`docs/lab/inventory/`](../lab/inventory) files show what a recorded result looks
like. At this stage you only read:

- The public device API for `model`, `platform`, firmware and the stable
  `device_id` your `site.json` will use.
- The existing public API fields `developerMode` and `developerIP`; report
  whether Developer Mode is enabled and whether a developer host is configured,
  but redact the TV's configured host address from shared reports. Survey and
  report output contain no IP addresses; interactive `doctor --tv` may show this
  computer's routed IPv4 so the owner can enter it in Developer Mode settings.
- `/etc/prd_info.ini` for the exact firmware string the guard will match.
- `uname -m` for `architecture`.
- The installed .NET runtime path and version, and the SHA-256 of the signed host
  binaries, for the runtime pins.
- The optional-app registrations you may later want in `cleanup` — record the
  package ids and your reason for each, mirroring the `reasons` block.

Capture this as JSON the way the existing inventories do, and keep raw dumps,
identifiers and journals out of Git.

## Step 2 — Decide what the model actually needs

Not every component applies to every TV. The `reasons` block in each profile
documents the choice per component (`hub`, `home`, `airplay`, `startup`,
`telemetry`, `splash`, `screensaver`, `cleanup`, `dashboard`). Work out, from
your inspection, which launch/boot path your model uses and whether it needs the
managed (.NET) helpers at all. [Choosing a launcher](choosing-a-launcher.md) and
the [native installation](native-installation.md) notes frame these choices;
the QN90A and S90D differ here, which is why their profiles differ.

## Step 3 — Produce reproducible build hashes

The `source_hashes`, `*_artifacts`, `helper_sha256`, `collector_sha256` and
`saver_generated` entries pin reproducible builds of the components your model
uses. Build them with the project's tooling and the reproducibility checks
(`scripts/check-reproducible.py`, `scripts/check-web-reproducible.py`) so the
numbers you record are the numbers the engine will later recompute. These must be
real outputs of your build, never hand-copied from another model.

## Step 4 — Dry-run offline, then on hardware under supervision

Validate without touching a TV first:

```sh
bin/couchroot-install plan --device <id> --launcher web
bin/couchroot-install doctor --device <id> --launcher web
```

Then move to hardware only under the
[owner-supervised acceptance](hardware-acceptance.md) procedure, inspecting each
proposal before applying and keeping the run id so an interrupted install can be
resumed or rolled back from the same checkout. Report local tests, read-only
observations and owner-authorized mutations separately — mocked state is not
hardware validation.

## Debugging a port — high level

When a model misbehaves, the useful loop is: reproduce it, capture it read-only,
narrow it to one layer, and only then change anything.

1. **Confirm the guard, not the feature, is the thing failing.** A refusal that
   mentions firmware, architecture or a hash mismatch means your profile does not
   match the TV — recheck `/etc/prd_info.ini`, `uname -m` and the binary hashes
   before touching anything else.
2. **Split UI from device.** Reproduce UI and navigation issues in the local
   workbench (`npm run dev`) with the simulated APIs; see
   [UI development](ui-development.md). If it only fails on the TV, the cause is
   in the device adapter or firmware behavior, not the shared UI.
3. **Watch the real boot/launch path.** Use the SDB connection recipes
   ([SDB connection reuse](sdb-connection-reliability.md)) to read systemd unit
   state, journal timestamps and the current foreground app id. The boot-inventory
   and startup-audit lab notes
   ([`docs/lab/devices/`](../lab/devices)) show the exact queries that turned
   "Hub didn't appear" into a named unit and timestamp.
4. **Diff against a known-good model.** The two shipped profiles and their lab
   notes are your reference for what "working" looks like; a new model's
   divergence from them is usually the bug.
5. **Keep it read-only until you understand it.** Capture, sanitize, hypothesize,
   and verify the hypothesis offline before proposing a privileged change.

The per-device READMEs and the performance, boot and startup notes under
[`docs/lab/`](../lab) are case studies of this loop on the QN90A and S90D.

## When you need to understand firmware behavior — decompilation

Some questions can only be answered by reading the firmware's own binaries: why a
model boots a particular app first, how its launch spinner is driven, what a
system service does on startup. The existing lab notes solved several of these
by **offline** static analysis of the exact binaries copied from the TV, and that
is the model to follow. A typical flow:

1. **Get the exact binary, read-only.** Copy the specific executable or library
   from your TV over SDB and record its SHA-256. Analysis is only meaningful
   against the build actually installed, so pin the hash the way the lab notes do.
2. **Work on a disposable copy, offline.** Treat the firmware blob as untrusted
   input: put it in its own directory, never run it, and never run an interpreter
   or build tool from inside that directory. All analysis is static.
3. **Disassemble / decompile.** The project's notes used Ghidra (ARM/Thumb, with
   an explicit load base) and REA for cross-checks; either is a reasonable
   choice. Resolve string literals independently from the ELF bytes rather than
   trusting imperfect decompiler output — the direct-boot and native-autostart
   notes are explicit that signatures and return types from a decompiler are
   approximate and must be confirmed at the instruction level.
4. **Confirm at instruction level.** Where a conclusion matters (a boot decision,
   a permission branch), check the actual instructions and record the addresses,
   as [direct-boot](../lab/devices/qn90a/direct-boot.md),
   [native-autostart](../lab/research/native-autostart.md) and
   [splash-acknowledgement](../lab/devices/s90d/splash-acknowledgement.md) do.
5. **Keep raw firmware and decompiler projects private.** The lab notes publish
   findings, addresses and sanitized reasoning only — raw Samsung binaries,
   decompiler exports and analysis projects stay out of Git. Follow the same rule
   for your own model.

Worked examples of this analysis, with the exact tools, load bases and
verification steps, are in the lab research notes:

- [Verified temporary root chain](../lab/research/exploit-chain.md)
- [Native startup and restart](../lab/research/native-autostart.md)
- [Tizen 6 startup survey](../lab/research/tizen6-survey.md)
- [QN90A: why Hub did not replace Live TV at cold boot](../lab/devices/qn90a/direct-boot.md)
- [S90D boot-splash acknowledgement](../lab/devices/s90d/splash-acknowledgement.md)

## Contributing a profile back

A new model is welcome as a contribution, on the same terms as any other: a
separate reviewed profile, original resource hashes, model-specific transport
evidence and a documented recovery path, with no weakening of the firmware,
signature or cleanup guards ([CONTRIBUTING](../../.github/CONTRIBUTING.md)).
Start from the generated redacted report or the
[device report issue template](../../.github/ISSUE_TEMPLATE/device-report.yml).
Mark every milestone as a read-only observation, owner-authorized change or not
tested. Submit only redacted, synthetic-identity reproduction steps. Because this is a
personal project, there is no support or response-time commitment — but a
well-evidenced new target is genuinely useful to other owners of that TV.

## Offline deeper runtime evidence

`tvsetup.deep_inspection.report(envelope)` parses already supplied evidence without
opening SDB, selecting a runtime, changing profiles or granting installation. The
public survey remains unchanged and does not use this parser. Supply a bounded
`listing` (at most 16 KiB), `listing_exit`, `source_revision` (40 hex characters),
`stage`, `outcome`, optional `explicit_choice`, `active_path`, a `files` map for
`libcoreclr.so` and `System.Private.CoreLib.dll`, and profile mismatch field names.
The returned schema-1 record separates detected versions from an explicit choice
and always leaves `selected_runtime` null and `install_authorized` false.

Standard runtime listing and the exact unknown-option/exit-255 fallback are
separate evidence paths. Alternate known CLR layouts are observations only.
Malformed paths, missing libraries, unknown families, choice mismatches and
unavailable captures produce reasons, not relaxed firmware/hash/signature guards.
Raw output, credentials, arbitrary paths and private mismatch values are omitted.
Record control timeout, fast rejection, callback failure and cleanup uncertainty
at their actual stages. Root success, display control, boot persistence and
security-policy capabilities remain independent milestones.

The diagnostic pattern was compared with upstream
[samsung-tv-root v0.0.12](https://github.com/chris-ritsen/samsung-tv-root/tree/3b97edf3762db7670585d73e29623dc56195bf98).
This is original parsing code, not an upstream dependency refresh. Couchroot's
pinned production transport calls `capture()`, not the upstream retried
`require_shell_injection()` method. Its frozen Linux OpenSSL environment workaround
has no demonstrated use in this source-toolkit path. Neither change is imported.

A later live collector needs separately authorized access, exact target identity,
fixed commands, bounded total elapsed time, provenance and staging cleanup with
lost-response reconciliation. `archive-root probe` acquires and cleans up; it is
not a read-only public survey. Parser removal requires no TV rollback.
