/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
/* Only the authenticated coordinator can replace this mailbox. Credentials and
 * broker commands cannot supply observations. A six-second TTL clears readings,
 * while known capabilities/inventories survive temporary coordinator delays. */
static char mqtt_observations[8192], mqtt_foreground_id[257];
static double mqtt_observations_at, mqtt_foreground_at;
typedef struct {
  MqttCpu cpu;
  int cpu_supported, memory_supported, foreground_supported;
  double next_foreground;
  char foreground[257];
} MqttSampler;
static int mqtt_supported(J *features, const char *key) {
  J *v = features ? get(features, key) : NULL;
  return v && json_object_is_type(v, 1) && json_object_get_boolean(v);
}
static const char *mqtt_observed_text(J *j, const char *key, size_t max) {
  J *v = j ? get(j, key) : NULL;
  if (!v || !json_object_is_type(v, 6))
    return NULL;
  const char *s = json_object_get_string(v);
  size_t n = strlen(s);
  if (!n || n > max || !mqtt_utf8((const unsigned char *)s) ||
      (size_t)json_object_get_string_len(v) != n)
    return NULL;
  for (const unsigned char *p = (const unsigned char *)s; *p; p++)
    if (*p < 32 || *p == 127)
      return NULL;
  return s;
}
static int mqtt_name_compare(const void *a, const void *b) {
  return strcmp(a, b);
}
static J *mqtt_app_options(J *apps) {
  J *options = json_object_new_array();
  if (!apps || !json_object_is_type(apps, 5) ||
      json_object_array_length(apps) > 64)
    return options;
  char names[64][97];
  size_t count = 0;
  for (size_t i = 0; i < json_object_array_length(apps); i++) {
    J *app = json_object_array_get_idx(apps, i);
    const char *id = mqtt_observed_text(app, "id", 256),
               *name = mqtt_observed_text(app, "name", 96);
    if (!mqtt_app_id(id) || !name) {
      json_object_put(options);
      return json_object_new_array();
    }
    strcpy(names[count++], name);
  }
  qsort(names, count, sizeof names[0], mqtt_name_compare);
  for (size_t i = 0; i < count; i++) {
    /* A name that maps to multiple IDs is not a safe future command option. */
    if ((i && !strcmp(names[i], names[i - 1])) ||
        (i + 1 < count && !strcmp(names[i], names[i + 1])))
      continue;
    json_object_array_add(options, json_object_new_string(names[i]));
  }
  return options;
}
static J *mqtt_source_options(J *sources) {
  J *options = json_object_new_array();
  if (!sources || !json_object_is_type(sources, 5) ||
      json_object_array_length(sources) > 5)
    return options;
  const char *ids[] = {"hdmi1", "hdmi2", "hdmi3", "hdmi4", "tv"};
  for (size_t i = 0; i < 5; i++) {
    for (size_t j = 0; j < json_object_array_length(sources); j++) {
      J *v = json_object_array_get_idx(sources, j);
      if (v && json_object_is_type(v, 6) &&
          !strcmp(json_object_get_string(v), ids[i]) &&
          json_object_get_string_len(v) == (int)strlen(ids[i])) {
        json_object_array_add(options, json_object_new_string(ids[i]));
        break;
      }
    }
  }
  return options;
}
/* Projection is deliberately fixed. No setting, path, topic or operation from
 * this local observation envelope can become an MQTT command/worker operation.
 */
static void mqtt_project(J *observation, int fresh, const char *foreground,
                         J *state, J *features) {
  if (observation && !json_object_is_type(observation, 4))
    observation = NULL;
  J *s = observation ? get(observation, "state") : NULL;
  J *caps = observation ? get(observation, "supported") : NULL;
  if (s && !json_object_is_type(s, 4))
    s = NULL;
  if (caps && !json_object_is_type(caps, 4))
    caps = NULL;
  json_object_object_add(
      features, "apps",
      mqtt_app_options(observation ? get(observation, "apps") : NULL));
  json_object_object_add(
      features, "sources",
      mqtt_source_options(observation ? get(observation, "sources") : NULL));
  int64_t volume;
  if (fresh && mqtt_supported(caps, "volume") &&
      integer(s, "volume", &volume) && volume >= 0 && volume <= 100)
    num(state, "volume", volume);
  J *muted = s ? get(s, "muted") : NULL;
  if (fresh && mqtt_supported(caps, "muted") && muted &&
      json_object_is_type(muted, 1))
    boolean(state, "muted", json_object_get_boolean(muted));
  /* No qualified visible-source adapter yet. Do not project a cached MAIN
   * window's selected input or timings as the current on-screen picture. */
  const char *observed_id = mqtt_observed_text(s, "app_id", 256),
             *name = mqtt_observed_text(s, "app_name", 96);
  if (foreground && *foreground)
    str(state, "app_id", foreground);
  boolean(features, "app", mqtt_supported(caps, "app"));
  if (fresh && foreground && observed_id && !strcmp(observed_id, foreground) &&
      name && mqtt_supported(caps, "app"))
    str(state, "app_name", name);
}
static void mqtt_observe(J *request) {
  const char *raw = textval(request, "observations");
  pthread_mutex_lock(&mqtt_mutex);
  if (mqtt_settings.state && raw && strlen(raw) < sizeof mqtt_observations) {
    strcpy(mqtt_observations, raw);
    mqtt_observations_at = stamp();
  } else {
    mqtt_observations[0] = 0;
    mqtt_observations_at = 0;
  }
  pthread_mutex_unlock(&mqtt_mutex);
}
static void mqtt_observation_reply(J *result) {
  boolean(result, "observe_state", mqtt_settings.state);
  pthread_mutex_lock(&mqtt_mutex);
  if (stamp() - mqtt_foreground_at < 6000 && *mqtt_foreground_id)
    str(result, "foreground_app", mqtt_foreground_id);
  pthread_mutex_unlock(&mqtt_mutex);
}
static void mqtt_sample(const MqttConfig *c, MqttSampler *sampler, J **state,
                        J **health, J **features, int (*cancel)(void)) {
  *state = mqtt_initial_state();
  *health = mqtt_health(c);
  *features = obj();
  if (!c->state)
    return;
  char raw[32768];
  double observed_at;
  pthread_mutex_lock(&mqtt_mutex);
  strcpy(raw, mqtt_observations);
  observed_at = mqtt_observations_at;
  pthread_mutex_unlock(&mqtt_mutex);
  J *observation = *raw ? parse(raw) : NULL;
  double now = stamp();
  if (now >= sampler->next_foreground) {
    int rc =
        mqtt_foreground_read("/proc/self/exe", sampler->foreground, cancel);
    if (rc >= 0)
      sampler->foreground_supported = rc;
    sampler->next_foreground = now + (rc == 0 ? 30000 : 2000);
    pthread_mutex_lock(&mqtt_mutex);
    strcpy(mqtt_foreground_id, sampler->foreground);
    mqtt_foreground_at = stamp();
    pthread_mutex_unlock(&mqtt_mutex);
  }
  mqtt_project(observation, observed_at > 0 && now - observed_at < 6000,
               sampler->foreground, *state, *features);
  if (!sampler->foreground_supported)
    boolean(*features, "app", 0);
  if (observation)
    json_object_put(observation);
  uint64_t counters[8];
  int read_ok = mqtt_proc_read("/proc/stat", raw, sizeof raw, 1);
  if (read_ok && mqtt_cpu_parse(raw, counters))
    sampler->cpu_supported = 1;
  json_object_object_add(
      *health, "cpu_pct",
      mqtt_cpu_sample(&sampler->cpu, read_ok ? raw : NULL, now));
  read_ok = mqtt_proc_read("/proc/meminfo", raw, sizeof raw, 0);
  J *memory = mqtt_memory_sample(read_ok ? raw : NULL);
  if (memory)
    sampler->memory_supported = 1;
  json_object_object_add(*health, "mem_used_pct", memory);
  boolean(*features, "cpu", sampler->cpu_supported);
  boolean(*features, "memory", sampler->memory_supported);
}
