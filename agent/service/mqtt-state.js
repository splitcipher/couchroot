'use strict';
// Original Couchroot code. SPDX-License-Identifier: 0BSD
// Read-only service APIs. No UI context, listener replacement, setters or guessed
// vendor enum mappings. Each sample replaces values; failures never reuse them.
const validText = (s, limit) =>
  typeof s === 'string' &&
  s.length > 0 &&
  Buffer.byteLength(s, 'utf8') <= limit &&
  !/[\x00-\x1f\x7f]/.test(s);
const appId = (s) => typeof s === 'string' && /^[A-Za-z0-9_.-]{1,256}$/.test(s);
const sourceId = (s) => {
  if (!s) return null;
  if (s.type === 'TV') return 'tv';
  return s.type === 'HDMI' &&
    Number.isInteger(s.number) &&
    s.number >= 1 &&
    s.number <= 4
    ? 'hdmi' + s.number
    : null;
};
function appInventory(rows) {
  if (!Array.isArray(rows) || rows.length > 1024) throw Error('inventory');
  const native = [
    'org.tizen.netflix-app',
    'org.tizen.primevideo',
    'org.tizen.browser',
    'com.samsung.tv.tvplus',
  ];
  const apps = [];
  for (const row of rows) {
    if (!row || !appId(row.id)) throw Error('inventory');
    if (
      row.show !== true ||
      ['MiniHub001.Hub', 'com.samsung.tv.csfs'].includes(row.id)
    )
      continue;
    const pkg = row.packageId || row.id.split('.')[0];
    if (
      typeof pkg !== 'string' ||
      (!/^[A-Za-z0-9]{10}$/.test(pkg) && !native.includes(row.id))
    )
      continue;
    if (!validText(row.name, 96)) throw Error('inventory');
    apps.push({ id: row.id, name: row.name });
  }
  if (apps.length > 64 || new Set(apps.map((x) => x.id)).size !== apps.length)
    throw Error('inventory');
  return apps.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}
function monotonic() {
  const t = process.hrtime();
  return t[0] * 1000 + t[1] / 1e6;
}
function createMqttState(api, clock = monotonic) {
  const supported = {};
  let stopped = false,
    inventoryAt = -Infinity,
    apps = [],
    sources = [],
    appsKnown = false,
    sourcesKnown = false;
  const pending = new Set(),
    inFlight = new Set();
  function read(key, call, valid) {
    try {
      const value = call();
      if (!valid(value)) return null;
      supported[key] = true;
      return value;
    } catch (error) {
      if (
        error &&
        ['NotSupportedError', 'SecurityError', 'TypeError'].includes(error.name)
      )
        delete supported[key];
      return null;
    }
  }
  function asyncRead(key, call) {
    if (inFlight.has(key)) return Promise.resolve(null);
    inFlight.add(key);
    return new Promise((resolve) => {
      let done = false;
      const finish = (value) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        pending.delete(cancel);
        resolve(value);
      };
      const cancel = () => finish(null);
      const timer = setTimeout(cancel, 750);
      pending.add(cancel);
      const fail = () => {
        inFlight.delete(key);
        cancel();
      };
      try {
        call((value) => {
          inFlight.delete(key);
          finish({ value });
        }, fail);
      } catch (_) {
        fail();
      }
    });
  }
  async function sample(foreground) {
    if (stopped) return null;
    const state = { app_id: null, app_name: null };
    if (appId(foreground)) {
      const info = read(
        'app',
        () => api.application.getAppInfo(foreground),
        (x) => x && validText(x.name, 96)
      );
      if (info) {
        state.app_id = foreground;
        state.app_name = info.name;
      }
    }
    state.volume = read(
      'volume',
      () => api.tvaudiocontrol.getVolume(),
      (x) => Number.isInteger(x) && x >= 0 && x <= 100
    );
    state.muted = read(
      'muted',
      () => api.tvaudiocontrol.isMute(),
      (x) => typeof x === 'boolean'
    );
    // TVWindow's selected MAIN source is not proof that the window is visible
    // over a streaming app. Keep current input/signal unsupported until the
    // model-specific visible-source relationship is qualified (offline model).
    if (clock() - inventoryAt >= 30000) {
      inventoryAt = clock();
      const [appResult, sourceResult] = await Promise.all([
        asyncRead('apps', (ok, fail) => api.application.getAppsInfo(ok, fail)),
        asyncRead('sources', (ok, fail) =>
          api.systeminfo.getPropertyValue('VIDEOSOURCE', ok, fail)
        ),
      ]);
      if (stopped) return null;
      // A complete empty inventory clears old options. Failure retains the last
      // inventory, but its values are not evidence of a currently running app.
      if (appResult) {
        try {
          apps = appInventory(appResult.value);
          appsKnown = true;
        } catch (_) {
          appsKnown = false;
          apps = [];
        }
      }
      if (sourceResult) {
        const value = sourceResult.value;
        if (
          value &&
          Array.isArray(value.connected) &&
          Array.isArray(value.disconnected) &&
          value.connected.length + value.disconnected.length <= 16
        ) {
          sources = [
            ...new Set(
              value.connected
                .concat(value.disconnected)
                .map(sourceId)
                .filter(Boolean)
            ),
          ].sort();
          sourcesKnown = true;
        } else {
          sources = [];
          sourcesKnown = false;
        }
      }
    }
    const result = {
      state,
      supported: { ...supported },
      apps: appsKnown ? apps : null,
      sources: sourcesKnown ? sources : null,
    };
    // OP frames are capped at 20,000 bytes. The envelope contains this JSON as
    // an escaped string; 8 KiB leaves room even for worst-case escaping. Never
    // send a partial inventory or let optional state terminate worker IPC.
    if (Buffer.byteLength(JSON.stringify(result), 'utf8') >= 8192)
      result.apps = null;
    return result;
  }
  return {
    sample,
    stop() {
      stopped = true;
      for (const cancel of pending) cancel();
    },
  };
}
module.exports = { createMqttState, appInventory, sourceId };
