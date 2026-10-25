# SDB pull-only inventory

Some Samsung TV builds accept SDB file transfer but close `sdb shell` command
execution. The TV still exposes enough read-only files to inventory installed
packages, the app catalog, firmware identity and service units. This guide
records the method used on a `QN65QN90AAGXZD` running `T-NKM2UABC-2301.1` and
`T-NKM2UABC-2310.0`; it applies to any target whose SDB daemon behaves the same.

This is a read-only procedure. It does not install, uninstall, root or change
any TV setting.

## Preconditions

- Developer Mode is enabled and the TV has been rebooted.
- The host can reach TCP 26101.
- `sdb devices` lists the target as `device`.
- You own or administer the TV.

All example addresses use the reserved `192.0.2.9`. Replace it with your TV's
address.

```sh
sdb connect 192.0.2.9:26101
sdb devices
```

If `sdb shell id` returns nothing while `sdb pull` succeeds, this method is the
right one. Do not repeat shell or `appinstall` probes merely to make shell work;
some daemons never expose it.

## Pull the useful files

Choose a private directory outside the checkout. The example uses
`/private/tv-inventory`; keep it out of Git.

```sh
mkdir -p /private/tv-inventory
sdb -s 192.0.2.9:26101 pull /etc/prd_info.ini /private/tv-inventory/
sdb -s 192.0.2.9:26101 pull /opt/dbspace/.pkgmgr_parser.db /private/tv-inventory/
sdb -s 192.0.2.9:26101 pull /opt/dbspace/.webappservice.db /private/tv-inventory/
sdb -s 192.0.2.9:26101 pull /lib/systemd/system/adagent-service.service /private/tv-inventory/
```

Directory pulls are inconsistent on these daemons: a directory may return zero
files while an individual unit file pulls normally. Prefer known unit paths and
treat a failed pull as unreadable, not absent.

Other files that are usually readable and useful:

- `/lib/systemd/system/*.service` — vendor unit definitions and conditions.
- `/usr/sbin/sdbd-tarlauncher`, `/usr/bin/dotnet`, `/usr/share/sdbd/public.pem`
  — hash them; do not execute them.
- `/usr/share/sdbd` — daemon directory; only `public.pem` was readable on the
  tested build.

Permission failures are expected for some databases and directories. Record
them as unreadable, not absent.

## Query the databases locally

The package database is SQLite. Open the copy read-only; never write to a pulled
database.

```sql
-- package count by type
select package_type, count(*) from package_info group by package_type;

-- visible, non-system app registrations
select a.app_id, p.package, p.package_version, p.package_system,
       p.package_removable, p.package_preload, p.package_readonly
from package_app_info a
join package_info p on p.package = a.package
where a.app_nodisplay = 'false' and p.package_system = 'false';

-- Samsung app catalog
select id, title, tizen_id, pkgname, version, is_removable, is_system,
       is_lock, install_state, is_app_available
from widgetinfo;
```

`package_info` carries `package_type`, `package_version`, `package_system`,
`package_removable`, `package_preload`, `package_readonly`, `mainapp_id` and
`root_path`. `package_app_info` carries `app_id`, `app_nodisplay`, `app_type` and
`app_onboot`. `widgetinfo` carries the store id, title, Tizen id and install
state.

If the database was copied while the TV was running, its file hash may differ
between two pulls even when no package changed: SQLite rewrites pages and
journals during normal operation. Compare rows, not file hashes. A journal file
next to the database is normal.

## Hash files without executing them

```sh
sha256sum /private/tv-inventory/sdbd-tarlauncher \
          /private/tv-inventory/dotnet \
          /private/tv-inventory/public.pem \
          /private/tv-inventory/prd_info.ini
```

Hashes are safe to publish. Raw databases, unit dumps, firmware images and
backups are not.

## Keep the evidence sanitized

- Replace the TV address with a reserved address such as `192.0.2.9`.
- Remove DUID, UDN, serial numbers, MAC addresses, SSIDs and account data.
- Do not commit `.db`, `.sqlite`, `.zip`, `.tar.gz`, `.pem` or signed packages.
- State whether a change was read-only, a local test, or an owner-authorized
  mutation.
- Keep the original checkout and the private evidence directory until any
  recovery window has closed.

The resulting sanitized inventory can follow the shape used by
[`docs/lab/inventory/`](../lab/inventory/). A worked example, including the root
and debloat results that followed this inventory, is in
[the Brazil QN90A record](../lab/devices/qn90a/br-t-nkm2uabc.md).
