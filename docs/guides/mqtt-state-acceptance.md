# Feature-2 S90D acceptance contract (not deployed)

Use the private pinned checklist for the exact source, proposed package version,
artifact digests, original enrollment and accepted feature-1 recovery set. Source
and offline tests do not qualify a service-context API on the TV. QN90A is gated
on S90D acceptance and still requires its exact 2310 trial contract.

## Discovery and HA entities

There are **27 components and 27 distinct unique IDs**: the prior 26 plus diagnostic
sensor **Agent uptime**, `tv_<id>_agent_uptime`, unit seconds. Existing Uptime and
`tv_<id>_uptime` remain unchanged. No Volume level or Muted sensors are added;
volume/mute UI controls wait for feature 3. Raw state can contain their readings.
Device name and identifier are unchanged; identifiers is now `["tv_<id>"]`.

While MQTT is online, four entities always use real availability: **Firmware,
Uptime, Root OK and Agent uptime**. Three more use it only after their adapter
has succeeded: **App (sensor), CPU and Memory**. Thus the healthy target is
**7 available / 20 unavailable**, not unconditional promotion of all seven.
A missing/denied adapter remains unavailable and must be recorded as an acceptance
gap; do not force it on. A previously readable adapter can be available but unknown
during a transient failure. CPU's first sample is unknown until a valid delta.

These **20 remain on `tv/<id>/unsupported`**, including controls with readable state:

- Switches: Power, Screen, Mute, Game mode, Kid mode, Telemetry block (6).
- Selects: Source, App, Picture mode, Audio output (4).
- Numbers: Volume, Sleep timer (2).
- Sensors: Input, Resolution, Refresh rate, HDR format, Wi-Fi signal, Temperature (6).
- Binary sensor: Firmware update pending (1).
- Notify: Screen message (1).

Real nonempty App/Source inventories can populate select options without making
them available. Picture mode and Audio output options remain empty. Complete
inventory changes, including removal, republish discovery after coalescing; normal
state ticks do not. An inventory is not proof of active input or usable commands.
All valid commands still return `unsupported_capability`; malformed, unknown and
retained commands retain their existing refusal behavior, with no TV action.

## Exact field expectations

| Document / field | Expected value when adapter succeeds | Failure or unsupported boundary |
| --- | --- | --- |
| state.app_id | Exact foreground app ID; Hub is `MiniHub001.Hub` | null when foreground cannot be read; it can be present while name is null |
| state.app_name | Platform application label; Hub manifest label is `Minimal Hub` | Resolve the exact same ID through getAppInfo; never reuse another app's label. A differing localized platform label needs readback, not hardcoded replacement |
| state.volume | JSON integer 0–100 matching absolute TV API reading | null if getter missing/denied/invalid/stale; Volume remains unavailable |
| state.muted | JSON boolean true/false matching isMute | null on missing/denied/invalid/stale read; Mute remains unavailable |
| health.cpu_pct | JSON number 0–100, aggregate utilization | null on initial warmup/reset/read failure/non-increasing counters/gap >45s; valid pair recovers |
| health.mem_used_pct | JSON number 0–100, `(MemTotal-MemAvailable)/MemTotal*100` | null on invalid/missing kernel data; not sum of RSS |
| health.agent_uptime_s | New field: nonnegative whole seconds of native worker process age, at most boot uptime | null if kernel identity/clock invalid; birth/reconnect must not reset it; new worker resets it |
| health.uptime_s | Existing nonnegative whole seconds since boot | Unchanged meaning; native handoff does not reset it, TV reboot does |
| health.firmware | Existing guard-enrolled firmware, S90D `T-PTMDAKUC-0090-2130.0` | Not a live firmware-update detector; exact admission guards still apply |
| health.agent_version | Version supplied by the new package coordinator | Verify against the pinned planned package; not the original feature-1 version |
| health.root_ok | JSON true for admitted root worker | Explicit ON/OFF template; only meaningful while MQTT available |

Fields newly capable of moving from null to values are state.app_id, app_name,
volume, muted and health.cpu_pct, mem_used_pct. Agent uptime is additive, previously
absent. No other existing null field becomes measured in this increment.

The following remain null: state.power, screen, input, input_label, audio_output,
picture_mode, game_mode, kid_mode, telemetry_block; all five state.signal members
(resolution, refresh_hz, hdr, vrr, allm); health.wifi_rssi_dbm, temp_c,
firmware_update_pending. No qualified visible-source/panel/signal/route/thermal/
Wi-Fi/update adapter exists. `sleep_timer` is absent from state, so its template
renders unknown; its number entity remains unavailable. No event or bedtime field
is introduced. Unsupported must never be inferred from a fabricated measurement.

## Observation schedule and gates

State is sampled about every two seconds and changes coalesced over250ms; allow
roughly eight seconds for foreground/name convergence. Health refreshes every60s
and on connect/birth. CPU/memory become readable before a later health publication
may deliver values; allow a full60s refresh after warmup. App/source inventory
refreshes at most every30s, with750ms API deadlines. Duplicate app names are omitted
from options; source IDs are actual reported `tv`/`hdmi1`–`hdmi4`, not invented CEC
names. State observations expire after6s without renewal; coordinator lease expires
after10s. App name/audio clear on expiry, while kernel metrics and freshly read
foreground have their independent sampling. Failed inventories retain the previous
complete result; malformed/oversized results are not silently truncated.

Repeat A: single connection, retained discovery/online/unsupported/state/health,
27 unique entities without duplicates, conditional seven readable entities,
physical-remote app/audio comparisons, and commands refused without effects.
Do not install/remove apps solely to test inventories without separate permission.
Repeat B: owner-controlled HA restart/nonretained birth, full republication,
unchanged native PID/start ticks and increasing Agent uptime.
Repeat C: separately authorized broker outage with retained-command refusal,
then separately authorized TV reboot with independent unattended Hub/root/MQTT
checks. Root lease alone is not proof of HA acceptance. Compare Agent uptime with
kernel start ticks; an independently approved worker restart resets process age
while boot Uptime continues. Keep recovery through every checkpoint; stop on errors.

On rollback, the feature-1 discovery has26 components. Verify HA processes removal
of Agent uptime and that App/CPU/Memory return to unsupported (3available total).
A stale additive entity must not be counted as successful rollback; resolve owned
HA discovery separately, without clearing unrelated integrations or topics.
