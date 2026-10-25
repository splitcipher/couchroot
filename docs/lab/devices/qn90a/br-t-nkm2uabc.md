# QN90A Brazil: root, suppression and cleanup evidence

Target: `QN65QN90AAGXZD` (Brazil), platform `21_NIKEM2_QTV`, firmware
`T-NKM2UABC-2301.1`, later updated to `T-NKM2UABC-2310.0`. One owner-authorized
TV. The address is shown as the reserved `192.0.2.9`; no device, account or
network identifiers are included.

This is a lab record, not a supported installation path. The reviewed profiles
cover `QN85QN90AAFXZA` / `T-NKM2AKUC-2301.1` and `QN55S90DAFXZA`. The platform
matches the QN90A profile, but the model and regional firmware do not. No profile
was added and no guard was weakened. All mutations were made by the owner after
read-only inspection.

## Identity and transport

| Field | Observed |
| --- | --- |
| Model | `QN65QN90AAGXZD` |
| Platform | `21_NIKEM2_QTV` |
| Firmware before update | `T-NKM2UABC-2301.1` |
| Firmware after update | `T-NKM2UABC-2310.0`, build `TIZEN-TRUNK2021-NikeM2-HOTFIX-RELEASE_20260721.1` |
| Architecture | `armv7l` |
| Runtime | `netcoreapp3.1` |

The four files pinned by the QN90A root path match the reviewed values on this
TV:

| File | SHA-256 |
| --- | --- |
| `/usr/sbin/sdbd-tarlauncher` | `3580e6dc…69a653` |
| `/usr/bin/dotnet` | `d2a35114…0702e` |
| `/usr/share/sdbd/public.pem` | `c83cab64…9d09` |
| `/etc/passwd` | `610fe330…ffad` |

SDB on this build accepts file transfer and capability queries but returns no
output for `sdb shell` commands, including `id`, `uname` and `dlog`. That is a
property of this daemon, not of the client: sdb 4.1.8, 4.2.25 and 4.2.36 behave
the same. The upstream archive-root route does not use plain shell; it sends the
internal `0 appinstall tpk` command. A timing probe showed that path executes:

| Injection command | Elapsed |
| --- | ---: |
| `/bin/true` | 0.25 s |
| `/bin/sleep 3` | 3.09 s |

A failed injection can leave `sdbd` unresponsive for about 60 seconds while the
port stays open. It recovered without a reboot in two observed cases. The full
pull-only inventory method is in
[SDB pull-only inventory](../../../guides/sdb-pull-inventory.md).

## Root result

The public `samsung-tv-root` v0.0.12 Windows release was used unmodified with
`archive-root probe`. It has no model whitelist and checks the SDB foothold,
capabilities and installed runtime before staging its payload. The probe
authenticated as root:

```json
{
  "authenticated": true,
  "uid": 0,
  "euid": 0,
  "gid": 0,
  "egid": 0,
  "cap_effective": "0000003fffffffff",
  "runtime": "3.1",
  "smack": "User",
  "staging_cleaned": true,
  "system_files_unchanged": true
}
```

A second root session after a reboot returned `uid=0(owner) gid=0(root)`. Root
is volatile: it ends with the session and is not installed as a service. The
host-side failures that preceded the successful probe were all transport issues
(wrong callback address, Public firewall profile, OpenSSL not on PATH), not TV
rejections.

## Suppression markers

Two empty files were created as root, matching the vendor conditions used by the
existing [startup-disable tests](startup-disable-tests.md):

| Path | Size | Mode | Before |
| --- | ---: | --- | --- |
| `/opt/usr/share/systemd/system/pisa-service` | 0 | 0666 | absent |
| `/opt/usr/share/systemd/system/canalysis-daemon` | 0 | 0666 | absent |

The vendor units contain:

```text
ConditionPathExists=!/opt/usr/share/systemd/system/pisa-service
ConditionPathExists=!/opt/usr/share/systemd/system/canalysis-daemon
```

After the reboot, a further root session reported:

| Unit | Active | Sub | Condition |
| --- | --- | --- | --- |
| `adagent-service` | inactive | dead | `no` |
| `pisa-service` | inactive | dead | `no` |
| `canalysis-service` | inactive | dead | `no` |
| `contents-recognition-service` | active | running | `yes` |

`ps` found no adagent, pisa or canalysis processes. Rollback is `rm -f` of the
two files, which requires another temporary root session. The files are not a
persistent root service and do not change firmware or security policy.

## Hidden Ad Player removal

`adplatform.ADPlayer` (package `adplatform`, version `0.10.96`, store id
`3201503001519`) is a hidden web app. Its package record has
`package_system=false`, `package_preload=false`, `package_readonly=false`,
`package_removable=true` and no declared incoming dependency. The installed
directory is `/opt/usr/apps/adplatform`.

The owner authorized removal. The directory was archived first
(`adplatform-backup.tar.gz`, SHA-256 `9410df7b…d0c17`) and copied off the TV.
The package was then removed with `pkgcmd -u -n adplatform`, which reported
`key[end] val[ok]` in about one second. The package count changed from 342 to
341, the package and app rows disappeared, and the install directory was gone.

`pkgcmd` left one stale `widgetinfo` catalog row. It was not hand-edited. The
later 2310.0 update reconciled it, and the catalog dropped from 37 to 36 entries
with no Ad Player row.

## Firmware update to 2310.0

The TV updated itself from `T-NKM2UABC-2301.1` to `T-NKM2UABC-2310.0` while
online. Post-update checks found:

- both markers present with their original timestamps;
- the three units still inactive with `ConditionResult=no`;
- no matching processes;
- the Ad Player package still absent;
- the stale catalog row gone;
- `sdbd-tarlauncher`, `dotnet`, `public.pem` and `/etc/passwd` hashes unchanged;
- `archive-root probe` still authenticating as root;
- `contents-recognition-service` still active with a live process.

This is one OTA on one TV. It does not establish that future updates preserve
the markers or the root chain.

A separate US QN90A 2310.0 agent qualification is recorded in
[firmware-2310-agent-trial.md](firmware-2310-agent-trial.md). It covers a
different model and firmware string and does not admit this Brazilian variant.

## Limitations

- One owner-authorized TV; no second unit of this model or firmware.
- Root is volatile; only the marker files and the package removal persist.
- The USB recovery image was downloaded and hash-verified but recovery was not
  executed.
- No physical remote, playback, standby or panel verification was performed.
- The TV updated firmware during the experiment; pre- and post-update results
  are recorded separately.
- `contents-recognition-service` remains active; no vendor condition marker was
  found for it.
- `pkgcmd` was used instead of the reviewed WAS helper. The stale catalog row was
  reconciled by the OTA, not by a supported cleanup path.
- The model and firmware are not in the reviewed profile registry. This record
  does not add support or justify copying any setting to another TV.

## Evidence

- [Sanitized root and debloat inventory](../../inventory/qn90a-br-root-20261024.json)
- [QN90A optional-app cleanup](app-cleanup.md)
- [QN90A startup-disable comparisons](startup-disable-tests.md)
- [QN90A viewer suppression trial](suppression-trial.md)
- [Device compatibility](../../../guides/device-compatibility.md)
- [Porting to a new TV or firmware](../../../guides/porting-to-a-new-tv.md)

Raw databases, backups, firmware images and device identifiers remain outside
this repository.
