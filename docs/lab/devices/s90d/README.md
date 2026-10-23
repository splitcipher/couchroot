# Couchroot integration on Samsung S90D

> **2026-10-12 recovery correction:** direct `tools/s90d/restore.py` commands
> below are historical Home-settings procedures with placeholder addressing, not
> current composite-helper/cache recovery. Use the original shared setup journal
> for setup rollback and [boot checkpoints](../../../guides/s90d-boot-recovery.md) for a future
> S90D boot trial. No current live state or physical boot timing was verified.

2026-09-19, QN55S90DAFXZA at `192.0.2.12`, firmware 2130.0, Tizen 9,
build `T-PTMDAKUC-0090-REL-202605141701`.

## Installed app

`MiniHub001.Hub` (package `MiniHub001`, version 0.1.0) is signed and installed
through Samsung's normal developer installer. the owner confirmed that the hub
renders on the TV and selecting Plex with the remote opens Plex. The hub requests
only `application.launch`; assets are local and no Mac server or root process is
required to use it. Plex, YouTube, and Samsung Home retain their existing app IDs.

The tested signed artifact is private at
`~/.local/share/samsung-tv-research/signing/package/MinimalHub.wgt`:
SHA-256 `a668a69e742ca04bd4df1bc4f3f40168272f27e8cb169c228b5b0aac5edc121d`,
12,688 bytes. Installation with filename `Minimal Hub.wgt` failed; the same bytes
installed successfully after removing the space from the filename.

The actual uninstall completed, a subsequent registry/path check found no hub,
and Plex, YouTube, and Samsung Home remained registered. The identical package
was reinstalled successfully. Evidence: `sessions/20260919T231302.333625Z-run/`.
The install directories have SMACK `User::Home`; the package directory belongs
to `tizenglobalapp:root`, and its writable app directory belongs to `owner:users`.
Both were mode 755. No app-registry or signature-policy bypass was used.

## Signing and tooling

the owner completed the Samsung account login himself, including the separate
certificate-service login. A reviewed local adaptation of the third-party
[`samsung-tv-cert`](https://github.com/titlog/samsung-tv-cert) client obtained
Samsung-issued author and public-level distributor certificates through Samsung's
certificate API. Its endpoints and certificate formats were compared with the
installed official Tizen extension server source. This client is not a Samsung
product. The OAuth callback bound only to loopback and has exited.

Private tooling under `~/.local/share/samsung-tv-research/` includes:

- Official VS Code extension 10.4.2 in an isolated extension directory.
- Official extension server archive, inspected but not started, SHA-256
  `81105e357174cf5319aaba0ef734905b309aaa533b22d021aa7525a25fc8a88b`.
- Official CLI/common/web/certificate-generator/SDB/utils packages verified
  against Tizen's package-index SHA-256 values. CLI reports version 2.5.25 and
  uses the existing Java 21 installation.
- `tizen-sdk/cli-data/profile/profiles.xml`, profile `MinimalHub`.
- Private author/distributor keys, certificates, DUID, and password under
  `signing/`; permissions restrict these to the owner. None are committed.

`scripts/sign.py` signs a private staged copy so the CLI cannot leave
signature documents or certificate subjects in the source tree. A new staged
build completed successfully. It does not replace the exact artifact tested on
this TV. The six launch-adapter tests passed.

## Native routing and rollback

The physical Home handler calls `ContextProduct::LaunchHomeApp`, resolving
`http://tizen.org/appcontrol/operation/main` through
`app_operation_get_current_app`. The corresponding native setter calls
`app_control_set_defapp`. An SDK-context helper successfully assigned the hub,
read it back, restored Samsung Home, and read that back. UID 0 and UID 901 queries
both resolve the same owner assignment. The Home assignment survives reboot.

The authoritative record is the main-operation row in
`/opt/dbspace/user/5001/.appsvc.db`; its original row is:

```
http://tizen.org/appcontrol/operation/main | NULL | NULL | com.samsung.tv.csfs
```

The two `NULL` fields are literal strings. The database is owned by
`5001:system_share`, mode 666, SMACK `User::Home`. Its backup is mode 664 with
the same owner/label. The global `/opt/dbspace/.appsvc.db` has no main row and is
not the owner assignment. All writes use the native API, not SQL injection or
manual registry edits.

The system settings database is `/opt/var/lib/buxton2/system.db`, mode 600,
owned by `buxton:buxton`, SMACK `System`. The SDK route can update the selected
values through native `vconf_set_str` / `vconf_set_int`. Final helpers use these
setters to preserve the existing key permissions. No system-wide access checks
or SMACK rules were changed.

Exact logical SQLite snapshots and xattr sidecars are private:

| Evidence directory | Contents |
| --- | --- |
| `dumps/20260919T231736Z/` | System settings and global app-service DB before preference tests |
| `dumps/20260919T232141Z/` | Owner app-service DB and its backup, both with original Samsung Home row |

Both SQLite backup operations and xattr collection passed integrity checks.
The earlier accompanying stat command returned 2 because its non-hidden glob
missed `.appsvc.db`; this did not affect the snapshots. A subsequent explicit
stat succeeded. Owner DB snapshots were taken after the first successful native
assignment/restore round trip, before retaining a hub assignment.

Original typed settings:

| Setting | Type | Original |
| --- | --- | --- |
| `db/appfw/home_appid` | string | `com.samsung.tv.csfs` |
| `db/appfw/startup_appid` | string | `org.tizen.tv-viewer` |
| `db/appfw/booting_appid_backup` | string | `org.tizen.tv-viewer` |
| `db/first_screen/type` | string | `com.samsung.tv.csfs` |
| `db/menu/smart_hub/ontvsetting/auto_start` | integer | `0` |

The Home API and each changed preference passed a change/restore/readback test.
The exploratory `vconftool` command required `-f` to update an existing key;
without it, the initial attempt refused the update. A later serialized-metadata
audit found the Home key's privilege fields had become `0`. The final implementation
therefore uses native value setters instead. Temporary root restored this one
key's original read/write privilege with `buxton2ctl set-read-priv` and
`set-write-priv`, both to `http://tizen.org/privilege/internal/default/public`.
No global security-enable/disable operation was used.

The native rollback passed with the restored permissions in
`sessions/20260919T234723.029135Z-run/`; effective privilege getters confirmed the
original read/write values afterward in `sessions/20260919T234746.892597Z-run/`.
`tools/s90d/enable.py` then applied the hub through the same native setters in
`sessions/20260919T234851.892182Z-run/`, and privilege readback again matched in
`sessions/20260919T234858.059027Z-run/`. Audit writer/process fields can change as
normal setters run; original logical records remain in the private backups.

After installing the signed package, the reproducible configuration command is
`python3 tools/s90d/enable.py` from the workspace root. It uses the same
bounded native helper as rollback and leaves no helper process running.

Before uninstalling, restore the recorded Home/startup configuration:

```sh
python3 tools/s90d/restore.py
```

This builds and uploads a temporary bounded native helper, restores the selected
values through their APIs, verifies readback, and deletes the uploaded helper.
It does not restore a whole database over unrelated newer settings. Use this workspace command for rollback; it supersedes the exploratory private
rollback scripts, which depended on a staged helper and the legacy CLI.

Then uninstall if desired:

```sh
"$HOME/.local/share/samsung-tv-research/tizen-sdk/cli/tools/ide/bin/tizen" \
  uninstall -s 192.0.2.12:26101 -p MiniHub001.Hub
```

## Startup validation

Writing only `db/appfw/startup_appid=MiniHub001.Hub` did not establish startup.
The controlled reboot changed the boot ID from `00000000-0000-4000-8000-000000000011`
to `00000000-0000-4000-8000-000000000012`. Samsung reset that string to the TV
viewer, and the foreground app was TV Plus. The hub remained installed and its
Home-operation assignment persisted. Evidence:
`sessions/20260919T232547.943753Z-run/`. Its exit 1 is the explicit report that
the hub was not running, not a failed preference read.

Read-only inspection of this firmware's `app-boot-manager` showed that it uses
`db/appfw/home_appid` to choose the Home app and the Smart Hub `auto_start` setting
to choose foreground versus background launch. A reversible trial therefore sets
the former to `MiniHub001.Hub` and the latter to `1`. Samsung then updated the
startup-app string to the hub itself. `db/first_screen/type` remains Samsung Home.
The next controlled reboot changed the boot ID to
`00000000-0000-4000-8000-000000000013`. All selected values survived, the derived
startup and boot-backup IDs named the hub, and the hub was running in the
foreground. Evidence: `sessions/20260919T233159.178671Z-run/`, exit 0.

The complete Mac-side restore command was exercised afterward and restored
Samsung Home, integer autostart `0`, and the original startup/boot-backup values.
The helper upload was removed by its exit trap. A distinct assembly/filename
(`MinimalHubControl.dll`) avoids the TV's resolver selecting an older same-named
assembly. The guarded helper's actual read-before-write/readback path passed in
`sessions/20260919T233319.670523Z-run/`. The working hub configuration was then
reapplied successfully in `sessions/20260919T233403.259142Z-run/`.

On-demand root passed after the first hub reboot: UID/GID 0, full available
capability mask, original passwd/public-key hashes unchanged, and temporary
namespace files removed. See [root persistence verification](persistence.md).
No root daemon, custom boot unit, firmware write, boot-slot change, global security
exception, or unauthenticated network shell was installed.

## App and navigation checks

the owner’s real remote/Plex test passed. Bounded root diagnostics then used the
TV's existing `input_keyevent` utility, which sends paired key-down/key-up events
to the window manager's system D-Bus interface. No input daemon, listener, or
persistent root helper was added. The SDK identity cannot execute this restricted
tool; temporary root can, without changing its permissions or SMACK policy.

- Home, Up, Right, OK selected the hub's YouTube tile. The foreground became
  `com.samsung.tv.cobalt-yt`, the installed native YouTube implementation. The
  legacy launch ID itself then reports not running, so that initial wrapper-ID
  check returned 1 despite the successful transition. Evidence:
  `dumps/20260919T233503Z/`.
- A subsequent sequence verified YouTube → Home → hub → Plex → Home → hub →
  Back dialog → Samsung Home. Foreground IDs matched every transition, and
  Samsung Home had the focused, visible compositor window. The operation returned
  0. Evidence: `dumps/20260919T233603Z/`.
- These are app-navigation/window checks. Signed-in playback and A/V quality
  were not tested. A separate physical Home-button confirmation is still optional;
  the automated Home-key path is verified.

## Standby, wake, and final state

The discrete power-event attempt returned normally but the compositor reported
On both times, so it was not counted as a standby pass. The normal `XF86PowerOff`
event did produce a complete standby/wake cycle. The TV API reported `standby`
at 9, 12, and 15 seconds and `on` from 18 seconds onward. The boot ID stayed
`00000000-0000-4000-8000-000000000013`, and Minimal Hub was the foreground app after
wake. The prepared wake recovery packet was unnecessary and was not sent.
Evidence: `dumps/20260919T234043Z/hub-power-key.txt` and private
`signing/hub-power-key-states.jsonl`.

The final version of `tools/s90d/restore.py` was exercised in
`sessions/20260919T234135.540769Z-run/`: native Home assignment, original Home
preference, autostart `0`, and original startup/boot-backup values were restored.
The tested hub configuration was then reapplied in
`sessions/20260919T234203.042502Z-run/`. All six bundled app source files were
compared byte-for-byte with the installed signed artifact and match the workspace.

The corrected native-setter implementation was validated through one final real
reboot. Boot ID `00000000-0000-4000-8000-000000000014` was new; the hub was running
in the foreground, autostart was `1`, and all derived app IDs named the hub.
Evidence: `sessions/20260919T235056.672532Z-run/`. Effective Home-key read/write
privileges still matched the original public privilege after reboot:
`sessions/20260919T235113.005439Z-run/`. On-demand root and cleanup passed again.

Final presentation evidence `dumps/20260919T235204Z/` shows Minimal Hub's
1920×1080 window focused and visible. The five failed systemd units were all in
the seven-unit pre-reboot baseline; no new failed unit appeared. Final cleanup
`sessions/20260919T235255.338656Z-run/` removed the known installer packages and
native test helpers, verified root staging directories absent, and confirmed
unchanged passwd/public-key hashes with the hub still running. Interrupted
collectors' expired TLS keys were removed locally; signing keys remain private.
The loopback desktop preview server was stopped. The TV hub needs no Mac server.

Sanitized machine-readable results:
[`inventory/samsung/2026-09-19/hub/verification.json`](../../inventory/samsung/2026-09-19/hub/verification.json).

## Vendor references

- [Samsung certificate requirements](https://developer.samsung.com/smarttv/develop/getting-started/setting-up-sdk/creating-certificates.html)
- [Samsung VS Code certificate workflow](https://developer.samsung.com/smarttv/develop/tools/additional-tools/vscode/creating-certificates.html)
- [Samsung TV CLI](https://developer.samsung.com/smarttv/develop/getting-started/using-sdk/command-line-interface.html)


## Cinematic UI redesign — 2026-09-19 (0.2.2)

Installed a warm charcoal/gold design with geometric Plex/YouTube artwork,
large focus rings, an offline SVG play emblem, and a matching Back dialog.
Removed the room name and HOME wordmark at the owner’s request. Five playful
headlines rotate every 30 seconds, pausing while hidden, launching an app, or
showing the dialog. The dialog also keeps Tab focus within its two actions.
No app IDs, privileges, Home assignments, or startup settings changed.

The final signed artifact is private at
`signing/builds/hub-hdr40dyx/MinimalHub.wgt` (15,071 bytes), SHA-256
`4718c94ea83c9b4e23f0238de542ca4b18f4241e6cf75fda9cacf584df8a380e`.
All six signed source files match the workspace and installed TV files.
The installer upload was removed. Source/cleanup evidence:
`sessions/20260920T000931.761155Z-run/`, exit 0.

Browser checks covered the default viewport, 1920×1080 bounds (no overflow),
remote-style navigation, preview launches, Back dialog, Tab focus, automatic
headline rotation and its pause with the dialog open. No browser warnings or
errors were reported. All six launch-bridge tests passed. The loopback-only
preview server remains available at http://127.0.0.1:8766 for design review;
the installed TV app remains fully independent of that server.

The first on-TV check passed both app launches but sampled Samsung Home before
its transition completed (exit 1); it was not counted as a full pass. Rechecking
with spaced key events and a longer transition wait passed every assertion on
the final 0.2.2 build: hub → YouTube → hub → Plex → hub → Samsung Home → hub.
The final compositor window was focused and visible at 1920×1080. Home app ID
remained `MiniHub001.Hub` and autostart remained integer `1`.
Evidence: `dumps/20260920T000843Z/hub-redesign-navigation.txt`, exit 0.
Temporary root staging cleanup completed successfully. This visual update did
not require another reboot; the existing reboot/standby verification above
applies to the unchanged startup integration. Actual new-design appearance on
the panel has not been separately confirmed by the owner.

Exact original six-file sources remain private at `signing/ui-before-0.2.0/`,
and the original 0.1.0 signed package remains in `signing/package/`. A signed
rollback build contains that original UI with only the version changed to
0.2.3, allowing a forward package update. Run:

```sh
~/.local/share/samsung-tv-research/signing/rollback-ui-0.2.0.sh
```

The rollback script was prepared before deployment and points to
`signing/builds/hub-zfjiyt_w/MinimalHub.wgt`. It restores the old UI while keeping
the hub's existing Home/startup assignment. This particular UI rollback package
has been signed and its command syntax checked, but was not installed during
the visual refresh. For full Samsung Home/startup restoration, use the already
tested workspace `tools/s90d/restore.py` command documented above.


### Card-number cleanup

Removed 01/02 from both cards and deleted unused number styles. Re-signed and
updated the existing 0.2.2 package in place; no behavior or configuration changed.
Current artifact: `signing/builds/hub-iiznlnco/MinimalHub.wgt`, 15032 bytes,
SHA-256 `9c23d2cf5e2a7685b0844a29fd57be363821030d8e97708cf7c993142167778a`. Browser accessibility inspection confirms both numbers
are absent. All six installed files match the workspace, installer upload was
removed, and hub is foreground. Evidence:
`sessions/20260920T001224.916106Z-run/`, exit 0. Earlier visual rollback remains
valid; previous signed builds are retained privately.


## Edit apps and Settings — 0.3.5 (2026-09-19 CDT)

The current UI replaces the fixed pair with locally saved, remote-editable
shortcuts. Live discovery was verified inside the already signed app, without
adding privileges. Netflix was added, launched, moved, removed from Home, and
confirmed still installed. Reboot, document reload, signed updates and
standby/wake preserved saved order. The existing Home/startup assignment remains
unchanged. See [the complete feature record](../../../guides/edit-apps.md) for discovery filters,
focused automated tests, native/physical evidence and limitations.

Home uses centered logo-only cards and a bottom menu. The gear holds sound,
comfortable/compact layout, confirmed shortcut reset, and remote help. Back no
longer shows an exit dialog or launches Samsung Home, even on rapid repeated
presses. Samsung Home remains an explicit footer action. Physical feedback on
the immediate focus/native sound change was positive. No resident service,
background process killer, external asset, telemetry or server was added.

The current pre-feature rollback is the privately prepared 0.3.99 signed copy of
0.2.2, not the older 0.2.3 package described in the historical sections above:
`~/.local/share/samsung-tv-research/signing/edit-apps-rollback/rollback.sh`.
Full integration rollback remains `python3 tools/s90d/restore.py`. Signing material and
raw device evidence stay outside Git.

## Alternative screensaver route (independent)

An independent owner report documents a route that leaves `libgl-demo-app.so`
untouched and overlays `ContentList.json` to select a signed web app:
[web-app-screensaver.md](web-app-screensaver.md). It is limited to
`QN55S90DAGXZD` / `T-PTMDUABC-0090-2130.0`, is not a supported profile, and the
boot bytes are per-firmware.
