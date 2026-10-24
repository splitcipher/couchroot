# Root protocol v1

`SAMSUNG-TV-ROOT/1` is a private, authenticated TCP channel between the JS service
(server) and either worker. It is not the public HTTPS API. The server binds
loopback by default. The shared supported secret is 32 random bytes; the JS and
managed implementations also accept longer secrets, but the native worker does
not. Enrollment uses 32 bytes. This compatibility difference is retained.

## Framing and authentication

The server sends `SAMSUNG-TV-ROOT/1<TAB>nonce_hex<LF>` with a fresh 32-byte nonce.
Every subsequent line is `payload<TAB>mac_hex<LF>`. The MAC is lowercase hex
HMAC-SHA256(secret, nonce || one zero byte || UTF-8 payload), with no newline in
the MAC input. Split at the last tab. There is no escaping inside fields;
binary/string fields use base64. MAC comparison must not stop at the first
mismatch. TCP fragments and coalesced frames are equivalent.

The worker sends `AUTH pid uid euid gid egid cap_eff smack_base64` (eight
tab-separated fields). Admission belongs to the server: PID is positive decimal;
all four IDs must be exactly `0`. Workers send a hexadecimal capability mask and a UTF-8 SMACK label encoded as
base64 (native capture supports 255 bytes). JS currently stores these two fields
without validating the mask or enforcing the decoded SMACK length. They are not
server admission rules; the 512-byte total AUTH bound still applies. Only one authenticated
worker is active. A competing connection cannot replace it. Sixteen pre-auth
peers may wait; close, successful authentication and shutdown release the slot.
Unauthenticated peers have a ten-second overall server deadline. Worker greeting
reads have a ten-second socket read timeout; this is not an overall lease.

Line limits count bytes before LF, including the tab and MAC. An oversized or
unauthenticated frame closes the channel. C# additionally accepts uppercase MAC hex and tolerates a trailing CR in its
reader; native and JS reject both. Senders use lowercase MAC hex and LF. Empty authenticated lines
are ignored by JS but rejected by workers. Neither extension is portable.

## Limits

| Boundary | Limit |
| --- | --- |
| Server pre-auth line / worker greeting | 512 bytes |
| Waiting pre-auth server peers | 16 |
| Authenticated line, either direction | 8 MiB |
| Pending JS requests | 32 |
| EXEC command, decoded | 64 KiB, nonempty |
| EXEC timeout | 100–300,000 ms; default JS 30,000 ms |
| Held native bootstrap EXEC | 100–25,000 ms (restricted role) |
| Retained EXEC output | 1 MiB per stream, plus a truncation notice appended to stderr |
| Binary operation chunk | 1 MiB |
| Transfer size | 2 GiB |
| Legacy managed READFILE / WRITEFILE | 4 MiB |

EXEC replies get the requested timeout plus 5 seconds at the JS caller. Losing
that deadline closes the channel and reports an unknown command outcome; never
retry a mutation automatically. Both workers kill the command's process group
after the leader exits and bound pipe draining. A background `cmd &` is not a
persistent job; use the job operations for that purpose.

## Verbs

Fields below are tab separated. Requests use positive, strictly increasing
sequence numbers for the life of a connection. Responses echo the sequence.
Malformed framing, bad MAC, invalid sequence or unsupported verbs terminate the
worker session. Authentication failure never executes an operation.

| Request | Response / body |
| --- | --- |
| `PING seq` | `PONG seq uid euid gid egid` |
| `SHUTDOWN seq` | `BYE seq`, then cleanup and disconnect |
| `EXEC seq timeout_ms command_base64` | `RESULT seq exitcode timedout stdout_base64 stderr_base64`; timedout is 0 or 1 |
| `OP seq json_base64` | `OPRESULT seq json_base64`, or `OPDATA seq offset length sha256` followed immediately by exactly length raw bytes |
| `OPWRITE seq transfer_id offset length sha256` | Exactly length raw request bytes, then `OPRESULT seq json_base64` |
| `READFILE seq path_base64` (managed compatibility only) | `FILE seq length sha256` then length raw bytes |
| `WRITEFILE seq path_base64 length sha256` (managed compatibility only) | length raw request bytes, then `WROTE seq length sha256` |

Binary headers are authenticated before consuming their bounded body. SHA-256
binds that body. Binary bytes can contain tabs, LF and NUL. A short body or invalid
header closes the session; an operation error after a valid body returns a failed
operation result without losing frame alignment. Legacy file paths remain inside
the worker's allowed staging/runtime directories; writes are create-new only.

The OP envelope carries the existing file, job, helper, health and shutdown
operations defined in `native-worker/worker.c`
(and their included handlers). It retains their admission, path, handle and
recovery rules. Results contain `ok` and, on failure, `error` and an outcome such
as `rejected`, `failed` or `unknown`. Response budgets remain those in
`service/operation-deadlines.js`: 30 seconds normally, 60 seconds for file reads
and writes, 120 seconds for file open/commit and helper preparation. These budgets
do not extend a job's execution deadline. Held bootstrap disallows uploads and
retains its restricted operation surface.

## Optional outbound MQTT lease

`OP {"op":"mqtt.start","device":...,"firmware":...,"version":...}` is an
idempotent ten-second lease for the ready production worker only. The coordinator
renews it through existing admission fences. The worker opens a fixed root-owned
config path and returns only a fixed state code, never credentials. Bounded and
held-bootstrap workers refuse it; the public HTTPS operation allowlist excludes it.
It adds no network listener or generic MQTT-to-OP dispatch. See the
[MQTT guide](../docs/guides/mqtt.md) for scope, recovery and acceptance limits.

## Remaining implementation differences

- OP JSON: native permits 20,000 decoded bytes except `file.write`, whose envelope
  may reach `ceil(1 MiB / 3) * 4 + 20,000` bytes. JS permits 1,500,000 JSON bytes.
  There is no common OP maximum.
- Malformed OP JSON ends the native session.
- JS rejects whitespace-only EXEC commands. The native worker rejects empty commands
  but accept nonempty whitespace for the shell to evaluate.
- JS does not enforce the capability-mask/decoded-SMACK constraints described
  above. Changing those admission rules requires a separate compatibility decision.

## Shared vectors and provenance

`tests/fixtures/root-protocol.json` pins wire bytes, MACs, valid/invalid AUTH
admission, line boundaries and EXEC ranges. npm tests run the JS server; the
native CI suite drives the compiled worker through its real greeting and dispatch loop.
Oversized greetings omit LF so an unbounded read cannot pass by later rejecting
invalid syntax. EXEC tests exercise real timeout/command admission and output
capture. Held-bootstrap limits and session framing divergences are explicit
vectors. The parity contract links to this fixture for shared wire limits. AUTH admission assertions
apply only to JS because workers send AUTH, rather than receive it.

The adapted JS server lives at `service/root-agent.js`, outside `vendor/`.
Its MIT notice remains linked to `service/vendor/LICENSE`. `UPSTREAM.json`
preserves original upstream digests as `upstream_sha256` for modified sources and
records the checked local digest as `sha256`. The setup packager verifies every
record before any build or copy. Unmodified vendor files retain their original
hashes. Managed adaptations retain `payload/LICENSE`.

This refactor changes JS EXEC admission from 1–120,000 to 100–300,000 ms, both
workers' authenticated line cap from 4 to 8 MiB, worker greeting caps from 4 MiB
to 512 bytes, worker greeting read timeouts to 10 seconds, and native SMACK
capture capacity from 127 to 256 bytes (room for a 255-byte label plus newline).
Server pre-auth limits remain 16 peers / 512 bytes. Bootstrap restrictions,
operation semantics and recovery are unchanged. Hardware acceptance is pending.
