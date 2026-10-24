/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
/* Private files are opened descriptor-by-descriptor: no symlink, writable
 * ancestor, FIFO/device, hard link or pathname re-open after validation. */
static int mqtt_private_read(const char *path, char *out, size_t cap) {
  if (!path || path[0] != '/' || strlen(path) >= PATH_MAX)
    return 0;
  char copy[PATH_MAX];
  strcpy(copy, path + 1);
  int dir = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC), good = 0;
  char *part = copy;
  while (dir >= 0 && *part) {
    char *slash = strchr(part, '/');
    if (slash)
      *slash = 0;
    if (!*part || !strcmp(part, ".") || !strcmp(part, ".."))
      break;
    int fd = openat(dir, part,
                    O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC |
                        (slash ? O_DIRECTORY : 0));
    struct stat s;
    if (fd < 0)
      break;
    if (fstat(fd, &s) || s.st_uid ||
        (slash ? (!S_ISDIR(s.st_mode) || (s.st_mode & 022))
               : (!S_ISREG(s.st_mode) || (s.st_mode & 07777) != 0600 ||
                  s.st_nlink != 1 || s.st_size < 1 ||
                  (uint64_t)s.st_size >= cap))) {
      close(fd);
      break;
    }
    if (slash) {
      close(dir);
      dir = fd;
      part = slash + 1;
      continue;
    }
    size_t at = 0;
    ssize_t n;
    while (at < cap && (n = read(fd, out + at, cap - at)) > 0)
      at += (size_t)n;
    good = at == (size_t)s.st_size && at < cap && !memchr(out, 0, at);
    close(fd);
    if (good)
      out[at] = 0;
    break;
  }
  if (dir >= 0)
    close(dir);
  return good;
}
static void mqtt_wipe(void *v, size_t n) {
  volatile unsigned char *p = v;
  while (n--)
    *p++ = 0;
}
/* Exact flat JSON envelope; reject duplicate/escaped/unknown keys, nested
 * objects, trailing data and comments before json-c can normalize them away. */
static int mqtt_utf8(const unsigned char *p) {
  while (*p) {
    unsigned a = *p++;
    if (a < 128)
      continue;
    unsigned value, minimum;
    int remaining;
    if (a >= 0xc2 && a <= 0xdf) {
      value = a & 31;
      minimum = 0x80;
      remaining = 1;
    } else if (a >= 0xe0 && a <= 0xef) {
      value = a & 15;
      minimum = 0x800;
      remaining = 2;
    } else if (a >= 0xf0 && a <= 0xf4) {
      value = a & 7;
      minimum = 0x10000;
      remaining = 3;
    } else
      return 0;
    while (remaining--) {
      if ((*p & 0xc0) != 0x80)
        return 0;
      value = (value << 6) | (*p++ & 63);
    }
    if (value < minimum || value > 0x10ffff ||
        (value >= 0xd800 && value <= 0xdfff))
      return 0;
  }
  return 1;
}
static J *mqtt_object(const char *s, const char *const *keys, size_t count) {
  if (!s || count > 32 || !mqtt_utf8((const unsigned char *)s))
    return NULL;
  const char *p = s;
  uint32_t seen = 0;
  while (isspace((unsigned char)*p))
    p++;
  if (*p++ != '{')
    return NULL;
  while (isspace((unsigned char)*p))
    p++;
  if (*p != '}')
    for (;;) {
      if (*p++ != '"')
        return NULL;
      const char *key = p;
      while ((*p >= 'a' && *p <= 'z') || *p == '_')
        p++;
      if (*p != '"')
        return NULL;
      size_t i;
      for (i = 0; i < count; i++)
        if (strlen(keys[i]) == (size_t)(p - key) &&
            !strncmp(key, keys[i], p - key))
          break;
      if (i == count || (seen & (1u << i)))
        return NULL;
      seen |= 1u << i;
      p++;
      while (isspace((unsigned char)*p))
        p++;
      if (*p++ != ':')
        return NULL;
      while (isspace((unsigned char)*p))
        p++;
      if (*p == '"') {
        p++;
        while (*p && *p != '"') {
          if ((unsigned char)*p < 32)
            return NULL;
          if (*p == '\\') {
            p++;
            if (!*p)
              return NULL;
          }
          p++;
        }
        if (*p++ != '"')
          return NULL;
      } else {
        const char *start = p;
        while (*p && *p != ',' && *p != '}' && !isspace((unsigned char)*p)) {
          if (!strchr("-0123456789truefals", *p))
            return NULL;
          p++;
        }
        if (start == p)
          return NULL;
      }
      while (isspace((unsigned char)*p))
        p++;
      if (*p == '}')
        break;
      if (*p++ != ',')
        return NULL;
      while (isspace((unsigned char)*p))
        p++;
    }
  if (*p++ != '}')
    return NULL;
  while (isspace((unsigned char)*p))
    p++;
  return *p ? NULL : parse(s);
}
static int mqtt_boolean(J *j, const char *key, int fallback) {
  J *v = get(j, key);
  return !v                          ? fallback
         : json_object_is_type(v, 1) ? json_object_get_boolean(v)
                                     : -1;
}
static int mqtt_string(J *j, const char *key, char *out, size_t cap) {
  const char *s = textval(j, key);
  if (!s || !*s || strlen(s) >= cap)
    return 0;
  for (const unsigned char *p = (const unsigned char *)s; *p; p++)
    if (*p < 32 || *p == 127)
      return 0;
  strcpy(out, s);
  return 1;
}
typedef struct {
  char device[8], name[96], host[INET_ADDRSTRLEN], credentials[PATH_MAX];
  char user[32], password[33], firmware[96], version[32];
  int port, enabled, state;
} MqttConfig;
static int mqtt_config(const char *path, const char *device,
                       const char *firmware, const char *version,
                       MqttConfig *c) {
  char raw[8192];
  memset(c, 0, sizeof *c);
  if (!mqtt_private_read(path, raw, sizeof raw))
    return 0;
  const char *keys[] = {"device",         "device_name",      "broker_host",
                        "broker_port",    "credentials_file", "enabled",
                        "state",          "control",          "events",
                        "notifications",  "kid_mode",         "resilience",
                        "telemetry_block"};
  J *j = mqtt_object(raw, keys, sizeof keys / sizeof *keys);
  mqtt_wipe(raw, sizeof raw);
  if (!j)
    return 0;
  struct in_addr addr;
  int64_t port = 0;
  integer(j, "broker_port", &port);
  int good =
      mqtt_string(j, "device", c->device, sizeof c->device) &&
      (!strcmp(c->device, "qn90a") || !strcmp(c->device, "s90d")) &&
      !strcmp(c->device, device) &&
      mqtt_string(j, "device_name", c->name, sizeof c->name) &&
      mqtt_string(j, "broker_host", c->host, sizeof c->host) &&
      inet_pton(AF_INET, c->host, &addr) == 1 && port > 0 && port <= 65535 &&
      mqtt_string(j, "credentials_file", c->credentials, sizeof c->credentials);
  c->port = (int)port;
  c->enabled = mqtt_boolean(j, "enabled", 1);
  c->state = mqtt_boolean(j, "state", 1);
  for (size_t i = 6; i < sizeof keys / sizeof *keys; i++) {
    int value = mqtt_boolean(j, keys[i], i < 10);
    if (value < 0 || (i >= 10 && value))
      good = 0; /* Later features cannot be enabled yet. */
  }
  if (c->enabled < 0 || !firmware || strlen(firmware) >= sizeof c->firmware ||
      !version || strlen(version) >= sizeof c->version)
    good = 0;
  if (good) {
    strcpy(c->firmware, firmware);
    strcpy(c->version, version);
  }
  json_object_put(j);
  if (!good)
    return 0;
  if (!c->enabled)
    return 1;
  if (!mqtt_private_read(c->credentials, raw, sizeof raw))
    return 0;
  char expected[64];
  snprintf(expected, sizeof expected, "MQTT_USER=tv-%s", c->device);
  char *line = strchr(raw, '\n');
  good = line != NULL;
  if (good) {
    *line++ = 0;
    size_t n = strlen(raw);
    if (n && raw[n - 1] == '\r')
      raw[n - 1] = 0;
    good = !strcmp(raw, expected) && !strncmp(line, "MQTT_PASSWORD=", 14);
    if (good) {
      char *pw = line + 14;
      n = strlen(pw);
      if (n && pw[n - 1] == '\n')
        pw[--n] = 0;
      if (n && pw[n - 1] == '\r')
        pw[--n] = 0;
      good = n == 32;
      for (size_t i = 0; i < n; i++)
        if ((unsigned char)pw[i] < 33 || (unsigned char)pw[i] > 126)
          good = 0;
      if (good) {
        snprintf(c->user, sizeof c->user, "tv-%s", c->device);
        memcpy(c->password, pw, 33);
      }
    }
  }
  mqtt_wipe(raw, sizeof raw);
  return good;
}
