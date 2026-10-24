/* Original Couchroot code. SPDX-License-Identifier: 0BSD
 * Same aggregate CPU and MemAvailable semantics as
 * telemetry/s90d/nas/metrics.py. No guest double count, RSS sum, cache
 * subtraction or counter-wrap guess. */
typedef struct {
  uint64_t counters[8];
  double at;
  int valid;
} MqttCpu;
static int mqtt_cpu_parse(const char *raw, uint64_t values[8]) {
  if (!raw || strncmp(raw, "cpu ", 4))
    return 0;
  const char *p = raw + 4;
  for (int i = 0; i < 8; i++) {
    while (*p == ' ' || *p == '\t')
      p++;
    if (!isdigit((unsigned char)*p))
      return 0;
    char *end;
    errno = 0;
    unsigned long long value = strtoull(p, &end, 10);
    if (errno || (*end != ' ' && *end != '\t' && *end != '\n' && *end))
      return 0;
    values[i] = value;
    p = end;
  }
  return 1;
}
static J *mqtt_cpu_sample(MqttCpu *previous, const char *raw, double now) {
  uint64_t values[8];
  if (!mqtt_cpu_parse(raw, values)) {
    previous->valid = 0;
    return NULL;
  }
  int good =
      previous->valid && now > previous->at && now - previous->at <= 45000;
  long double total = 0, idle = 0;
  for (int i = 0; i < 8; i++) {
    if (values[i] < previous->counters[i])
      good = 0;
    long double delta = values[i] >= previous->counters[i]
                            ? values[i] - previous->counters[i]
                            : 0;
    total += delta;
    if (i == 3 || i == 4)
      idle += delta;
  }
  memcpy(previous->counters, values, sizeof values);
  previous->at = now;
  previous->valid = 1;
  return good && total > 0
             ? json_object_new_double((double)(100 * (total - idle) / total))
             : NULL;
}
static int mqtt_mem_value(const char *raw, const char *key, uint64_t *value) {
  if (!raw)
    return 0;
  size_t keylen = strlen(key);
  int found = 0;
  for (const char *line = raw; line && *line;) {
    if (!strncmp(line, key, keylen)) {
      if (found++)
        return 0;
      const char *p = line + keylen;
      while (*p == ' ' || *p == '\t')
        p++;
      if (!isdigit((unsigned char)*p))
        return 0;
      char *end;
      errno = 0;
      *value = strtoull(p, &end, 10);
      if (errno)
        return 0;
      while (*end == ' ' || *end == '\t')
        end++;
      if (strncmp(end, "kB", 2) || (end[2] && end[2] != '\n'))
        return 0;
    }
    line = strchr(line, '\n');
    if (line)
      line++;
  }
  return found == 1;
}
static J *mqtt_memory_sample(const char *raw) {
  uint64_t total, available;
  if (!mqtt_mem_value(raw, "MemTotal:", &total) ||
      !mqtt_mem_value(raw, "MemAvailable:", &available) || !total ||
      available > total)
    return NULL;
  return json_object_new_double(100.0 * (double)(total - available) /
                                (double)total);
}
/* Fixed kernel paths only. A short first /proc/stat line is sufficient even on
 * hosts with huge per-CPU tables. meminfo must fit and terminate completely. */
static int mqtt_proc_read(const char *path, char *out, size_t cap,
                          int first_line) {
  if (!mqtt_fd_lock(1))
    return 0;
  int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
  mqtt_fd_unlock();
  if (fd < 0)
    return 0;
  size_t used = 0;
  int good = 0;
  while (used < cap - 1) {
    ssize_t n = read(fd, out + used, cap - 1 - used);
    if (n < 0 && errno == EINTR)
      continue;
    if (n <= 0) {
      good = n == 0;
      break;
    }
    used += (size_t)n;
    if (first_line && memchr(out, '\n', used)) {
      good = 1;
      break;
    }
  }
  close(fd);
  out[used] = 0;
  return good && used && !memchr(out, 0, used);
}
