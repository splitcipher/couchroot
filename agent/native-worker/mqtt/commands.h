/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
static int mqtt_text(J *j, const char *key, size_t limit) {
  const char *s = textval(j, key);
  if (!s || !*s || strlen(s) > limit)
    return 0;
  for (const unsigned char *p = (const unsigned char *)s; *p; p++)
    if (*p < 32 || *p == 127)
      return 0;
  return 1;
}
static int mqtt_range(J *j, const char *key, int lo, int hi) {
  int64_t n;
  return integer(j, key, &n) && n >= lo && n <= hi;
}
static int mqtt_choice(const char *s, const char *const *choices,
                       size_t count) {
  for (size_t i = 0; s && i < count; i++)
    if (!strcmp(s, choices[i]))
      return 1;
  return 0;
}
static int mqtt_id(J *j) {
  if (!get(j, "id"))
    return 1;
  const char *s = textval(j, "id");
  if (!s || !*s || strlen(s) > 64)
    return 0;
  for (; *s; s++)
    if (!isalnum((unsigned char)*s) && !strchr("_.:-", *s))
      return 0;
  return 1;
}
/* Returns only validated data. No command is turned into shell text, EXEC,
 * a path, a generic worker OP, or a public API call. */
static J *mqtt_command(const char *name, const char *raw, const char **error) {
  const char *keys[8] = {"id"};
  size_t n = 1;
  int type = 0;
  const char *bools[] = {"power",     "screen",   "mute",
                         "game_mode", "kid_mode", "telemetry_block"};
  if (mqtt_choice(name, bools, 6)) {
    keys[n++] = "on";
    type = 1;
  } else if (!strcmp(name, "source")) {
    keys[n++] = "input";
    type = 2;
  } else if (!strcmp(name, "launch_app")) {
    keys[n++] = "app_id";
    keys[n++] = "name";
    keys[n++] = "deep_link";
    type = 3;
  } else if (!strcmp(name, "volume")) {
    keys[n++] = "level";
    type = 4;
  } else if (!strcmp(name, "picture_mode")) {
    keys[n++] = "mode";
    type = 5;
  } else if (!strcmp(name, "audio_output")) {
    keys[n++] = "output";
    type = 5;
  } else if (!strcmp(name, "sleep_timer")) {
    keys[n++] = "minutes";
    type = 6;
  } else if (!strcmp(name, "key")) {
    keys[n++] = "key";
    type = 7;
  } else if (!strcmp(name, "notify")) {
    keys[n++] = "title";
    keys[n++] = "message";
    keys[n++] = "image_url";
    keys[n++] = "duration_s";
    keys[n++] = "position";
    type = 8;
  } else {
    *error = "unknown_command";
    return NULL;
  }
  *error = "invalid_payload";
  J *j = mqtt_object(raw, keys, n);
  if (!j)
    return NULL;
  int good = mqtt_id(j);
  const char *inputs[] = {"tv", "hdmi1", "hdmi2", "hdmi3", "hdmi4"};
  const char *remote[] = {
      "UP",         "DOWN",         "LEFT",      "RIGHT",       "ENTER",
      "RETURN",     "HOME",         "PLAY",      "PAUSE",       "STOP",
      "REWIND",     "FAST_FORWARD", "VOLUME_UP", "VOLUME_DOWN", "MUTE",
      "CHANNEL_UP", "CHANNEL_DOWN"};
  const char *positions[] = {"top_left", "top_right", "bottom_left",
                             "bottom_right"};
  switch (type) {
  case 1:
    good = good && mqtt_boolean(j, "on", -1) >= 0;
    break;
  case 2:
    good = good && mqtt_choice(textval(j, "input"), inputs, 5);
    break;
  case 3:
    good = good && (!!get(j, "app_id") != !!get(j, "name")) &&
           (get(j, "app_id") ? mqtt_text(j, "app_id", 256)
                             : mqtt_text(j, "name", 128)) &&
           (!get(j, "deep_link") || mqtt_text(j, "deep_link", 1024));
    break;
  case 4:
    good = good && mqtt_range(j, "level", 0, 100);
    break;
  case 5:
    good = good && mqtt_text(j, keys[1], 64);
    break;
  case 6:
    good = good && mqtt_range(j, "minutes", 0, 1440);
    break;
  case 7:
    good = good && mqtt_choice(textval(j, "key"), remote,
                               sizeof remote / sizeof *remote);
    break;
  case 8:
    good = good && mqtt_text(j, "title", 128) &&
           mqtt_text(j, "message", 1024) &&
           (!get(j, "duration_s") || mqtt_range(j, "duration_s", 1, 60)) &&
           (!get(j, "position") ||
            mqtt_choice(textval(j, "position"), positions, 4));
    if (get(j, "image_url"))
      good = good && mqtt_text(j, "image_url", 1024) &&
             !strncmp(textval(j, "image_url"), "https://", 8);
    break;
  }
  if (!good) {
    json_object_put(j);
    return NULL;
  }
  *error = NULL;
  return j;
}
