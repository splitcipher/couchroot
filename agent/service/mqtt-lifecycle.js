'use strict';
// Credentials and MQTT stay in the selected native worker. This lease only
// admits an independently ready worker; maintenance/retirement fences win.
const { createMqttState } = require('./mqtt-state');
function createMqttLifecycle(agent, config, version, api) {
  const observer = createMqttState(
    api || (typeof tizen === 'undefined' ? {} : tizen)
  );
  let observe = false,
    foreground = null,
    workerId,
    configInactive = false;
  let busy = false,
    stopped = false,
    leaseState = 'waiting-worker';
  async function tick() {
    if (busy || stopped) return;
    busy = true;
    try {
      const status = agent.status();
      if (
        !status.worker_ready ||
        status.admission_held ||
        status.native_upgrade ||
        !Array.isArray(status.capabilities) ||
        !status.capabilities.includes('mqtt-bridge-v1')
      ) {
        leaseState = 'waiting-worker';
        observe = false;
        foreground = null;
        configInactive = false;
        return;
      }
      if (workerId !== status.worker_id) {
        observe = false;
        foreground = null;
        configInactive = false;
        workerId = status.worker_id;
      }
      // An unconfigured or disabled bridge is inert for this worker generation.
      // A worker restart (new worker_id) is required to pick up a newly installed
      // private config, so do not repeat the lease or state readers on every tick.
      if (configInactive) return;
      const observations = observe ? await observer.sample(foreground) : null;
      if (stopped) return;
      const ready = agent.status();
      if (
        !ready.worker_ready ||
        ready.admission_held ||
        ready.native_upgrade ||
        ready.worker_id !== status.worker_id
      )
        return;
      const request = {
        op: 'mqtt.start',
        device: config.device,
        firmware: config.firmware,
        version,
      };
      if (observations) request.observations = JSON.stringify(observations);
      const result = await agent.operation(request);
      observe = !!(result && result.observe_state === true);
      foreground = result && result.foreground_app;
      if (
        result &&
        (result.state === 'unconfigured' || result.state === 'disabled')
      ) {
        observe = false;
        foreground = null;
        configInactive = true;
      }
      if (!stopped)
        leaseState =
          result &&
          [
            'started',
            'disabled',
            'unconfigured',
            'invalid_metadata',
            'metadata_drift',
            'thread_unavailable',
          ].includes(result.state)
            ? result.state
            : 'unavailable';
    } catch (_) {
      if (!stopped) leaseState = 'unavailable';
      // No retry of commands or broker credentials. A later readiness tick may
      // renew the idempotent lease; it cannot bypass worker admission.
    } finally {
      busy = false;
    }
  }
  return {
    tick,
    status() {
      return { lease_state: leaseState };
    },
    stop() {
      stopped = true;
      observer.stop();
      leaseState = 'stopped';
    },
  };
}
module.exports = { createMqttLifecycle };
