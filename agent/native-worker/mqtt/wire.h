/* Bounded MQTT 3.1.1 subset, original 0BSD implementation. Outbound only.
 * Clean sessions, QoS 0 publications/subscriptions; no retransmission queue.
 * Every packet has a whole-frame deadline and all I/O observes cancellation. */
#define MQTT_PACKET_MAX 32768
static pthread_mutex_t mqtt_mutex = PTHREAD_MUTEX_INITIALIZER;
static int mqtt_stopping, mqtt_thread_started, mqtt_active;
static pthread_t mqtt_thread;
static MqttConfig mqtt_settings;
static int mqtt_cancelled(void) {
  pthread_mutex_lock(&mqtt_mutex);
  int v = mqtt_stopping;
  pthread_mutex_unlock(&mqtt_mutex);
  return v;
}
static void mqtt_log(const char *level, const char *code) {
  /* Both arguments are source-controlled constants; never log network input. */
  fprintf(stderr, "{\"component\":\"mqtt\",\"level\":\"%s\",\"code\":\"%s\"}\n",
          level, code);
}
static int mqtt_wait(int fd, short events, double until) {
  while (!mqtt_cancelled() && stamp() < until) {
    struct pollfd p = {fd, events, 0};
    int delay = (int)(until - stamp());
    if (delay > 100)
      delay = 100;
    if (delay < 1)
      delay = 1;
    int rc = poll(&p, 1, delay);
    if (rc < 0 && errno == EINTR)
      continue;
    if (rc < 0 || (rc && (p.revents & (POLLERR | POLLNVAL))))
      return 0;
    if (rc && (p.revents & (events | POLLHUP)))
      return 1;
  }
  return 0;
}
static int mqtt_io(int fd, void *data, size_t n, int writing, double until) {
  unsigned char *p = data;
  while (n && !mqtt_cancelled()) {
    if (!mqtt_wait(fd, writing ? POLLOUT : POLLIN, until))
      return 0;
    ssize_t k = writing ? send(fd, p, n, MSG_NOSIGNAL) : recv(fd, p, n, 0);
    if (k < 0 && (errno == EINTR || errno == EAGAIN))
      continue;
    if (k <= 0)
      return 0;
    p += k;
    n -= (size_t)k;
  }
  return !n;
}
static int mqtt_send(int fd, unsigned char type, const void *data, size_t n) {
  if (n > MQTT_PACKET_MAX)
    return 0;
  unsigned char header[5] = {type};
  size_t at = 1, left = n;
  do {
    unsigned char d = left % 128;
    left /= 128;
    header[at++] = d | (left ? 128 : 0);
  } while (left);
  double until = stamp() + 3000;
  return mqtt_io(fd, header, at, 1, until) &&
         mqtt_io(fd, (void *)data, n, 1, until);
}
static int mqtt_receive(int fd, unsigned char *type, unsigned char *out,
                        size_t *length) {
  double until = stamp() + 3000;
  unsigned char b;
  size_t n = 0, mult = 1;
  if (!mqtt_io(fd, type, 1, 0, until))
    return 0;
  for (int i = 0; i < 4; i++) {
    if (!mqtt_io(fd, &b, 1, 0, until))
      return 0;
    n += (b & 127) * mult;
    if (n > MQTT_PACKET_MAX)
      return 0;
    if (!(b & 128)) {
      if (i && b == 0)
        return 0;
      *length = n;
      return mqtt_io(fd, out, n, 0, until);
    }
    mult *= 128;
  }
  return 0;
}
static size_t mqtt_utf(unsigned char *p, const char *s) {
  size_t n = strlen(s);
  p[0] = n >> 8;
  p[1] = n & 255;
  memcpy(p + 2, s, n);
  return n + 2;
}
static int mqtt_publish(int fd, const char *topic, const char *value,
                        int retained) {
  size_t t = strlen(topic), v = strlen(value);
  if (t > 256 || t + v + 2 > MQTT_PACKET_MAX)
    return 0;
  unsigned char *p = allocate(t + v + 2);
  size_t n = mqtt_utf(p, topic);
  memcpy(p + n, value, v);
  int good = mqtt_send(fd, 0x30 | (retained ? 1 : 0), p, n + v);
  free(p);
  return good;
}
static int mqtt_publish_json(int fd, const char *topic, J *value,
                             int retained) {
  int good = mqtt_publish(fd, topic, json(value), retained);
  json_object_put(value);
  return good;
}
static int mqtt_connect(const MqttConfig *c) {
  int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
  if (fd < 0)
    return -1;
  struct sockaddr_in a = {.sin_family = AF_INET, .sin_port = htons(c->port)};
  inet_pton(AF_INET, c->host, &a.sin_addr);
  int rc = connect(fd, (struct sockaddr *)&a, sizeof a), err = 0;
  socklen_t len = sizeof err;
  if ((rc && errno != EINPROGRESS) || !mqtt_wait(fd, POLLOUT, stamp() + 3000) ||
      getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) || err) {
    close(fd);
    return -1;
  }
  unsigned char p[512] = {0, 4, 'M', 'Q', 'T', 'T', 4, 0xc6, 0, 30};
  size_t n = 10;
  char text[96];
  snprintf(text, sizeof text, "tv_%s", c->device);
  n += mqtt_utf(p + n, text);
  snprintf(text, sizeof text, "tv/%s/availability", c->device);
  n += mqtt_utf(p + n, text);
  n += mqtt_utf(p + n, "offline");
  n += mqtt_utf(p + n, c->user);
  n += mqtt_utf(p + n, c->password);
  /* username + password + clean session + retained QoS0 will. */
  p[7] |= 0x20;
  int good = mqtt_send(fd, 0x10, p, n);
  mqtt_wipe(p, sizeof p);
  unsigned char type, reply[MQTT_PACKET_MAX];
  size_t size;
  if (!good || !mqtt_receive(fd, &type, reply, &size) || type != 0x20 ||
      size != 2 || reply[0] || reply[1]) {
    close(fd);
    return -1;
  }
  unsigned char sub[128] = {0, 1};
  n = 2;
  n += mqtt_utf(sub + n, "homeassistant/status");
  sub[n++] = 0;
  snprintf(text, sizeof text, "tv/%s/cmd/+", c->device);
  n += mqtt_utf(sub + n, text);
  sub[n++] = 0;
  if (!mqtt_send(fd, 0x82, sub, n)) {
    close(fd);
    return -1;
  }
  /* MQTT permits retained publications before SUBACK. Discard this bounded
   * pre-admission stream; birth is covered by the unconditional snapshot. */
  double until = stamp() + 3000;
  for (int packets = 0; packets < 32 && stamp() < until; packets++) {
    if (!mqtt_receive(fd, &type, reply, &size))
      break;
    if (type == 0x90) {
      if (size == 4 && !reply[0] && reply[1] == 1 && !reply[2] && !reply[3])
        return fd;
      break;
    }
    if (type != 0x30 && type != 0x31)
      break;
  }
  close(fd);
  return -1;
}
