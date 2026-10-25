# MQTT feature 2: measured state and remaining qualification gates

This increment is **offline-tested source, not TV acceptance**. Feature 1's S90D
deployment uses `a4e942d` plus its bounded candidate-provenance correction. The
owner reported HA discovery/commands, HA birth and broker-outage checks passed
on 2026-10-24; the TV reboot remains pending separate authorization. Keep that
deployed build separate from this feature-2 branch. Do not proceed
to feature 3 controls on the strength of simulated state or a successful install.

## Implemented read path

The existing coordinator lease admits state collection only after the worker has
read valid private MQTT configuration with `state:true`. No config means no state
API reads. `state:false` leaves Firmware/Uptime/Root OK and the new Agent uptime
diagnostic available and disables the state sampling. Existing telemetry stays enabled.

`health.agent_uptime_s` measures whole elapsed seconds since the native worker
process started, using its already-verified kernel start ticks and
`CLOCK_BOOTTIME`. It is not coordinator or MQTT-thread uptime, nor CPU time.
It survives MQTT reconnect/birth/lease renewal and includes suspend time; a new
worker starts near zero. Invalid identity/clock data is `null`. The diagnostic
sensor **Agent uptime** uses unique ID `tv_<id>_agent_uptime`, making 27 entities
in this build. Existing **Uptime**, its `tv_<id>_uptime` ID and `uptime_s` boot-time
value are unchanged. A coordinator-only restart that preserves the worker will
not reset Agent uptime; compare the coordinator process identity separately.

The worker samples aggregate `/proc/stat` and `/proc/meminfo` every two seconds.
CPU uses deltas of the first eight counters, excludes guest double counting, and
counts idle plus iowait as idle. A first sample, reset, invalid read, non-increasing
time or gap over 45 seconds produces `null`; another valid pair recovers. Memory
is `(MemTotal - MemAvailable) / MemTotal`, not a sum of process RSS. An initially
absent/unreadable adapter remains unsupported; a previously readable adapter's
transient failure produces `null`. Health publishes every 60 seconds, on connect
and on HA birth. State changes do not increase its routine publication rate.

Foreground identity reuses `memory/appfw/current_fullscreen_appid`, the key read
by the existing telemetry collector and QN90A boot relay. A fixed, read-only mode
of the same executable reads it in a short-lived child, with an 800 ms parent
budget, no shell or caller-supplied key, closed inherited descriptors, empty
environment, parent-death kill and bounded output. It remains under the existing
worker guardian. Missing vconf is unsupported; timeout/invalid output clears the
identity and never blocks root administration indefinitely. This is a fullscreen
app observation, not identification of a transient overlay or a playback session.

The coordinator resolves that exact ID through `tizen.application.getAppInfo` and
reads absolute `tizen.tvaudiocontrol.getVolume()` / `isMute()`. The native worker
accepts only a fixed bounded projection over its existing authenticated lease.
It matches the returned app name against its latest foreground ID before using it.
No public HTTPS or MQTT operation can inject this observation envelope. Optional
file/socket allocation uses the existing descriptor admission lock and preserves
headroom for protocol/monitor work; pressure yields unavailable readings. Package
privileges add application information and TV audio access; the adapter has no
setter, launcher or key-emulation path. Missing/denied/unsupported APIs never
establish support. A replacement worker must admit observation again. Synchronous
platform getters still need hardware latency acceptance; a blocked coordinator
loses its native lease and must be recovered through the existing SDK path. Temporary failures clear values, and observations expire after
six seconds without renewal. Fresh collection follows a reconnect. A suspended
coordinator still loses its entire MQTT lease after ten seconds.

App/source inventories refresh at most every 30 seconds through `getAppsInfo` and
`systeminfo` VIDEOSOURCE. App eligibility matches the Hub's store/native-app rules;
Hub, Samsung Home and internal services are not select choices. Complete results
replace previous inventories, including an empty result after removal. Failures
retain the last complete inventory. At most one pending callback per API can exist;
750 ms deadlines and cancellation prevent a hung inventory from blocking the lease.
Names, counts and the escaped IPC envelope are bounded; an oversized inventory
is unavailable rather than truncated. Ordering is canonical, and ambiguous duplicate app
names are omitted from select options. Source options are actual reported port
IDs; they do not invent HDMI ports or CEC names.

Inventory/capability changes republish discovery after a coalesced 250 ms deadline.
Ordinary state ticks do not. App, Source, Picture mode and Audio output selects
**remain unavailable** because feature 3's command adapters do not exist. No select
becomes available with empty options. Identifiers are now a list and Root OK has
explicit ON/OFF rendering, covered by both golden fixtures.
Mute, Game mode, Kid mode and Telemetry block likewise render booleans as
`ON`/`OFF`, while a `null` reading remains unknown. Their command payloads and
unsupported-control availability are unchanged.

## Field-by-field boundary

The same conservative gates apply independently to S90D and QN90A; a successful
adapter on one device cannot grant a capability on the other.

| State / entity | This increment | Remaining acceptance or prerequisite |
| --- | --- | --- |
| `app_id`, `app_name`; App sensor | Fixed vconf read + API label; sensor becomes available only after a valid label read and vconf support | Compare Hub, Home, native and store apps; transitions clear an old label; service-context API/SMACK access on each firmware |
| `volume`, `muted` | Validated integer 0–100 and boolean state; controls still unsupported | Compare OSD at 0/15/100 and mute/unmute using the physical remote, including external audio routes; no key-relative estimate |
| `cpu_pct`, `mem_used_pct` | Available after successful kernel reads; warmup/failure unknown | Compare same-interval existing telemetry; inspect overhead and standby behavior |
| Firmware, Uptime, Root OK | Existing boot-guard enrollment firmware, CLOCK_BOOTTIME, admitted root UID | Firmware is not a live update detector; do not bypass its exact guard |
| Agent uptime | Native worker process age from its admitted kernel start identity | Compare `/proc/<pid>/stat` and `CLK_TCK`; reconnect/birth must not reset it, a separately approved worker restart must reset it while boot Uptime continues |
| `power`, `screen` | Unsupported / null | Distinguish on, picture-off, standby and process-off with independent panel/power observations and bounded read-only native evidence; connectivity or deviced state alone is insufficient |
| `input`, `input_label`; Input sensor | Unsupported / null; real port inventory only | Establish visible source ownership plus CEC label API/schema. Changing CEC names must change discovery, while preserving command port identity |
| `signal.resolution`, `refresh_hz` | Unsupported / null; [offline MAIN-window model](../../research/mqtt-state/README.md) | Prove selected MAIN input is visible, reject cached timing behind streaming apps and no-signal inputs, validate units/transitions per firmware |
| `signal.hdr`, `vrr`, `allm`, `game_mode` | Unsupported / null | Model-specific current-signal getters and tested enums; capability support is not active signal state |
| `audio_output` | Unsupported / null | Actual speaker/ARC/eARC/Bluetooth route plus real route inventory. AudioControl output mode is a **codec**, not a route |
| `picture_mode` | Unsupported / null | Read current mode in each applicable input context and retrieve nonempty real options |
| `wifi_rssi_dbm`, `temp_c` | Unsupported / null | Proven dBm readings and identified thermal sensor/units. Do not convert normalized Wi-Fi strength or choose an arbitrary thermal zone |
| Firmware update pending | Unsupported / null | Feature 4/7's real update-status source; preserve firmware guard refusal |
| Power/Screen/Mute/Game mode/Kid mode/Telemetry block switches; all selects/numbers; Screen message | Unsupported | Feature 3/5/6/8, with their own tests, guards and acceptance; no commands dispatch in this increment |

The documented TVWindow API describes its selected input window, which may remain
behind another application's picture. The offline prototype deliberately has no
production import or TV-window privilege. It cannot make Input/Resolution/Refresh
rate available. Power distinctions, CEC, picture modes, route and signal-format
work are explicit unfinished qualification work, not silently inferred adapters.

## Verification without devices

Run `npm test` for optional API absence/errors, inventory changes, hangs, late
callbacks, cancellation, admission/maintenance fences and the offline signal model.
Run the existing [MQTT container suite](mqtt.md#offline-verification) with pattern
`native_mqtt*test.py`. It covers kernel resets/overflow/missing data, foreground
hangs/oversize output/recovery, stale readings, dynamic discovery, disabled state,
real production-worker IPC and shutdown, birth/reconnect and command rejection.
The process-age tests cover tick units, subsecond boundaries, bad identity/clock
data and recovery, plus actual process restart versus broker reconnect and birth.
The normal native build checks the new headers in its source manifest, ARMv7
soft-float ABI, dependency/GLIBC limits and two byte-identical builds. These checks
cannot qualify vendor API semantics or signed service privileges on a TV.

## Later owner-run acceptance and rollback

1. Finish the separately prepared **feature-1 S90D-only** acceptance first,
   including its separately authorized reboot observation. Feature 1 has 26
   entities; this feature-2 build has 27 because Agent uptime is additive.
   This document does not authorize any live action.
2. For a separately authorized feature-2 trial, retain original credentials,
   signed prior package, native candidate, checkout and journals. Follow the
   [native handoff guide](native-worker-upgrades.md), including exact identity,
   firmware/hash, registration, pending-operation and independent SDK recovery
   checks. The first feature-2 trial is S90D only, after James's approval; do not
   contact QN90A. Repeat HA-side A (discovery/state/command refusal), B (birth) and
   C (broker outage/retained-command refusal), with each exercise coordinated by
   the owner. Installing a package is separate from selecting its native worker.
3. Compare each implemented field against the TV/telemetry, allowing roughly eight
   seconds for app identity/label convergence. Never accept a previous app's label
   under a new ID. Inventory changes should settle within 30 seconds plus debounce,
   and unchanged inventories must not republish discovery on every state tick.
   Record fields that stay unsupported on that model; do not force-enable them.
4. Observe error/recovery and state expiry under an approved coordinator/service
   interruption. Confirm no command replay, health at 60 seconds despite frequent
   state changes, and correct republication on broker reconnect/HA birth. Verify
   Hub preferences, Samsung Home fallback and existing telemetry independently.
   TV standby/reboot/AC-loss exercises require their own authorization and
   independent unattended-Hub/root-worker observations.
5. To remove just state sampling, journal `state:false` in the private config and
   restart through the guarded lifecycle; confirm CPU/Memory/App become unsupported
   and new values clear. To remove MQTT, use `enabled:false`. To reverse code, use
   the retained native candidate with a fresh reviewed reverse handoff, then the
   original signed package/journal if needed. Never erase selection, pending
   markers or history to make recovery appear clean. Restore only journal-owned
   config; keep credentials, Hub, preferences and telemetry. Retain SDK rescue
   until the old worker, Hub and telemetry are independently verified. HA-side
   removal of retained discovery is a separate owned-topic action.

## Read API provenance

Original 0BSD implementation; no vendor code copied. Kernel calculations reuse
this repository's telemetry semantics; the foreground key and vconf loader follow
its telemetry/boot/recovery readers. API contracts were checked against Samsung's
[Application](https://developer.samsung.com/smarttv/develop/api-references/tizen-web-device-api-references/application-api.html),
[TV Audio Control](https://developer.samsung.com/smarttv/develop/api-references/tizen-web-device-api-references/tvaudiocontrol-api.html),
[System Information](https://developer.samsung.com/smarttv/develop/api-references/tizen-web-device-api-references/systeminfo-api.html)
and [TV Window](https://developer.samsung.com/smarttv/develop/api-references/tizen-web-device-api-references/tvwindow-api.html)
references. Documentation does not prove availability in either installed service.

Process-age units follow Linux's [`/proc/<pid>/stat` starttime contract](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)
and [`CLOCK_BOOTTIME`](https://man7.org/linux/man-pages/man2/clock_gettime.2.html).
These contracts and offline tests do not qualify TV suspend/resume behavior.
