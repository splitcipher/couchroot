/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
static const struct {
  const char *key, *platform, *name, *field, *command, *unit;
  int diagnostic;
} mqtt_entities[] = {
    {"power", "switch", "Power", "power", "power", NULL, 0},
    {"screen", "switch", "Screen", "screen", "screen", NULL, 0},
    {"mute", "switch", "Mute", "muted", "mute", NULL, 0},
    {"game_mode", "switch", "Game mode", "game_mode", "game_mode", NULL, 0},
    {"kid_mode", "switch", "Kid mode", "kid_mode", "kid_mode", NULL, 0},
    {"telemetry_block", "switch", "Telemetry block", "telemetry_block",
     "telemetry_block", NULL, 0},
    {"source", "select", "Source", "input", "source", NULL, 0},
    {"app_select", "select", "App", "app_name", "launch_app", NULL, 0},
    {"picture_mode", "select", "Picture mode", "picture_mode", "picture_mode",
     NULL, 0},
    {"audio_output", "select", "Audio output", "audio_output", "audio_output",
     NULL, 0},
    {"volume", "number", "Volume", "volume", "volume", NULL, 0},
    {"sleep_timer", "number", "Sleep timer", "sleep_timer", "sleep_timer",
     "min", 0},
    {"app", "sensor", "App", "app_name", NULL, NULL, 0},
    {"input", "sensor", "Input", "input", NULL, NULL, 0},
    {"resolution", "sensor", "Resolution", "signal.resolution", NULL, NULL, 0},
    {"refresh_rate", "sensor", "Refresh rate", "signal.refresh_hz", NULL, "Hz",
     0},
    {"hdr_format", "sensor", "HDR format", "signal.hdr", NULL, NULL, 0},
    {"firmware", "sensor", "Firmware", "firmware", NULL, NULL, 0},
    {"uptime", "sensor", "Uptime", "uptime_s", NULL, "s", 1},
    {"cpu", "sensor", "CPU", "cpu_pct", NULL, "%", 1},
    {"memory", "sensor", "Memory", "mem_used_pct", NULL, "%", 1},
    {"wifi_signal", "sensor", "Wi-Fi signal", "wifi_rssi_dbm", NULL, "dBm", 1},
    {"temperature", "sensor", "Temperature", "temp_c", NULL, "°C", 1},
    {"firmware_update_pending", "binary_sensor", "Firmware update pending",
     "firmware_update_pending", NULL, NULL, 1},
    {"root_ok", "binary_sensor", "Root OK", "root_ok", NULL, NULL, 1},
    {"screen_message", "notify", "Screen message", NULL, "notify", NULL, 0}};
static J *mqtt_discovery(const MqttConfig *c, J *features) {
  J *d = obj(), *dev = obj(), *origin = obj(), *components = obj();
  char value[512], base[48];
  snprintf(base, sizeof base, "tv/%s", c->device);
  snprintf(value, sizeof value, "tv_%s", c->device);
  J *identifiers = json_object_new_array();
  json_object_array_add(identifiers, json_object_new_string(value));
  json_object_object_add(dev, "identifiers", identifiers);
  str(dev, "name", c->name);
  str(dev, "manufacturer", "Samsung");
  str(dev, "model", !strcmp(c->device, "qn90a") ? "QN90A" : "S90D");
  str(dev, "sw_version", c->firmware);
  str(origin, "name", "Couchroot");
  str(origin, "sw_version", c->version);
  json_object_object_add(d, "dev", dev);
  json_object_object_add(d, "o", origin);
  snprintf(value, sizeof value, "%s/availability", base);
  str(d, "availability_topic", value);
  json_object_object_add(d, "cmps", components);
  for (size_t i = 0; i < sizeof mqtt_entities / sizeof *mqtt_entities; i++) {
    J *e = obj();
    const char *key = mqtt_entities[i].key, *p = mqtt_entities[i].platform;
    str(e, "p", p);
    str(e, "name", mqtt_entities[i].name);
    snprintf(value, sizeof value, "tv_%s_%s", c->device, key);
    str(e, "unique_id", value);
    if (mqtt_entities[i].diagnostic)
      str(e, "entity_category", "diagnostic");
    /* Measurement support never enables a control. Feature 3 owns setters. */
    int available = !strcmp(key, "firmware") || !strcmp(key, "uptime") ||
                    !strcmp(key, "root_ok") ||
                    (c->state && !mqtt_entities[i].command && features &&
                     json_object_get_boolean(get(features, key)));
    snprintf(value, sizeof value, "%s/%s", base,
             available ? "availability" : "unsupported");
    str(e, "availability_topic", value);
    if (mqtt_entities[i].field) {
      snprintf(value, sizeof value, "%s/%s", base,
               i >= 17 ? "health" : "state");
      str(e, "state_topic", value);
      snprintf(value, sizeof value, "{{ value_json.%s | default(none) }}",
               mqtt_entities[i].field);
      str(e, "value_template", value);
    }
    if (mqtt_entities[i].command) {
      snprintf(value, sizeof value, "%s/cmd/%s", base,
               mqtt_entities[i].command);
      str(e, "command_topic", value);
      boolean(e, "retain", 0);
      num(e, "qos", 0);
    }
    if (mqtt_entities[i].unit)
      str(e, "unit_of_measurement", mqtt_entities[i].unit);
    if (!strcmp(p, "switch")) {
      str(e, "payload_on", "{\"on\":true}");
      str(e, "payload_off", "{\"on\":false}");
      str(e, "state_on",
          (!strcmp(key, "power") || !strcmp(key, "screen")) ? "on" : "True");
      str(e, "state_off",
          !strcmp(key, "power")    ? "standby"
          : !strcmp(key, "screen") ? "off"
                                   : "False");
    } else if (!strcmp(p, "binary_sensor")) {
      str(e, "payload_on", "True");
      str(e, "payload_off", "False");
      if (!strcmp(key, "root_ok")) {
        str(e, "value_template", "{{ 'ON' if value_json.root_ok else 'OFF' }}");
        str(e, "payload_on", "ON");
        str(e, "payload_off", "OFF");
      }
    } else if (!strcmp(p, "select")) {
      J *options = features ? get(features, !strcmp(key, "app_select") ? "apps"
                                            : !strcmp(key, "source") ? "sources"
                                                                     : "")
                            : NULL;
      J *copy = json_object_new_array();
      if (options && json_object_is_type(options, 5))
        for (size_t k = 0; k < json_object_array_length(options); k++)
          json_object_array_add(copy,
                                json_object_new_string(json_object_get_string(
                                    json_object_array_get_idx(options, k))));
      json_object_object_add(e, "options", copy);
      const char *field = !strcmp(key, "source")         ? "input"
                          : !strcmp(key, "app_select")   ? "name"
                          : !strcmp(key, "picture_mode") ? "mode"
                                                         : "output";
      snprintf(value, sizeof value, "{{ {\"%s\": value} | to_json }}", field);
      str(e, "command_template", value);
    } else if (!strcmp(p, "number")) {
      num(e, "min", 0);
      num(e, "max", !strcmp(key, "volume") ? 100 : 1440);
      num(e, "step", 1);
      str(e, "mode", "slider");
      snprintf(value, sizeof value, "{{ {\"%s\": value | int} | to_json }}",
               !strcmp(key, "volume") ? "level" : "minutes");
      str(e, "command_template", value);
    } else if (!strcmp(p, "notify")) {
      str(e, "command_template",
          "{{ {\"title\": \"Home Assistant\", \"message\": value} | to_json "
          "}}");
    }
    json_object_object_add(components, key, e);
  }
  return d;
}
static J *mqtt_initial_state(void) {
  J *s = obj(), *signal = obj();
  const char *fields[] = {"power",          "screen",    "app_id",
                          "app_name",       "input",     "input_label",
                          "volume",         "muted",     "audio_output",
                          "picture_mode",   "game_mode", "kid_mode",
                          "telemetry_block"};
  for (size_t i = 0; i < sizeof fields / sizeof *fields; i++)
    json_object_object_add(s, fields[i], NULL);
  const char *signals[] = {"resolution", "refresh_hz", "hdr", "vrr", "allm"};
  for (size_t i = 0; i < sizeof signals / sizeof *signals; i++)
    json_object_object_add(signal, signals[i], NULL);
  json_object_object_add(s, "signal", signal);
  return s;
}
static J *mqtt_health(const MqttConfig *c) {
  J *j = obj();
  struct timespec up;
  if (!clock_gettime(CLOCK_BOOTTIME, &up))
    num(j, "uptime_s", up.tv_sec);
  else
    json_object_object_add(j, "uptime_s", NULL);
  const char *unknown[] = {"cpu_pct", "mem_used_pct", "wifi_rssi_dbm", "temp_c",
                           "firmware_update_pending"};
  for (size_t i = 0; i < sizeof unknown / sizeof *unknown; i++)
    json_object_object_add(j, unknown[i], NULL);
  str(j, "firmware", c->firmware);
  str(j, "agent_version", c->version);
  boolean(j, "root_ok", getuid() == 0 && geteuid() == 0);
  return j;
}
