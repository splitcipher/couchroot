# Home Assistant MQTT bridge — features 1–2

This increment implements outbound MQTT and discovery in the existing native
worker. Feature 2 is source-only and has **not been deployed or accepted on a TV**.
The owner accepted feature 1 on S90D on 2026-10-24, including discovery, birth,
broker outage and unattended reboot on the TV and HA sides. Feature 2 adds measured
state and explicitly gated remaining adapters; see the
[state/qualification guide](mqtt-state.md). Stop at this boundary before controls.
No broker, Home Assistant, router or telemetry configuration is changed.

The signed JS coordinator renews an authenticated `mqtt.start` lease every two
seconds only after native readiness, with no maintenance/upgrade hold. The worker
reads its own root-only configuration; credentials never traverse IPC or the
public HTTPS API. The operation is unavailable to bounded/held-bootstrap workers
and is not in the public API operation allowlist. A missing/invalid configuration
leaves MQTT unconfigured without preventing root administration. Existing packages
without this capability remain usable. No listener, installer, watchdog service,
credential-copy helper or new runtime dependency is added.

## Configuration and private material

The worker reads `/opt/couchroot/mqtt/config.json`. Use
[the placeholder example](../examples/mqtt.json). Each ancestor must be root-owned,
not group/other writable, and free of symlinks. Config and credential files must be
regular, single-link, root-owned files with **exact mode 0600**. Files are opened
through directory descriptors, bounded and inspected before reading; FIFOs,
devices, hard links, symlinks and unsafe parents are refused. Invalid config is
reported as an unconfigured bridge; contents and filesystem paths are not logged.

Set `device` to `qn90a` or `s90d`, exactly matching enrollment. Set `device_name` to
the owner's stable dashboard name, and `broker_host` to the existing broker's IPv4
address, port 1883. Real addresses, room labels and credentials belong in private
site material, not this public example. The prepared private per-TV examples for
this task preserve the requested names and broker; they contain no passwords.
Do not change the name after discovery, or HA's initially generated entity IDs can
differ. Unique IDs remain `tv_<id>_<key>`.

James supplies the credential file out of band, in exactly this format (LF or CRLF,
optional final line ending; no quotes, `export`, extra variables or shell parsing):

```text
MQTT_USER=tv-<id>
MQTT_PASSWORD=<32 printable non-whitespace ASCII characters>
```

The username must match the configured device. Credentials are used only for the
MQTT CONNECT packet, never put in argv, logs, retained state, discovery or IPC.
The connection uses plain TCP as specified; there is no TLS or anonymous fallback.
Do not reuse these credentials for other services. A worker restart is required
after a config/credential change; no MQTT command can reconfigure the connection.

`enabled` defaults true **only when a valid configuration is present**. Feature
flag `state` defaults true and gates the feature-2 readers. `control`, `events`
and `notifications` default true as rollout intent but cannot enable adapters that
do not exist. Setting them false also leaves those features unavailable. `kid_mode`, `resilience` and
`telemetry_block` default false; true is refused until those later features have
implementation and acceptance. Existing telemetry is left untouched: feature 1's
health snapshot does not cover it sufficiently to disable the old collector.

## Topics and discovery

Only these ACL paths are used:

| Topic | Retained | Purpose |
| --- | --- | --- |
| `homeassistant/device/tv_<id>/config` | yes | One device discovery document with `dev`, `o`, availability and `cmps` |
| `tv/<id>/availability` | yes | `online`; retained `offline` will on loss |
| `tv/<id>/state` | yes | Latest state, changes coalesced within 250 ms and refresh every 60 s |
| `tv/<id>/health` | yes | 60 s health refresh |
| `tv/<id>/unsupported` | yes | `offline` for entities whose adapters are not implemented |
| `tv/<id>/cmd/<name>` | no | Strict command envelopes; subscription is `cmd/+`, QoS 0 |
| `tv/<id>/cmd_result` | no | `cmd`, validated optional `id` or null, `ok`, fixed error code |
| `homeassistant/status` | input only | Every `online` birth triggers republication; retain is not required |

Every successful connection publishes discovery, availability, state and health
without waiting for HA. Birth messages coalesce over 250 ms and republish those
same documents. MQTT uses 3.1.1 clean sessions, a retained QoS 0 offline will,
30 s keepalive, bounded connect/frame/write deadlines and 1–60 s reconnect backoff
with per-device jitter. Subscriptions must receive successful SUBACKs. Publications
are QoS 0; a socket write is not proof HA accepted discovery. ACL/silent broker
drops require HA-side observation. Disconnects keep only the latest snapshot;
there is no offline command, result or event replay queue.

A lease expires after ten seconds without the ready coordinator. The worker then
publishes offline and disconnects. Shutdown or a broken connection relies on the
broker's will. MQTT failures do not change worker selection or acquisition policy.
No blanket retry of a TV mutation exists. The existing authenticated agent status
adds `mqtt.lease_state` with a fixed redacted code: `started` means worker admission,
not confirmed broker/HA readiness. `unconfigured` includes missing or refused files;
`disabled` is an explicit false flag. The worker emits fixed connection codes to
stderr, but the current production unit uses `StandardError=null`, so those events
are not retained there. No birth/SUBACK-success event or rate-drop counter exists.
Do not claim a historical event trace from lease status. No credential value is
exposed through this status.

Device metadata uses Samsung, model QN90A/S90D, enrollment firmware and package
version. Firmware is currently the guard-verified enrollment value, not live
update detection. Uptime remains `CLOCK_BOOTTIME`; the added diagnostic Agent
uptime (`agent_uptime_s`) measures native worker process age and resets only when
that worker is replaced/restarted. It adds one entity (27 total) without renaming
the original Uptime. Root OK describes the admitted root
worker while its MQTT availability is online. Feature 2 adds CPU/memory, fullscreen app identity/name and absolute volume/mute
where a validated read succeeds. Remaining measurements are `null`, including
power and screen, rather than inferred from process or broker health.
The initial state has the requested signal subfields. No bedtime/screen-time
entity or state is published.

### Stable entity contract

| Domain | Entity names | Current availability |
| --- | --- | --- |
| switch | Power, Screen, Mute, Game mode, Kid mode, Telemetry block | Unavailable; no mutation adapter |
| select | Source, App, Picture mode, Audio output | Unavailable; actual App/Source options when inventory is readable |
| number | Volume, Sleep timer | Unavailable; absolute volume contract, never key emulation |
| sensor | App | Available after successful vconf/API observation |
| sensor | Input, Resolution, Refresh rate, HDR format | Unavailable; visible-source qualification pending |
| sensor | Firmware, Uptime | Available while bridge is online |
| diagnostic sensor | CPU, Memory | Available after successful kernel reads; CPU warmup is unknown |
| diagnostic sensor | Agent uptime | Available while bridge is online; invalid clock/identity is unknown |
| diagnostic sensor | Wi-Fi signal, Temperature | Unavailable |
| diagnostic binary_sensor | Firmware update pending | Unavailable |
| diagnostic binary_sensor | Root OK | Available while bridge is online |
| notify | Screen message | Unavailable; JSON command template for HA plain-text messages |

App uses component keys `app_select` and `app` for its select and sensor; the domain
distinguishes the generated HA IDs. HA may retain customized or conflicting IDs;
verify the entity registry before binding a dashboard. Golden discovery fixtures
cover both node IDs with synthetic device names and every stable entity name.

Device triggers are reserved for feature 4 at
`homeassistant/device_automation/tv_<id>/<key>_<action>/config`; none are published
until actual pass-through key detection exists. The bridge does not read/grab any
remote device and does not claim that short/long/double events have been detected.
The nonretained `tv/<id>/event` topic is likewise reserved for real observations.

## Command boundary

Features 1–2 validate the full fixed command vocabulary, but **all valid commands
return `ok:false`, `error:unsupported_capability`**. They never dispatch shell
commands, generic worker operations, URLs or app launches. Invalid commands return
`unknown_command` or `invalid_payload`; retained commands return `retained_command`.
Malformed frames close the session. Overload is dropped after a 20-command burst
at 10 commands/second, including result/log amplification. Logging uses fixed
structured codes and never logs payloads, IDs, topics or network errors verbatim.

Every JSON command may include an ASCII alphanumeric/`_.:-` `id` (1–64 characters).
Unknown or duplicate fields, nested values, trailing bytes and incorrect types
are refused. Power and screen use the unambiguous boolean form `{"on":true}` or
`{"on":false}`, like mute/game/kid/telemetry switches. Source accepts `tv` and
`hdmi1`–`hdmi4`; launch_app takes exactly one of `app_id` or `name`, plus optional
`deep_link`. Volume is an integer 0–100, sleep minutes 0–1440. Notification title
and message are bounded; duration defaults to 8 in the future renderer contract,
allowed supplied values 1–60; position is optional. The exact Frigate envelope
`title,message,image_url,duration_s,id` is accepted unchanged by validation.
**No image is fetched yet.** Feature 5 must add HTTPS host allowlisting, redirect
revalidation, byte/time limits and a focus/input-safe overlay before admission.

## Offline verification

Run normal `npm test` for coordinator admission and the existing lifecycle tests.
The native MQTT suite is wired into both existing Linux/native and ARM64 CI jobs.
To run it in the existing disposable test image (no external network):

```sh
docker run --rm --network none --tmpfs /tmp:exec -v "$PWD:/src:ro" \
  -w /src couchroot-native-tests:py312 sh -eu -c '
  gcc -std=c99 -O2 -Wall -Wextra -Werror -Wno-unused-function \
    tests/mqtt/harness.c -ldl -pthread -o /tmp/mqtt-harness
  MQTT_HARNESS=/tmp/mqtt-harness python3 -m unittest discover -s tests -p "native_mqtt*test.py"
'
```

The local TCP broker simulator checks actual wire packets, credentials/will flags,
exact subscription and publication paths, fragmented/oversized/trickled frames,
birth and reconnect behavior, retained command refusal, rate limiting, lease
expiry, 60 s refresh and bounded shutdown. Config/command tests cover permission,
identity, syntax and type failures; the debouncer retains one latest snapshot.
This does not prove Mosquitto ACLs, HA entity acceptance, TV SMACK outbound access,
TV json-c compatibility, firmware controls or unattended startup.

## Owner-run deployment, acceptance and rollback

Before installation, validate the actual prepared native payload with the
coordinator's candidate checks, including its source provenance paths:

```sh
NATIVE_CANDIDATE_BUILD="$PREPARED_PAYLOAD" node --test tests/native-candidate.test.cjs
```

Use the prepared package's payload directory, containing `native-manifest.json`
and its native binaries. MQTT's five source headers live under
`native-worker/mqtt/`; they must be admitted explicitly without broadening the
source-path guard to arbitrary nested files. This offline check does not qualify
root acquisition, MQTT connectivity or unattended startup on a TV.

For each TV separately, retain the current signed package, native worker candidate,
source checkout and journals. Use the existing
[native worker upgrade workflow](native-worker-upgrades.md) and
[agent enrollment/recovery](../../agent/README.md), never a parallel installer.
A package update alone does not replace the committed native worker. QN90A exact
2310.0 still needs its explicit [trial contract](../lab/devices/qn90a/firmware-2310-agent-trial.md);
ordinary setup remains pinned to 2301.1. Preserve SDK rescue, package identity,
firmware/hash/signature checks and both on-boot/auto-restart registration flags.
This task authorizes no deployment, broker contact or network changes.

During later owner-authorized acceptance, install the private root config and
out-of-band credential file with the guarded shared journal. Verify credential
permissions without printing them, then accepted native selection/root readiness,
MQTT availability, exact discovery and HA's entity registry. Repeat broker outage,
HA restart with nonretained birth, agent restart and TV reboot; observe Hub startup
independently. Verify commands cannot invoke an arbitrary operation and telemetry
still uploads. Standby, picture-off and AC-off are **unqualified**: no wake/control
promise follows from MQTT connectivity; an offline worker cannot receive MQTT.

Use a private mode-0600 Mosquitto client configuration containing host, username
and password. Set `XDG_CONFIG_HOME` to that private directory and put options in
`mosquitto_sub` and `mosquitto_pub` files (one option/value per line). This replaces
the requested `-P <pass>` examples so passwords never appear in argv or history.
Only James should run these against the real broker, with the existing TV user:

```sh
mosquitto_sub -v -t 'tv/<id>/#'
mosquitto_pub -t 'tv/<id>/cmd/volume' -m '{"level":15,"id":"t1"}'
mosquitto_pub -t 'tv/<id>/cmd/notify' \
  -m '{"title":"Test","message":"Hello","duration_s":5,"id":"t2"}'
```

Expect retained availability/state/health, the correct named device, unavailable
future controls, and `unsupported_capability` for the valid samples at this phase.
Malformed/unknown/retained inputs must have no side effects. A TV user cannot read
the other TV or HA discovery; obtain HA-side observation with the owner. Future
features must change these expectations only alongside tested implementations.

Rollback first disables MQTT in the private root config and stops/restarts the
worker through the existing guarded lifecycle, or restores the retained native
candidate/package through its original journal. Verify offline availability and
normal Hub/worker/telemetry recovery before retiring SDK rescue. HA may keep
retained discovery: explicitly remove the owned discovery message with an empty
retained payload only during an authorized rollback; do not clear unrelated topics.
Retain the disabled config and credential file privately for recovery, or let James
remove/revoke them separately. No runtime code rewrites credentials or broker ACLs.

## Protocol references

- [MQTT 3.1.1 specification](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html)
- [HA device discovery](https://www.home-assistant.io/integrations/mqtt/#device-discovery-payload)
- [HA MQTT notify](https://www.home-assistant.io/integrations/notify.mqtt/)
- [Mosquitto private client configuration](https://mosquitto.org/man/mosquitto_pub-1.html#options)
