'use strict';
const fs = require('fs'),
  path = require('path'),
  crypto = require('crypto');
const sdb = require('./vendor/sdb'),
  { tarGz } = require('./vendor/tar'),
  { RootAgentServer } = require('./root-agent');
const {
  read,
  hash,
  atomic,
  verifyFirmware,
  sdkRuntimeGuard,
} = require('./policy');
const { candidateStatus } = require('./native-candidate');
const { selectionStatus, nativeCommit } = require('./worker-selection');
const {
  reviewUpgrade,
  upgradeStatus,
  runUpgrade,
} = require('./native-upgrade');
const { recoveryPlan, recoverUpgrade } = require('./native-upgrade-recovery');
const { inventoryRestart } = require('./restart-inventory');
const { startupCandidate, startSelectedNative } = require('./native-startup');
const { loadAcquisition, stageAcquisition } = require('./service-acquisition');
const {
  prepareBootstrap,
  validateBootstrap,
  bindBootstrap,
  retireBootstrap,
} = require('./held-bootstrap');
const {
  recoveryCandidate,
  recoveryCommand,
  completeAcquisitionRecovery,
} = require('./bootstrap-recovery');
const BASE = '/home/owner/share/tmp/sdk_tools';
const quote = (s) => "'" + s.replace(/'/g, "'\\''") + "'";
function launchRequest(stage, gate) {
  const script =
    'mkdir ' +
    quote(gate) +
    ' 2>/dev/null && { . ' +
    quote(stage + '/launch-sdk.sh') +
    '; }';
  const encoded = Buffer.from(script).toString('base64');
  const request =
    'shell:0 appinstall tpk new2.tpk`printf${IFS}%s${IFS}' +
    encoded +
    '|base64${IFS}-d|bash`.tpk';
  if (Buffer.byteLength(request) > 510)
    throw Error('SDK launch command exceeds safe transport limit');
  return request;
}
async function launchSdk(client, stage, gate, privateLog) {
  // The app writes SDK diagnostics itself; SDK UID 901 needs no log-file access.
  if (privateLog)
    fs.writeFileSync(stage + '/launcher.log', '', { mode: 0o600, flag: 'wx' });
  const output = await sdb.exec(client, launchRequest(stage, gate), {
    timeout: 30000,
  });
  if (privateLog) fs.appendFileSync(stage + '/launcher.log', output || '');
  return output;
}
function createAgent(config, options = {}) {
  let running = false,
    connected = false,
    launching = false,
    timer = null,
    channel = null,
    client = null,
    stage = null,
    attempts = 0,
    generation = 0,
    lastError = null,
    lastAcquisitionError = null,
    identity = null,
    lastAcquired = null,
    workerReady = false,
    workerStatus = null,
    workerStatusAt = 0;
  const firmware = options.verifyFirmware || verifyFirmware;
  const currentBoot =
    options.readBootId ||
    (() => read('/proc/sys/kernel/random/boot_id', 128).toString().trim());
  const payload = options.payload || path.join(__dirname, '../payload');
  let nativeCandidate = candidateStatus(payload, config.device);
  let acquisitionMode = null;
  let nativeRuntime = null,
    nativeStartup = null,
    bootstrapRecovery = null;
  const inFlight = new Set();
  const upgradeChannels = new Set();
  let upgradeHeld = false,
    upgradeRecovery = false;
  function selection() {
    if (!options.selectionFile)
      return {
        phase: 'inspection-required',
        launch_allowed: false,
        reason: 'native-enrollment-required',
      };
    return selectionStatus(options.selectionFile);
  }
  function runtimeAllowed(selected) {
    const h = nativeCommit(selected);
    return !!(
      nativeRuntime &&
      running &&
      connected &&
      workerReady &&
      generation === nativeRuntime.generation &&
      channel === nativeRuntime.channel &&
      JSON.stringify(selected) === nativeRuntime.selection &&
      selected.phase === 'stable' &&
      selected.selected_implementation === 'native-prototype' &&
      selected.selected_manifest_sha256 ===
        nativeRuntime.record.manifest_sha256 &&
      h &&
      h.id === nativeRuntime.record.id &&
      h.outcome === 'committed' &&
      h.readiness_sha256 === nativeRuntime.activation.readiness_sha256
    );
  }
  function diagnostics() {
    const out = {};
    if (stage)
      for (const n of ['launcher.log', 'root-agent.status', 'root-agent.log']) {
        try {
          out[n] = read(stage + '/' + n, 65536)
            .toString()
            .slice(-2048);
        } catch (_) {}
      }
    return out;
  }
  function status() {
    const selected = selection();
    let upgrade = null;
    try {
      const pending =
        options.selectionFile && upgradeStatus(options.selectionFile);
      upgrade = pending ? pending.record.phase : null;
    } catch (_) {
      upgrade = 'inspection-required';
    }
    let boot = null,
      uptime = null;
    try {
      boot = fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim();
      uptime = Number(fs.readFileSync('/proc/uptime', 'utf8').split(' ')[0]);
    } catch (_) {}
    if (workerStatus) {
      boot = workerStatus.boot_id;
      uptime = workerStatus.uptime_seconds + process.uptime() - workerStatusAt;
    }
    return {
      schema: 2,
      native_upgrade: upgrade,
      root_acquisition: acquisitionMode,
      native_runtime:
        nativeRuntime && runtimeAllowed(selected)
          ? {
              transaction_id: nativeRuntime.record.id,
              manifest_sha256: nativeRuntime.record.manifest_sha256,
              activation_sha256: nativeRuntime.activation.receipt_sha256,
            }
          : null,
      admission_held: restartHeld(),
      in_flight_requests: inFlight.size,
      selected_implementation: selected.selected_implementation || null,
      worker_selection: selected,
      native_candidate: nativeCandidate,
      boot_id: boot,
      uptime_seconds: uptime,
      worker_ready: workerReady && runtimeAllowed(selected) && !restartHeld(),
      worker_id: workerStatus && workerStatus.worker_id,
      capabilities: workerStatus ? workerStatus.capabilities : [],
      last_root_acquired_at: lastAcquired,
      device: config.device,
      enabled: running,
      connected,
      phase:
        restartHeld() && connected
          ? 'reconciling'
          : !runtimeAllowed(selected) && !selected.launch_allowed
            ? 'selection-required'
            : workerReady
              ? 'ready'
              : connected
                ? 'checking'
                : launching
                  ? 'acquiring'
                  : running
                    ? 'waiting'
                    : 'disabled',
      attempts,
      last_error: lastError,
      last_acquisition_error: lastAcquisitionError,
      identity,
      diagnostics: diagnostics(),
    };
  }
  function clean() {
    if (!stage) return;
    // Do not remove other tools' staging directories or recursively delete unknown files.
    if (
      fs.existsSync(stage + '/code') &&
      fs.lstatSync(stage + '/code').isDirectory() &&
      !fs.lstatSync(stage + '/code').isSymbolicLink()
    ) {
      for (const n of [
        'libacquire.so',
        'native-worker',
        'native-app-launcher',
      ]) {
        const p = stage + '/code/' + n;
        if (fs.existsSync(p) && fs.lstatSync(p).isFile()) fs.unlinkSync(p);
      }
      try {
        fs.rmdirSync(stage + '/code');
      } catch (_) {}
    }
    for (const n of fs.readdirSync(stage)) {
      if (
        !/^(SamsungTv(RootAgent|ArchiveRoot)\.(dll|runtimeconfig\.json|deps\.json)|NativeEntry\.(dll|runtimeconfig\.json|deps\.json)|operation\.sh|public\.pem|passwd|root-agent\.(token|log|status)|launcher\.log|launch-sdk\.sh)$/.test(
          n
        )
      )
        continue;
      const p = path.join(stage, n);
      if (fs.lstatSync(p).isFile()) fs.unlinkSync(p);
    }
    try {
      fs.rmdirSync(stage + '/launch-once');
    } catch (_) {}
    const pkg = path.basename(stage);
    for (const suffix of ['.tar.gz', '.tar.gz.signature']) {
      const p = BASE + '/on-demand/' + pkg + suffix;
      if (fs.existsSync(p) && fs.lstatSync(p).isFile()) fs.unlinkSync(p);
    }
    try {
      fs.rmdirSync(stage);
      stage = null;
    } catch (_) {}
    // The shared archive directory persists; remove only this attempt's files.
    // Removing an empty parent can race another setup/agent upload.
  }
  function schedule() {
    if (!running || timer || connected) return;
    if (attempts >= 8) {
      lastError =
        'Acquisition retry budget exhausted; use authenticated disable/enable after diagnosis';
      return;
    }
    timer = setTimeout(
      () => {
        timer = null;
        launch();
      },
      Math.min(60000, 5000 * Math.pow(2, Math.max(0, attempts - 1)))
    );
  }
  function prepare(port, secret, attempt) {
    firmware(config);
    if (options.selectionFile) {
      const prior = recoveryCandidate(options.selectionFile, currentBoot);
      if (prior && (!attempt.recovery || prior.id !== attempt.recovery.id))
        throw Error('Bootstrap recovery must precede acquisition');
    }
    const pkg = 'archive-root-' + crypto.randomBytes(8).toString('hex');
    stage = BASE + '/' + pkg;
    fs.mkdirSync(stage, { mode: 0o755 });
    const onDemand = BASE + '/on-demand';
    try {
      fs.mkdirSync(onDemand, { mode: 0o755 });
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
      const s = fs.lstatSync(onDemand);
      if (!s.isDirectory() || s.isSymbolicLink())
        throw Error('Unsafe staging directory');
    }
    attempt.acquisition = loadAcquisition(payload, config.device);
    if (!attempt.acquisition)
      throw Error('Native acquisition package required');
    acquisitionMode = 'native-managed-entry';
    stageAcquisition(stage, attempt.acquisition);
    const keys = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
    fs.writeFileSync(
      stage + '/public.pem',
      keys.publicKey.export({ type: 'spki', format: 'pem' }),
      { mode: 0o644, flag: 'wx' }
    );
    const passwd = read('/etc/passwd').toString().split('\n');
    let changed = 0;
    const view = passwd
      .map((line) => {
        const parts = line.split(':');
        if (parts[0] === 'owner') {
          if (parts.length !== 7 || parts[2] !== '5001' || parts[3] !== '100')
            throw Error('Unexpected owner identity');
          parts[2] = '0';
          parts[3] = '0';
          changed++;
          return parts.join(':');
        }
        return line;
      })
      .join('\n');
    if (changed !== 1) throw Error('Missing owner identity');
    fs.writeFileSync(stage + '/passwd', view, { mode: 0o644, flag: 'wx' });
    fs.writeFileSync(
      stage + '/root-agent.token',
      secret.toString('base64') + '\n',
      { mode: 0o600, flag: 'wx' }
    );
    let script;
    if (attempt.recovery) {
      // A fresh native acquisition seals and cleans the interrupted bootstrap.
      // It never starts another worker or replays the old launch.
      script = recoveryCommand(attempt.recovery, { bootId: currentBoot() });
    } else {
      const prepared = prepareBootstrap({
        payload,
        device: config.device,
        stage,
        port,
        bootId: currentBoot(),
        journalDirectory: path.dirname(options.selectionFile),
        selectionFile: options.selectionFile,
      });
      attempt.bootstrap = prepared.record;
      script = prepared.command;
    }
    fs.writeFileSync(stage + '/operation.sh', script, {
      mode: 0o644,
      flag: 'wx',
    });
    const archive = tarGz([{ name: 'launch.sh', data: script, mode: 0o700 }]);
    fs.writeFileSync(onDemand + '/' + pkg + '.tar.gz', archive, {
      mode: 0o644,
      flag: 'wx',
    });
    fs.writeFileSync(
      onDemand + '/' + pkg + '.tar.gz.signature',
      crypto.sign('RSA-SHA256', archive, keys.privateKey),
      { mode: 0o644, flag: 'wx' }
    );
    return pkg;
  }
  async function launch() {
    if (!running || connected || launching) return;
    const selected = selection();
    if (
      (!upgradeRecovery && selected.phase !== 'stable') ||
      selected.selected_implementation !== 'native-prototype'
    ) {
      running = false;
      lastError =
        'Native-only package requires settled native enrollment; retain the previous package and journals for legacy recovery';
      return;
    }
    if (
      options.selectionFile &&
      selection().selected_implementation === 'native-prototype' &&
      (selection().phase === 'stable' || upgradeRecovery)
    ) {
      try {
        const c = upgradeRecovery
          ? recoveryPlan(options.selectionFile).candidate
          : startupCandidate(options.selectionFile);
        if (c)
          nativeStartup = { id: c.record.id, phase: 'acquiring', error: null };
      } catch (e) {
        running = false;
        lastError = e.message;
        return;
      }
    }
    if (options.selectionFile) {
      try {
        const prior = recoveryCandidate(options.selectionFile, currentBoot);
        if (prior)
          bootstrapRecovery = {
            id: prior.id,
            record: prior,
            phase: 'acquiring',
            attempts: 0,
            error: null,
          };
      } catch (error) {
        running = false;
        lastError = String(error.message);
        return;
      }
    }
    if (!selection(true).launch_allowed && !restartHeld()) {
      running = false;
      lastError = 'Worker selection requires reconciliation';
      return;
    }
    launching = true;
    attempts++;
    const gen = ++generation,
      attempt = {
        acquisition: null,
        bootstrap: null,
        recovery:
          bootstrapRecovery && bootstrapRecovery.phase !== 'complete'
            ? bootstrapRecovery.record
            : null,
      };
    let step = 'firmware verification';
    try {
      nativeCandidate = candidateStatus(payload, config.device);
      firmware(config);
      const secret = crypto.randomBytes(32);
      if (channel) channel.close();
      channel = new RootAgentServer({
        secret,
        onConnect: (conn) => {
          if (!running || gen !== generation) {
            conn._socket.destroy();
            return;
          }
          connected = true;
          workerReady = false;
          identity = conn.identity;
          conn
            .operation({ op: 'status' })
            .then((info) => {
              if (
                !running ||
                gen !== generation ||
                !connected ||
                channel._conn !== conn
              )
                return;
              if (attempt.bootstrap)
                validateBootstrap(info, {
                  bootId: currentBoot(),
                  launcherSha256: attempt.bootstrap.launcher_sha256,
                });
              else throw Error('Unexpected worker during acquisition recovery');
              workerStatus = info;
              workerStatusAt = process.uptime();
              workerReady = true;
              lastAcquired = new Date().toISOString();
              if (nativeStartup && nativeStartup.phase !== 'complete')
                runNativeStartup(conn, gen, attempt.bootstrap);
            })
            .catch((error) => {
              if (gen === generation && connected && channel._conn === conn) {
                lastError = String(error.message);
                conn._socket.destroy();
              }
            });
          lastError = null;
          launching = false;
          if (timer) {
            clearTimeout(timer);
            timer = null;
          }
          if (client) {
            sdb.close(client);
            client = null;
          }
        },
        onClose: () => {
          if (
            gen !== generation ||
            (attempt.bootstrap && nativeStartup && nativeStartup.retiring)
          )
            return;
          connected = false;
          workerReady = false;
          identity = null;
          workerStatus = null;
          workerStatusAt = 0;
          schedule();
        },
      });
      await new Promise((resolve, reject) => {
        channel.start(resolve);
        channel._server.once('error', reject);
      });
      if (!running || gen !== generation) return;
      step = 'loopback connection';
      const opened = await sdb.connect({
        host: '127.0.0.1',
        port: 26101,
        timeout: 8000,
      });
      if (!running || gen !== generation) {
        sdb.close(opened);
        return;
      }
      client = opened;
      step = 'payload staging';
      clean();
      const pkg = prepare(channel.listeningPort(), secret, attempt);
      const command =
        'env -i PATH=/usr/bin:/bin DBUS_SYSTEM_BUS_ADDRESS=kernel:path=/sys/fs/kdbus/0-system/bus /usr/bin/dotnet ' +
        quote(stage + '/NativeEntry.dll') +
        ' probe ' +
        quote(pkg);
      // SDK UID 901 cannot create a marker in the app-owned staging directory.
      const gate = '/tmp/' + pkg + '-launch-once';
      fs.writeFileSync(
        stage + '/launch-sdk.sh',
        'set -eu\n' + sdkRuntimeGuard(config) + command + '\n',
        { mode: 0o644, flag: 'wx' }
      );
      step = 'SDK launcher';
      const output = await launchSdk(
        client,
        stage,
        gate,
        !!attempt.acquisition
      );
      if (attempt.recovery) {
        if (!running || gen !== generation) return;
        completeAcquisitionRecovery(
          options.selectionFile,
          attempt.recovery,
          currentBoot(),
          output
        );
        bootstrapRecovery.phase = 'complete';
        return;
      }
      if (!connected && output)
        lastError =
          'SDK launcher: ' + output.slice(-300).replace(/[\r\n]+/g, ' ');
      if (!connected && running && gen === generation)
        throw Error(
          lastError && lastError.startsWith('SDK launcher:')
            ? lastError
            : 'Launcher returned without authenticated agent'
        );
    } catch (e) {
      if (running && gen === generation && !connected) {
        lastError = (step + ': ' + String(e.message || e.code)).slice(0, 300);
        lastAcquisitionError = lastError;
      }
    } finally {
      if (gen === generation) {
        launching = false;
        if (client) {
          sdb.close(client);
          client = null;
        }
        if (!connected) schedule();
      }
    }
  }
  function restartHeld() {
    return (
      upgradeHeld ||
      (!!bootstrapRecovery && bootstrapRecovery.phase !== 'complete') ||
      (!!nativeStartup && nativeStartup.phase !== 'complete')
    );
  }
  async function runNativeStartup(conn, gen, bootstrap) {
    const r = nativeStartup,
      owner = channel;
    const owned = () => {
      if (
        !running ||
        gen !== generation ||
        channel !== owner ||
        owner._conn !== conn ||
        !connected ||
        nativeStartup !== r
      )
        throw Error('Native bootstrap executor changed');
    };
    r.phase = 'verifying';
    let result;
    try {
      if (bootstrap) {
        bootstrap = await bindBootstrap(bootstrap, owner, currentBoot());
        owned();
        r.bootstrap = {
          id: bootstrap.id,
          implementation: 'native-bootstrap',
          phase: 'ready',
        };
      }
      result = await (upgradeRecovery ? recoverUpgrade : startSelectedNative)({
        selectionFile: options.selectionFile,
        executor: {
          implementation: 'native-bootstrap',
          launcherSha256: bootstrap && bootstrap.launcher_sha256,
          pid: conn.identity.pid,
          status: async () => {
            owned();
            const info = await conn.operation({ op: 'status' });
            owned();
            return info;
          },
          execute: async (c, t) => {
            owned();
            const value = await owner.execute(c, t);
            owned();
            return value;
          },
        },
      });
      owned();
      const next = result.channel,
        peer = next._conn;
      if (!peer) throw Error('Native startup transport changed');
      if (bootstrap) {
        r.retiring = true;
        await retireBootstrap(bootstrap, owner, next);
        if (
          !running ||
          gen !== generation ||
          channel !== owner ||
          nativeStartup !== r ||
          owner._conn !== null ||
          next._conn !== peer
        )
          throw Error('Retired bootstrap ownership changed');
        r.bootstrap.phase = 'retired';
      }
      if (result.finish) result.finish();
      upgradeHeld = false;
      upgradeRecovery = false;
      const adoptedGeneration = ++generation;
      channel = next;
      connected = true;
      workerReady = true;
      workerStatus = result.info;
      workerStatusAt = process.uptime();
      identity = peer.identity;
      launching = false;
      lastError = null;
      nativeRuntime = { ...result, generation: adoptedGeneration };
      r.phase = 'complete';
      const previousClose = next.onClose;
      next.onClose = (error) => {
        try {
          if (previousClose) previousClose(error);
        } finally {
          nativeDisconnected(next, adoptedGeneration);
        }
      };
      owner.close();
    } catch (error) {
      if (result && channel !== result.channel) result.channel.close();
      r.phase = 'failed';
      r.error = [];
      for (let c = error; c && r.error.length < 4; c = c.cause)
        r.error.push(String(c.message).slice(0, 160));
      lastError = r.error.join(': ');
    }
  }
  function nativeDisconnected(next, gen) {
    if (generation !== gen || channel !== next) return;
    if (upgradeHeld) {
      connected = false;
      workerReady = false;
      return;
    }
    connected = false;
    workerReady = false;
    workerStatus = null;
    identity = null;
    workerStatusAt = 0;
    nativeRuntime = null;
    lastError = 'Native worker disconnected; reconciliation required';
    nativeStartup = null;
    schedule();
  }
  function start() {
    if (running) return;
    running = true;
    attempts = 0;
    lastError = null;
    lastAcquisitionError = null;
    launch();
  }
  function stop() {
    for (const c of upgradeChannels) c.close();
    upgradeChannels.clear();
    upgradeRecovery = false;
    nativeRuntime = null;
    running = false;
    connected = false;
    workerReady = false;
    identity = null;
    workerStatus = null;
    workerStatusAt = 0;
    ++generation;
    nativeStartup = null;
    bootstrapRecovery = null;
    if (timer) clearTimeout(timer);
    timer = null;
    if (client) sdb.close(client);
    client = null;
    if (channel) channel.close();
    channel = null;
    launching = false;
    const stopped = generation;
    setTimeout(() => {
      if (!running && generation === stopped) {
        try {
          clean();
        } catch (e) {
          lastError = 'Staging cleanup incomplete';
        }
      }
    }, 1000);
  }
  function submit(call) {
    if (
      restartHeld() ||
      !running ||
      !connected ||
      !workerReady ||
      !channel ||
      !runtimeAllowed(selection())
    )
      return Promise.reject(
        Object.assign(Error('Root worker unavailable or admission held'), {
          outcome: 'rejected',
        })
      );
    let request;
    try {
      request = Promise.resolve(call(channel));
    } catch (e) {
      request = Promise.reject(e);
    }
    // Keep a result classification, not command output, for the handoff drain.
    // Transport errors without an explicit outcome are also uncertain.
    const settled = request.then(
      () => true,
      (e) => !!e && ['failed', 'rejected'].includes(e.outcome)
    );
    inFlight.add(settled);
    settled.then(() => inFlight.delete(settled));
    return request;
  }
  // Durable evidence only; live coordinator handles are reported separately.
  const restartInventory = () => {
    if (!options.selectionFile) return null;
    try {
      return {
        ...inventoryRestart(options.selectionFile),
        bootstrap_recovery: bootstrapRecovery && {
          id: bootstrapRecovery.id,
          phase: bootstrapRecovery.phase,
          attempts: bootstrapRecovery.attempts,
          error: bootstrapRecovery.error,
        },
        native_startup: nativeStartup,
      };
    } catch (error) {
      return {
        schema: 1,
        action: 'pending-reconciliation',
        diagnostics: [
          'inventory unavailable: ' + String(error.message).slice(0, 160),
        ],
      };
    }
  };
  function upgradeReview(target = 'package') {
    firmware(config);
    if (!runtimeAllowed(selection()) || restartHeld())
      throw Error('Ready native worker required');
    return reviewUpgrade({
      selectionFile: options.selectionFile,
      payload,
      device: config.device,
      target,
    });
  }
  async function upgradeNative(reviewSha256, target = 'package') {
    const review = upgradeReview(target);
    if (review.sha256 !== reviewSha256 || inFlight.size)
      throw Object.assign(Error('Upgrade review changed or requests active'), {
        outcome: 'rejected',
      });
    const owner = channel,
      gen = generation,
      peer = owner._conn;
    upgradeHeld = true;
    const owned = () => {
      if (!running || generation !== gen || channel !== owner)
        throw Error('Upgrade ownership changed');
    };
    const hold = {
      pid: peer.identity.pid,
      check: owned,
      status: async () => {
        owned();
        const r = await owner.operation({ op: 'status' });
        owned();
        return r;
      },
      execute: async (c, t) => {
        owned();
        const r = await owner.execute(c, t);
        owned();
        return r;
      },
      shutdown: async () => {
        owned();
        return owner.shutdown();
      },
      release: () => {
        owned();
        upgradeHeld = false;
      },
      adopt: async (result) => {
        owned();
        const next = result.channel,
          p = next._conn;
        if (!p) throw Error('Upgraded worker disconnected');
        const adopted = ++generation;
        channel = next;
        connected = true;
        workerReady = true;
        identity = p.identity;
        workerStatus = result.info;
        workerStatusAt = process.uptime();
        nativeRuntime = { ...result, generation: adopted };
        upgradeHeld = false;
        lastError = null;
        const close = next.onClose;
        next.onClose = (e) => {
          try {
            if (close) close(e);
          } finally {
            nativeDisconnected(next, adopted);
          }
        };
        upgradeChannels.clear();
        owner.close();
      },
    };
    try {
      return await runUpgrade({
        selectionFile: options.selectionFile,
        payload,
        device: config.device,
        reviewSha256,
        target,
        hold,
        retain: (c) => upgradeChannels.add(c),
      });
    } catch (e) {
      lastError = String(e.message);
      if (
        !upgradeStatus(options.selectionFile) &&
        selection().phase === 'stable'
      )
        hold.release();
      throw e;
    }
  }
  function recoverNativeUpgrade() {
    if (upgradeRecovery && nativeStartup && nativeStartup.phase !== 'failed')
      throw Error('Native upgrade recovery already running');
    recoveryPlan(options.selectionFile); // Validate before closing any transport.
    stop();
    upgradeHeld = true;
    upgradeRecovery = true;
    start();
    return { phase: 'recovering', status_url: '/v1/status' };
  }
  const api = {
    status,
    start,
    stop,
    restartInventory,
    upgradeReview,
    upgradeNative,
    recoverNativeUpgrade,
    operation: (value, data) => submit((owner) => owner.operation(value, data)),
    execute: (command, timeout) =>
      submit((owner) => owner.execute(command, timeout)),
  };
  return api;
}
module.exports = { createAgent, launchRequest, launchSdk };
