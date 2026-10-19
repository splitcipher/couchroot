# Samsung S89C setup and hardware checks

On 2026-10-18, Minimal Hub 0.4.1 was signed for the owner's 77-inch
`QN77S89CBFXZA`, installed and selected as Home. The owner confirmed that the
launcher displays installed apps, responds to the remote's arrows and opens
again when Home is pressed from another app. The owner chose to keep it.

The checkout starts from upstream commit
`83906b468836869933012da03a4018fb339462b3`.

## Observed device and settings

| Detail | Observed value |
| --- | --- |
| Platform | `23_PTM_QD_T09` |
| Firmware | `T-PTMCAKUC-0090-2220.4` |
| Build | `T-PTMCAKUC-0090-REL-202603190200` |
| OS | Tizen 9.0.0 |
| Kernel and architecture | Linux 5.4.77, ARMv7 (`armv7l`) |
| Managed helper runtime | .NET 6.0.9 |
| Launcher package / app | `MiniHub001` / `MiniHub001.Hub` |
| Home operation and Home setting | `MiniHub001.Hub` |
| Smart Hub autostart | Integer `1`, preserved from the original configuration |
| Reported startup app | `MiniHub001.Hub` |

The .NET host and launcher hashes match the reviewed S90D runtime. Native API
calls on this S89C also confirmed the current Home assignment, a working Home
setter and eligibility for the installed web app to start as Home. These checks
ran as UID 901 (`sdk`). Root access stayed disabled.

The original Home operation, `db/appfw/home_appid` and
`db/appfw/startup_appid` all named `com.samsung.tv.csfs`. The restore command
returned those values to Samsung Home and preserved integer autostart `1`.
Selecting Minimal Hub through the native API updates the reported startup app.
The final assignment was verified after the recovery timer had exited.

See the [sanitized inspection record](../../../inventory/samsung/2026-10-18/s89c/inspection.json).
Private identities, signed artifacts and raw output live under ignored
`.local-tools/` directories.

## Samsung signing

The local `CouchrootS89C` profile contains Samsung-issued author and distributor
certificates. The owner completed Samsung account sign-in. Certificate validity
and CA chains passed inspection, and the distributor certificate contains this
TV's SDK signing DUID. Passwords live in macOS Keychain.

Retrieve the signing DUID through the official SDB `getduid` service. The HTTP
identity API's `duid` field contains the network UUID on this set. An initial
distributor certificate using that UUID was rejected during installation.
Issuing a corrected distributor certificate with the SDK DUID resolved the
failure while preserving the author key.

Samsung's official tools run through Rosetta 2, installed with the owner's
approval. The pinned local packages include SDB 4.2.36 and Tizen Core 10.0.18.
Samsung's certificate helper comes from `Samsung/tizen-agent-skills` commit
`21af18ca1e4ab83acb8aafb277d2b93cbf531b2e`; the local copy requires HTTPS
certificate verification for its CA requests. Package archives were checked
against the official Tizen catalog's SHA-256 values.

The shared Couchroot Builder staged the launcher sources. Tizen Core's `tz pack`
produced the signed WGT, which passed the shared `verify_package` checks against
independently inspected certificate pins. Every installed file matched its
signed archive member. The older Java CLI failed on a missing XML utility;
its local shell wrapper also needed argument quoting for this workspace's spaces.

Keep `.local-tools/tizen-sdk/data-data/keystore/samsung/CouchrootS89C/` and the
matching Keychain entries when backing up this setup. Updates require the same
author identity. Signing trust and the package manifests stay private.

## Recovery on this Mac

From the Couchroot checkout, check readiness without changing Home:

```sh
.venv/bin/python .local-tools/s89c/restore-home.py --check
```

To restore the captured Samsung Home configuration:

```sh
.venv/bin/python .local-tools/s89c/restore-home.py
```

This private command verifies the physical TV identity, Developer Mode host and
runtime hashes. It checks the saved helper's digest, reuses an existing SDB
connection or connects once, and uploads the helper when performing recovery.
Native setters preserve the settings' access labels. Readback confirms Samsung
Home, the original startup value and autostart `1`. The installed Minimal Hub app
remains available.

The command and its pinned helper are local preparation files excluded from Git.
Preserve `.local-tools/s89c/` with the signing setup. The private
`home-trial.json` records the trial and original typed settings. The historical
S90D restore procedure uses its own autostart baseline of `0` and must stay
separate from this S89C procedure.

A temporary TV-side watchdog exercised automatic recovery. Its SDK-shell
cancellation marker failed to prevent that recovery. The watchdog exited before
the final Home assignment. Its trial commands were retired and temporary files
were removed. The underlying native restore passed
the roundtrip check; the local wrapper passed its `--check` readiness check.

## Local development

A Python 3.12 virtual environment, locked JavaScript dependencies and local
Playwright browser binaries are prepared. The .NET SDK 10.0.301 matches
`global.json`.

```sh
. .venv/bin/activate
export PATH="$PWD/.local-tools/dotnet:$PATH"
export DOTNET_ROOT="$PWD/.local-tools/dotnet"
export DOTNET_CLI_HOME="$PWD/.local-tools/dotnet-home"
export NUGET_PACKAGES="$PWD/.local-tools/nuget"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.local-tools/playwright"
npm run dev
```

Open <http://127.0.0.1:8766>. The browser workbench simulates TV apps. Use arrows,
Enter and Escape in the preview. `npm run package` produces an unsigned WGT;
installation requires the TV-specific signing profile.

The read-only identity command remains available:

```sh
.venv/bin/python -m tvsetup.s89c_inspect TV_IP
```

It checks the exact model and returns selected identity fields while omitting
private identifiers. Its `setup_supported: false` keeps the general installer
boundary explicit.

## Remaining hardware scope

Cold reboot and standby recovery remain untested. The S90D's native boot/splash
helper and writable-cache assumptions require separate S89C work. General
`tv-setup` / `deploy-ui` commands still refuse S89C because a complete integration
profile has yet to be implemented and accepted.

HDMI shortcuts await a native source-handoff check; the launcher includes a
Samsung Home fallback for inputs. See the [HDMI investigation](../../research/hdmi-shortcuts.md).
App cleanup and alternate screensavers remain outside this setup. A telemetry
receiver/service was not provisioned.

The earlier host suite passed 233 Python tests and 118 JavaScript/browser tests.
This session's checks covered certificate chains and signatures, installed-file
hashes, native Home/readback and recovery, plus the owner's physical remote test.
The shipped UI source stayed unchanged during signing and hardware validation.
