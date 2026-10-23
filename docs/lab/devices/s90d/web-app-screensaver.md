# Alternative S90D screensaver route: ContentList overlay -> signed web app

> **Independent owner report, not a supported Couchroot profile.** Tested only
> on `QN55S90DAGXZD` / `T-PTMDUABC-0090-2130.0` (Tizen 9, Brazilian regional
> build). Do not infer `T-PTMDAKUC` or other-model compatibility. The boot cache
> bytes are per-firmware; the mechanism ports, the pinned bytes do not. This note
> does not change profiles, installers, or guards.

Date: 2026-10-23. Related issue:
<https://github.com/splitcipher/couchroot/issues/41>

## Idea

Couchroot's S90D native route replaces the renderer library
(`libgl-demo-app.so`) with an Asteroids implementation of its GLES2 ABI. This
route leaves that library and the native ABI untouched. Instead it overlays
`ContentList.json`, the small selection file read by Samsung's
`com.samsung.tv.glscreensaver-launcher`, so the launcher selects a signed web app
(`KurumiSvr1.Saver`). The launcher retains the idle path, key grabs, power
handling and return-to-app behavior; the web app only draws.

The overlay is a read-only bind mount applied in PID 1's mount namespace by a
one-shot `Boot.dll` started by AT-HUB at boot. The helper runs the original
`/opt/etc/parseinfo.sh` before the mount and exits; it is not a resident root
agent and opens no listener. The AT-HUB first unit in
`/opt/etc/systemd/oneservice` is patched to run the helper; the unit keeps its
209-byte length and all following offsets. The original cache, table, parseinfo
and stock ContentList are backed up under `/opt/minimal-saver`; removing the
mount/restoring the cache is the rollback. The helper checks the stock and custom
ContentList hashes and leaves the stock saver intact on any mismatch.

## Evidence (owner-authorized, 2026-10-22/23)

- Stock `libgl-demo-app.so`:
  `4f0b36d9639a194936def6250a03db1383db284f11f74d83ec7dda50420befaa`
  (matches Couchroot's reviewed stock hash).
- `/opt/etc/parseinfo.sh`:
  `c6369e7dec69408e176daa252d436acf6f8e265f560504d8bd831c8023c71d61`
  (matches Couchroot's expected hash).
- `oneservice`:
  `60a17f7bf53a5c0be1d4b4fb0f17c3415d0480b73901e91ff139b5aca550dbce`;
  `.table`:
  `cfbee9145724c7258a4a4895d54cb418372a71db4d6a49b61299f6726d400840`.
  These differ from the reviewed `T-PTMDAKUC` bytes
  (`3ffa26a6...` / `afba7a1d...`), but the first unit is the same 209-byte
  AT-HUB unit. The patched cache generated from this TV is
  `d8c2d011fe485f8b5076a2e80316d233508235e0ef7dfbb1080768c2f130f309`.
- Stock ContentList:
  `23b0564a366e09fcba9592449d7fc8124480732980f9f6300daa60ee4ef08466`
  (86 bytes, CRLF); custom:
  `e802155cd726aae2a32a137d7820d716c7265d22e5ebf641878e5d716ea5f430`
  (70 bytes). The helper checks both.
- After a normal reboot, `/opt/minimal-saver/last-boot.log` shows
  `active: read-only ContentList overlay`; the foreground app was
  `KurumiSvr1.Saver`; the on-disk stock saver was not modified. The on-demand
  `archive-launcher` root route used for the original setup is not needed at
  boot; the helper itself runs via AT-HUB, exits, and no root agent remains.

## Trade-offs and limits

- Avoids the ARMv7-softfp GLES2 cross-compile and the native ABI
  reverse-engineering. The cost is web-runtime performance and a signed web app
  instead of a native renderer.
- **OLED burn-in:** the idle launcher hands off the idle path but does not itself
  enforce burn-in protection. The web content owns that policy. This route's
  saver keeps the background black, has no static text/logo in normal operation,
  moves the subject continuously, fades to black during the final minute, and
  stops at 10 minutes (`MAX_MS`/`FADE_MS` in the app's `js/saver.js`; see
  `saver/README.md`). The 10-minute deadline is a conservative project policy,
  not a Samsung-specified safe duration.
- Tested only on the model/firmware above. The `oneservice` patch and the
  ContentList hashes are per-firmware; a different regional build must regenerate
  them from the TV and revalidate the helper. This is not a supported profile and
  is not folded into the installer/profile guards.

## Credit

Independent implementation:
<https://github.com/IgorRichard13/kurumi-s90d-toolkit> (MIT). Relevant paths:
`saver/`, `tools/boot-hook/`, `tools/boot_prepare.py`,
`tools/boot_install.py`. The toolkit credits Couchroot (0BSD) for the S90D
research and `samsung-tv-root` (Unlicense) for the archive route. No firmware,
vendor binaries, keys, device identifiers, addresses or raw logs are included.
