/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
// Include order follows the worker’s single-translation-unit convention.
#include "config.h"

#include "discovery.h"

#include "commands.h"

#include "fd.h"

#include "wire.h"

#include "foreground.h"

#include "metrics.h"

#include "state.h"
static double mqtt_lease;
/* One replaceable snapshot, no offline publication/command queue. The first
 * changed snapshot sets a bounded 250 ms deadline; subsequent changes coalesce.
 */
typedef struct {
  char latest[4096];
  double due;
  int dirty;
} MqttState;
static int mqtt_state_update(MqttState *s, const char *value, double now) {
  if (strlen(value) >= sizeof s->latest)
    return 0;
  if (!strcmp(value, s->latest))
    return 1;
  strcpy(s->latest, value);
  if (!s->dirty)
    s->due = now + 250;
  s->dirty = 1;
  return 1;
}
static int mqtt_state_due(MqttState *s, double now) {
  return s->dirty && now >= s->due;
}
static int mqtt_owned(void) {
  pthread_mutex_lock(&mqtt_mutex);
  int good = !mqtt_stopping && stamp() < mqtt_lease;
  pthread_mutex_unlock(&mqtt_mutex);
  return good;
}
static int mqtt_snapshot(int fd, const MqttConfig *c, MqttState *s,
                         const char *discovery_json, const char *health,
                         int discovery, int publish_health) {
  char topic[128];
  if (discovery) {
    snprintf(topic, sizeof topic, "homeassistant/device/tv_%s/config",
             c->device);
    if (!mqtt_publish(fd, topic, discovery_json, 1))
      return 0;
    snprintf(topic, sizeof topic, "tv/%s/unsupported", c->device);
    if (!mqtt_publish(fd, topic, "offline", 1))
      return 0;
    snprintf(topic, sizeof topic, "tv/%s/availability", c->device);
    if (!mqtt_publish(fd, topic, "online", 1))
      return 0;
  }
  snprintf(topic, sizeof topic, "tv/%s/state", c->device);
  if (!mqtt_publish(fd, topic, s->latest, 1))
    return 0;
  s->dirty = 0;
  snprintf(topic, sizeof topic, "tv/%s/health", c->device);
  return !publish_health || mqtt_publish(fd, topic, health, 1);
}
static void mqtt_refresh(const MqttConfig *c, MqttSampler *sampler,
                         MqttState *state, char discovery[24576],
                         char health[2048], double *discovery_due) {
  J *s, *h, *features;
  mqtt_sample(c, sampler, &s, &h, &features, mqtt_cancelled);
  mqtt_state_update(state, json(s), stamp());
  snprintf(health, 2048, "%s", json(h));
  J *d = mqtt_discovery(c, features);
  const char *raw = json(d);
  if (strlen(raw) < 24576 && strcmp(raw, discovery)) {
    strcpy(discovery, raw);
    if (!*discovery_due)
      *discovery_due = stamp() + 250;
  }
  json_object_put(s);
  json_object_put(h);
  json_object_put(features);
  json_object_put(d);
}
static int mqtt_incoming(int fd, const MqttConfig *c, unsigned char type,
                         unsigned char *packet, size_t size, double *tokens,
                         double *token_at, int *birth) {
  if (type == 0xd0)
    return size == 0; /* PINGRESP */
  /* Subscription QoS is 0. A broker sending QoS1/2 or DUP QoS0 is invalid. */
  if ((type != 0x30 && type != 0x31) || size < 2)
    return 0;
  size_t t = (size_t)packet[0] * 256 + packet[1];
  if (!t || t > 256 || t + 2 > size)
    return 0;
  char topic[257];
  memcpy(topic, packet + 2, t);
  topic[t] = 0;
  if (memchr(topic, 0, t))
    return 0;
  size_t n = size - t - 2;
  unsigned char *payload = packet + t + 2;
  if (!strcmp(topic, "homeassistant/status")) {
    if (n == 6 && !memcmp(payload, "online", 6))
      *birth = 1;
    return 1;
  }
  char prefix[64];
  snprintf(prefix, sizeof prefix, "tv/%s/cmd/", c->device);
  if (strncmp(topic, prefix, strlen(prefix)))
    return 1;
  const char *name = topic + strlen(prefix);
  if (!*name || strlen(name) > 32)
    return 1;
  for (const char *p = name; *p; p++)
    if ((*p < 'a' || *p > 'z') && *p != '_')
      return 1;
  double now = stamp();
  *tokens += (now - *token_at) / 100.0;
  *token_at = now;
  if (*tokens > 20)
    *tokens = 20;
  if (*tokens < 1)
    return 1; /* Drop overload, including log/result amplification. */
  *tokens -= 1;
  char raw[3073];
  J *command = NULL;
  const char *error = "invalid_payload";
  if (n > 0 && n < sizeof raw && !memchr(payload, 0, n)) {
    memcpy(raw, payload, n);
    raw[n] = 0;
    command = mqtt_command(name, raw, &error);
    mqtt_wipe(raw, sizeof raw);
  }
  if (type & 1)
    error = "retained_command";
  else if (command)
    error = "unsupported_capability";
  J *result = obj();
  str(result, "cmd", name);
  boolean(result, "ok", 0);
  str(result, "error", error);
  if (command && textval(command, "id"))
    str(result, "id", textval(command, "id"));
  else
    json_object_object_add(result, "id", NULL);
  if (command)
    json_object_put(command);
  /* Feature 1 deliberately has no operation dispatcher. */
  mqtt_log("warn", "command_rejected");
  snprintf(prefix, sizeof prefix, "tv/%s/cmd_result", c->device);
  return mqtt_publish_json(fd, prefix, result, 0);
}
static void *mqtt_loop(void *unused) {
  (void)unused;
  MqttState state = {0};
  MqttSampler sampler = {0};
  char discovery_json[24576] = {0}, health_json[2048] = {0};
  double sample_due = 0, discovery_due = 0;
  unsigned backoff = 1;
  while (!mqtt_cancelled()) {
    if (!mqtt_owned()) {
      poll(NULL, 0, 100);
      continue;
    }
    /* Always sample before connect; never reconnect with an old retained value.
     */
    mqtt_refresh(&mqtt_settings, &sampler, &state, discovery_json, health_json,
                 &discovery_due);
    sample_due = stamp() + 2000;
    int fd = mqtt_connect(&mqtt_settings);
    if (fd >= 0) {
      mqtt_refresh(&mqtt_settings, &sampler, &state, discovery_json,
                   health_json, &discovery_due);
      double connected = stamp(), refresh = connected + 60000,
             next_ping = connected + 15000, ping_deadline = 0;
      double tokens = 20, token_at = connected, birth_due = 0;
      mqtt_log("info", "connected");
      int good =
          mqtt_owned() && mqtt_snapshot(fd, &mqtt_settings, &state,
                                        discovery_json, health_json, 1, 1);
      discovery_due = 0;
      while (good && mqtt_owned()) {
        double now = stamp();
        if (now >= sample_due) {
          mqtt_refresh(&mqtt_settings, &sampler, &state, discovery_json,
                       health_json, &discovery_due);
          sample_due = stamp() + 2000;
        }
        if ((birth_due && now >= birth_due) ||
            (discovery_due && now >= discovery_due) || now >= refresh ||
            mqtt_state_due(&state, now)) {
          int full = birth_due != 0 || now >= refresh;
          good = mqtt_snapshot(fd, &mqtt_settings, &state, discovery_json,
                               health_json,
                               birth_due != 0 || discovery_due != 0, full);
          if (full)
            refresh = now + 60000;
          birth_due = discovery_due = 0;
        }
        if (ping_deadline && now >= ping_deadline)
          break;
        if (now >= next_ping && !ping_deadline) {
          good = good && mqtt_send(fd, 0xc0, NULL, 0);
          ping_deadline = now + 10000;
          next_ping = now + 15000;
        }
        struct pollfd p = {fd, POLLIN, 0};
        int ready = poll(&p, 1, 100);
        if (ready < 0 && errno != EINTR)
          break;
        if (ready > 0) {
          unsigned char type, packet[MQTT_PACKET_MAX];
          size_t n;
          int birth = 0;
          if (!mqtt_receive(fd, &type, packet, &n))
            break;
          if (type == 0xd0)
            ping_deadline = 0;
          good = mqtt_incoming(fd, &mqtt_settings, type, packet, n, &tokens,
                               &token_at, &birth);
          if (birth && !birth_due)
            birth_due = stamp() + 250;
        }
      }
      if (!mqtt_cancelled() && !mqtt_owned()) {
        char topic[64];
        snprintf(topic, sizeof topic, "tv/%s/availability",
                 mqtt_settings.device);
        if (mqtt_publish(fd, topic, "offline", 1))
          mqtt_send(fd, 0xe0, NULL, 0);
      }
      close(fd); /* On shutdown/error the broker publishes the retained will. */
      if (stamp() - connected >= 60000)
        backoff = 1;
      mqtt_log("info", "disconnected");
    } else
      mqtt_log("warn", "connect_failed");
    /* Bounded 1..60 second backoff, deterministic per-device jitter. */
    double until = stamp() + backoff * 1000 +
                   (!strcmp(mqtt_settings.device, "qn90a") ? 137 : 379);
    while (!mqtt_cancelled() && stamp() < until)
      poll(NULL, 0, 100);
    if (backoff < 60)
      backoff = backoff > 30 ? 60 : backoff * 2;
  }
  return NULL;
}
static void mqtt_stop(void) {
  pthread_mutex_lock(&mqtt_mutex);
  mqtt_stopping = 1;
  pthread_mutex_unlock(&mqtt_mutex);
  if (mqtt_thread_started && !pthread_equal(pthread_self(), mqtt_thread))
    pthread_join(mqtt_thread, NULL);
  mqtt_thread_started = 0;
  mqtt_active = 0;
  mqtt_wipe(&mqtt_settings, sizeof mqtt_settings);
  mqtt_wipe(mqtt_observations, sizeof mqtt_observations);
  mqtt_foreground_id[0] = 0;
}
/* Only the existing authenticated coordinator admits/renews this capability.
 * No private config path or broker credentials can be supplied through IPC. */
static J *mqtt_start(J *request) {
  J *result = obj();
  const char *device = textval(request, "device"),
             *firmware = textval(request, "firmware"),
             *version = textval(request, "version");
  if (!device || !firmware || !version) {
    str(result, "state", "invalid_metadata");
    return result;
  }
  if (mqtt_active) {
    if (strcmp(device, mqtt_settings.device) ||
        strcmp(firmware, mqtt_settings.firmware) ||
        strcmp(version, mqtt_settings.version)) {
      str(result, "state", "metadata_drift");
      return result;
    }
    pthread_mutex_lock(&mqtt_mutex);
    mqtt_lease = stamp() + 10000;
    pthread_mutex_unlock(&mqtt_mutex);
    mqtt_observe(request);
    mqtt_observation_reply(result);
    str(result, "state", "started");
    return result;
  }
  int admitted = mqtt_fd_lock(2);
  int configured =
      admitted && mqtt_config("/opt/couchroot/mqtt/config.json", device,
                              firmware, version, &mqtt_settings);
  if (admitted)
    mqtt_fd_unlock();
  if (!configured) {
    mqtt_wipe(&mqtt_settings, sizeof mqtt_settings);
    str(result, "state", "unconfigured");
    return result;
  }
  if (!mqtt_settings.enabled) {
    str(result, "state", "disabled");
    return result;
  }
  pthread_mutex_lock(&mqtt_mutex);
  mqtt_stopping = 0;
  mqtt_lease = stamp() + 10000;
  pthread_mutex_unlock(&mqtt_mutex);
  mqtt_observe(request);
  /* Do not let an optional broker failure stop the administration worker. */
  sigset_t blocked, previous;
  lifecycle_signals(&blocked);
  int e = pthread_sigmask(SIG_BLOCK, &blocked, &previous);
  if (!e) {
    e = pthread_create(&mqtt_thread, NULL, mqtt_loop, NULL);
    if (pthread_sigmask(SIG_SETMASK, &previous, NULL))
      fatal("restore MQTT signal mask");
  }
  if (e) {
    str(result, "state", "thread_unavailable");
    return result;
  }
  mqtt_active = mqtt_thread_started = 1;
  mqtt_observation_reply(result);
  str(result, "state", "started");
  return result;
}
