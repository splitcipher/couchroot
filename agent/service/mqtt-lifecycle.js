'use strict';
// Credentials and MQTT stay in the selected native worker. This lease only
// admits an independently ready worker; maintenance/retirement fences win.
function createMqttLifecycle(agent, config, version) {
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
        return;
      }
      const result = await agent.operation({
        op: 'mqtt.start',
        device: config.device,
        firmware: config.firmware,
        version,
      });
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
      leaseState = 'stopped';
    },
  };
}
module.exports = { createMqttLifecycle };
