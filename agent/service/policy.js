'use strict';
const fs = require('fs'),
  path = require('path'),
  crypto = require('crypto');
const hash = (data) => crypto.createHash('sha256').update(data).digest('hex');
function read(file, limit = 65536) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > limit)
    throw Error('Invalid configuration file');
  return fs.readFileSync(file);
}
// Optional request-local sync accounting. The same synchronous durability barrier
// runs exactly once; even a thrown sync is timed without changing its outcome.
function sync(fd, timing, kind) {
  if (!timing) return fs.fsyncSync(fd);
  const start = process.hrtime();
  try {
    return fs.fsyncSync(fd);
  } finally {
    const d = process.hrtime(start),
      v = timing[kind] || (timing[kind] = { ms: 0, calls: 0 });
    v.ms += d[0] * 1000 + d[1] / 1e6;
    v.calls++;
  }
}
function atomic(file, value, timing) {
  const tmp = file + '.new-' + crypto.randomBytes(8).toString('hex');
  const fd = fs.openSync(tmp, 'wx', 0o600);
  try {
    fs.writeFileSync(fd, JSON.stringify(value));
    sync(fd, timing, 'file_sync');
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, file);
  const parent = fs.openSync(path.dirname(file), 'r');
  try {
    sync(parent, timing, 'directory_sync');
  } finally {
    fs.closeSync(parent);
  }
}
function config(data) {
  if (
    data &&
    data.service_acquisition !== undefined &&
    data.service_acquisition !== 'native'
  )
    throw Error('Invalid service acquisition selection');
  if (
    data &&
    data.boot_launcher !== undefined &&
    (typeof data.boot_launcher !== 'boolean' ||
      (data.boot_launcher && data.device !== 'qn90a'))
  )
    throw Error('Boot launcher is QN90A-only');
  if (
    !data ||
    data.schema !== 1 ||
    !['qn90a', 's90d'].includes(data.device) ||
    typeof data.enabled !== 'boolean' ||
    !Number.isInteger(data.port) ||
    data.port < 1024 ||
    data.port > 65535
  )
    throw Error('Invalid agent configuration');
  if (
    !/^[a-f0-9]{64}$/.test(data.client_sha256) ||
    !data.firmware ||
    !data.hashes ||
    !Object.keys(data.hashes).length
  )
    throw Error('Missing identity guards');
  for (const p of Object.keys(data.hashes))
    if (
      ![
        '/usr/bin/dotnet',
        '/usr/bin/dotnet-launcher',
        '/usr/sbin/sdbd-tarlauncher',
      ].includes(p) ||
      !/^[a-f0-9]{64}$/.test(data.hashes[p])
    )
      throw Error('Invalid firmware guard');
  if (
    !data.hashes['/usr/bin/dotnet'] ||
    !data.hashes['/usr/sbin/sdbd-tarlauncher']
  )
    throw Error('Missing launcher guards');
  return data;
}
function verifyFirmware(c) {
  const lines = read('/etc/prd_info.ini').toString().split(/\r?\n/),
    expected = 'Version=' + c.firmware + ';';
  if (!lines.includes(expected)) {
    // Preserve the exact guard; JSON quoting exposes whitespace and controls.
    // Report only version lines, never the rest of the device identity file.
    const observed = lines.filter((line) => /^\s*Version\s*=/i.test(line));
    const message =
      'Firmware mismatch in /etc/prd_info.ini: expected ' +
      JSON.stringify(expected) +
      '; observed ' +
      JSON.stringify(observed);
    throw Error(
      message.length <= 256 ? message : message.slice(0, 240) + ' [truncated]'
    );
  }
}
function sdkRuntimeGuard(c) {
  config(c);
  // Some TV package labels cannot stat System::Tools. Check the same pinned
  // bytes as SDK, before executing dotnet or the archive launcher; never skip it.
  return (
    Object.keys(c.hashes)
      .sort()
      .map(
        (p) =>
          'test "$(sha256sum \'' +
          p +
          "' | cut -d ' ' -f 1)\" = '" +
          c.hashes[p] +
          "' || { echo 'Runtime hash mismatch: " +
          p +
          "'; exit 74; }"
      )
      .join('\n') + '\n'
  );
}
function validateRequest(v) {
  if (
    !v ||
    Object.keys(v).some((k) => !['id', 'command', 'timeout_ms'].includes(k)) ||
    !/^[-a-zA-Z0-9]{16,64}$/.test(v.id) ||
    typeof v.command !== 'string' ||
    !v.command.trim() ||
    Buffer.byteLength(v.command) > 16384 ||
    v.command.includes('\0') ||
    !Number.isInteger(v.timeout_ms) ||
    v.timeout_ms < 100 ||
    v.timeout_ms > 25000
  )
    throw Error('Invalid command request');
  return v;
}
class Journal {
  constructor(file) {
    this.file = file;
    this.archiveDir = file + '.archives';
    this.failed = false;
    this.seen = new Map();
    this.rows = this.present(file) ? JSON.parse(read(file, 262144)) : [];
    this.validate(this.rows);
    // Also retain replay protection for archives made by the earlier SDK maintenance workflow.
    const parent = path.dirname(file),
      prefix = path.basename(file, '.json') + '.archive-';
    for (const name of fs.readdirSync(parent))
      if (name.startsWith(prefix) && name.endsWith('.json'))
        this.remember(JSON.parse(read(path.join(parent, name), 262144)));
    if (this.present(this.archiveDir)) {
      this.checkArchiveDir();
      for (const name of fs.readdirSync(this.archiveDir)) {
        if (/^[a-f0-9]{64}\.json\.new-[a-f0-9]{16}$/.test(name)) continue; // interrupted pre-rename write; active journal remains authoritative
        if (!/^[a-f0-9]{64}\.json$/.test(name))
          throw Error('Unexpected journal archive file');
        const bytes = read(path.join(this.archiveDir, name), 262144);
        if (hash(bytes) !== name.slice(0, 64))
          throw Error('Journal archive hash mismatch');
        this.remember(JSON.parse(bytes));
      }
    }
    this.remember(this.rows);
  }
  validate(rows) {
    if (!Array.isArray(rows) || rows.length > 1000)
      throw Error('Invalid command journal');
    const ids = new Set();
    for (const r of rows) {
      if (
        !r ||
        !/^[-a-zA-Z0-9]{16,64}$/.test(r.id) ||
        !/^[a-f0-9]{64}$/.test(r.sha256) ||
        !['submitted', 'completed'].includes(r.state) ||
        !Number.isFinite(r.at) ||
        ids.has(r.id)
      )
        throw Error('Invalid command journal entry');
      ids.add(r.id);
    }
  }
  remember(rows) {
    this.validate(rows);
    for (const r of rows) {
      if (this.seen.has(r.id) && this.seen.get(r.id) !== r.sha256)
        throw Error('Conflicting archived request');
      this.seen.set(r.id, r.sha256);
    }
  }
  present(file) {
    try {
      fs.lstatSync(file);
      return true;
    } catch (e) {
      if (e.code === 'ENOENT') return false;
      throw e;
    }
  }
  checkArchiveDir() {
    const s = fs.lstatSync(this.archiveDir);
    if (!s.isDirectory() || s.isSymbolicLink())
      throw Error('Invalid journal archive directory');
  }
  digest() {
    return hash(JSON.stringify(this.rows));
  }
  save(rows, timing) {
    try {
      atomic(this.file, rows, timing);
      this.rows = rows;
    } catch (e) {
      this.failed = true;
      throw e;
    }
  }
  archive(expected, timing) {
    if (this.failed)
      throw Error('Journal storage failed; restart after diagnosis');
    if (expected !== undefined && expected !== this.digest())
      throw Error('Journal changed; inspect before archiving');
    const completed = this.rows.filter((r) => r.state === 'completed'),
      recent = new Set(completed.slice(-100).map((r) => r.id));
    const retained = this.rows.filter(
      (r) => r.state !== 'completed' || recent.has(r.id)
    );
    if (retained.length === this.rows.length)
      return {
        archived_entries: 0,
        retained_entries: this.rows.length,
        sha256: this.digest(),
      };
    const bytes = Buffer.from(JSON.stringify(this.rows)),
      digest = hash(bytes),
      destination = path.join(this.archiveDir, digest + '.json');
    try {
      try {
        fs.mkdirSync(this.archiveDir, 0o700);
      } catch (e) {
        if (e.code !== 'EEXIST') throw e;
      }
      this.checkArchiveDir();
      if (this.present(destination)) {
        if (!read(destination, 262144).equals(bytes))
          throw Error('Journal archive conflict');
      } else atomic(destination, this.rows, timing);
      // Commit the complete immutable archive before reducing the active file.
      const parent = fs.openSync(path.dirname(this.archiveDir), 'r');
      try {
        sync(parent, timing, 'directory_sync');
      } finally {
        fs.closeSync(parent);
      }
      if (!read(destination, 262144).equals(bytes))
        throw Error('Journal archive verification failed');
      const removed = this.rows.length - retained.length;
      this.save(retained, timing);
      return {
        archived_entries: removed,
        retained_entries: retained.length,
        archive_sha256: digest,
        sha256: this.digest(),
      };
    } catch (e) {
      this.failed = true;
      throw e;
    }
  }
  begin(v, timing) {
    validateRequest(v);
    if (this.failed)
      throw Error('Journal storage failed; restart after diagnosis');
    if (this.seen.has(v.id))
      throw Error('Request already submitted; inspect outcome, do not replay');
    if (this.rows.length >= 1000) this.archive(undefined, timing);
    if (this.rows.length >= 1000)
      throw Error(
        'Command journal full of unfinished requests; inspect outcomes'
      );
    this.save(
      this.rows.concat([
        {
          id: v.id,
          sha256: hash(v.command),
          state: 'submitted',
          at: Date.now(),
        },
      ]),
      timing
    );
    this.seen.set(v.id, hash(v.command));
  }
  finish(id, result, timing) {
    if (this.failed)
      throw Error('Journal storage failed; restart after diagnosis');
    if (!this.rows.some((r) => r.id === id && r.state === 'submitted'))
      throw Error('Unknown pending request');
    this.save(
      this.rows.map((r) =>
        r.id === id
          ? Object.assign({}, r, {
              state: 'completed',
              exit_code: result.exit_code,
              timed_out: result.timed_out,
            })
          : r
      ),
      timing
    );
  }
}
module.exports = {
  read,
  atomic,
  hash,
  config,
  verifyFirmware,
  sdkRuntimeGuard,
  validateRequest,
  Journal,
};

// Optional QN90A-only, once-per-boot handoff. This does not select a source mode.
// Commands are fixed and encoded to preserve shell bytes through the old worker.
const CLAIM = '/tmp/minimal-root-hub-boot';
function wire(script) {
  return (
    'printf %s ' +
    Buffer.from(script).toString('base64') +
    ' | base64 -d | /bin/sh'
  );
}
function script(action) {
  const head =
    "set -eu\ngrep -qx 'Version=T-NKM2AKUC-2301.1;' /etc/prd_info.ini\n";
  if (action === 'inspect')
    return (
      head +
      'u=$(cut -d . -f 1 /proc/uptime); echo UPTIME:$u\nvconftool get memory/appfw/current_fullscreen_appid\nif test -e ' +
      CLAIM +
      '; then echo CLAIMED; fi\n'
    );
  if (action !== 'launch') throw Error('Unknown boot action');
  return (
    head +
    'test "$(cut -d . -f 1 /proc/uptime)" -le 110\n' +
    'f=$(vconftool get memory/appfw/current_fullscreen_appid)\ncase "$f" in\n' +
    "'memory/appfw/current_fullscreen_appid, value =  (String)'|'memory/appfw/current_fullscreen_appid, value = org.tizen.tv-viewer (String)'|'memory/appfw/current_fullscreen_appid, value = com.samsung.tv.csfs (String)') ;;\n*) exit 73;;\nesac\n" +
    'umask 077\nmkdir ' +
    CLAIM +
    '\napp_launcher -s MiniHubBoot.Start -u 5001\n'
  );
}
function createBootLaunch(agent, enabled) {
  let state = enabled ? 'waiting-agent' : 'disabled',
    busy = false,
    started = false;
  async function tick() {
    if (
      busy ||
      !enabled ||
      !['waiting-agent', 'waiting-foreground'].includes(state)
    )
      return;
    const readiness = agent.status();
    if (!readiness.connected || readiness.worker_ready === false) return;
    busy = true;
    try {
      const r = await agent.execute(wire(script('inspect')), 5000);
      if (r.timed_out || r.exit_code !== 0) throw Error('Inspection failed');
      const text = r.stdout === undefined ? r.output : r.stdout;
      if (typeof text !== 'string') throw Error('Missing inspection output');
      const up = /^UPTIME:(\d+)$/m.exec(text);
      const fg =
        /^memory\/appfw\/current_fullscreen_appid, value = (.*) \(String\)$/m.exec(
          text
        );
      if (!up || !fg) throw Error('Incomplete inspection');
      if (fg[1] === 'MiniHub001.Hub') {
        state = 'foreground-confirmed';
        return;
      }
      if (Number(up[1]) > 110) {
        state = 'deadline';
        return;
      }
      if (!['', 'org.tizen.tv-viewer', 'com.samsung.tv.csfs'].includes(fg[1])) {
        state = 'other-app';
        return;
      }
      if (started) return;
      if (/^CLAIMED$/m.test(text)) {
        state = 'previous-attempt';
        return;
      }
      // Record local intent BEFORE submission. A lost response never replays.
      started = true;
      state = 'submitting';
      const result = await agent.execute(wire(script('launch')), 12000);
      state =
        result.exit_code === 0 && !result.timed_out
          ? 'waiting-foreground'
          : 'launch-unconfirmed';
    } catch (_) {
      state = started ? 'launch-uncertain' : 'inspection-failed';
    } finally {
      busy = false;
    }
  }
  return { tick, status: () => state };
}
Object.assign(module.exports, {
  createBootLaunch,
  bootScript: script,
  bootWire: wire,
});
