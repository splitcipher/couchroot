"""Fresh, read-only evidence for the one owned administration service.

This is registration evidence, not process health or unattended boot acceptance.
The generic two-column application inventory intentionally remains unchanged.
"""

import shlex
from .transport import PKG_DB

PACKAGE = "MiniRoot01"
SERVICE = PACKAGE + ".Service"
COLUMNS = ("app_id", "package", "app_component", "app_disable", "app_onboot", "app_autorestart")
FIELDS = (*COLUMNS, "package_disable")


def row_sql():
    columns = ["a." + c for c in COLUMNS] + ["p.package_disable"]
    # Preserve SQLite types as well as NULL; never coerce an unfamiliar flag.
    expressions = [f"typeof({c}),CASE WHEN {c} IS NULL THEN '-' ELSE hex({c}) END" for c in columns]
    return (
        "SELECT " + ",".join(expressions)
        + " FROM package_app_info a JOIN package_info p ON p.package=a.package"
        + f" WHERE a.app_id='{SERVICE}' AND a.package='{PACKAGE}' LIMIT 3;"
    )


def capture_command():
    q = shlex.quote
    schema = (
        "SELECT count(*) FROM pragma_table_info('package_app_info') WHERE name IN ("
        + ",".join("'" + c + "'" for c in COLUMNS) + ");"
        + "SELECT count(*) FROM pragma_table_info('package_info') WHERE name IN ('package','package_disable');"
    )
    return (
        f"if schema=$(sqlite3 -readonly {q(PKG_DB)} {q(schema)} 2>/dev/null); then\n"
        f"if test \"$schema\" = {q('6' + chr(10) + '2')}; then\n"
        f"if rows=$(sqlite3 -readonly -separator '|' {q(PKG_DB)} {q(row_sql())} 2>/dev/null); then\n"
        "printf 'OK\\n%s\\n' \"$rows\"\nelse echo READ_ERROR; fi\n"
        "else echo UNSUPPORTED_SCHEMA; fi\nelse echo READ_ERROR; fi"
    )


def _flag(value):
    if value == {"type": "text", "value": "true"}:
        return True
    if value == {"type": "text", "value": "false"}:
        return False
    return None


def parse_capture(text):
    result = dict(schema=1, package=PACKAGE, service=SERVICE, capture="unknown",
                  status="unknown", reason="incomplete_capture", row=None,
                  worker_ready="not_observed", new_boot_ready="not_observed")
    lines = text.strip().splitlines()
    if lines == ["READ_ERROR"] or lines == ["UNSUPPORTED_SCHEMA"]:
        result.update(capture="error", reason=lines[0].lower())
        return result
    if not lines or lines[0] != "OK":
        return result
    result["capture"] = "observed"
    if len(lines) != 2:
        result["reason"] = "missing_row" if len(lines) == 1 else "duplicate_rows"
        return result
    parts = lines[1].split("|")
    if len(parts) != 2 * len(FIELDS):
        result["reason"] = "malformed_row"
        return result
    row = {}
    try:
        for i, field in enumerate(FIELDS):
            kind, raw = parts[2*i:2*i+2]
            if kind not in ("null", "text", "integer", "real", "blob") or (kind == "null" and raw != "-"):
                raise ValueError()
            value = None if kind == "null" else bytes.fromhex(raw).decode("utf-8")
            row[field] = {"type": kind, "value": value}
    except (ValueError, UnicodeError):
        result["reason"] = "malformed_row"
        return result
    # Do not export unexpected strings or identifiers from an untrusted row.
    if row["app_id"] != {"type": "text", "value": SERVICE} or row["package"] != {"type": "text", "value": PACKAGE}:
        result["reason"] = "identity_mismatch"
        return result
    if row["app_component"] != {"type": "text", "value": "svcapp"}:
        result["reason"] = "component_mismatch"
        return result
    safe_row = {k: v if v["value"] in (None, "true", "false") else {"type": v["type"], "value": "[unrecognized]"}
                for k, v in row.items() if k not in ("app_id", "package", "app_component")}
    result["row"] = safe_row
    disabled = [_flag(row[k]) for k in ("app_disable", "package_disable")]
    flags = [_flag(row[k]) for k in ("app_onboot", "app_autorestart")]
    if True in disabled:
        result.update(status="disabled", reason="registration_disabled")
    elif None in disabled or None in flags:
        result["reason"] = "unknown_flags"
    elif flags != [True, True]:
        result.update(status="disabled", reason="startup_flags_disabled")
    else:
        result.update(status="expected", reason="expected_startup_flags")
    return result
