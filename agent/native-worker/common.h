/* Original Couchroot experimental worker utilities. SPDX-License-Identifier:
 * 0BSD */
#ifndef COUCHROOT_NATIVE_COMMON_H
#define COUCHROOT_NATIVE_COMMON_H
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <arpa/inet.h>
#include <assert.h>
#include <ctype.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#ifdef COUCHROOT_NATIVE_WORKER
#include "descriptor-budget.h"
#endif
#define CHUNK 1048576
#define FRAME (8 * CHUNK)
#define PREAUTH_BYTES 512
static int exec_timeout_valid(int64_t timeout, int bootstrap) { return timeout >= 100 && timeout <= (bootstrap ? 25000 : 300000); }
#define LIMIT INT64_C(2147483648)
typedef void J;
#define JSON_APIS(X)                                                           \
  X(J *, json_object_new_object, (void))                                       \
  X(J *, json_object_new_array, (void))                                        \
  X(J *, json_object_new_string, (const char *))                               \
  X(J *, json_object_new_string_len, (const char *, int))                      \
  X(J *, json_object_new_int64, (int64_t))                                     \
  X(J *, json_object_new_boolean, (int))                                       \
  X(J *, json_object_new_double, (double))                                     \
  X(int, json_object_object_add, (J *, const char *, J *))                     \
  X(size_t, json_object_array_length, (const J *))                             \
  X(J *, json_object_array_get_idx, (const J *, size_t))                        \
  X(int, json_object_array_add, (J *, J *))                                    \
  X(int, json_object_object_get_ex, (const J *, const char *, J **))           \
  X(const char *, json_object_get_string, (J *))                               \
  X(int, json_object_get_string_len, (const J *))                              \
  X(int64_t, json_object_get_int64, (const J *))                               \
  X(int, json_object_get_boolean, (const J *))                                 \
  X(int, json_object_is_type, (const J *, int))                                \
  X(const char *, json_object_to_json_string_ext, (J *, int))                  \
  X(int, json_object_put, (J *))                                               \
  X(J *, json_tokener_parse_verbose, (const char *, int *))
#define DECL(ret, name, args) static ret(*name) args;
JSON_APIS(DECL)
#undef DECL
static void *(*md_new)(void);
static void (*md_free)(void *);
static const void *(*md_sha)(void);
static int (*md_init)(void *, const void *, void *),
    (*md_update)(void *, const void *, size_t),
    (*md_final)(void *, unsigned char *, unsigned *);
static unsigned char *(*hmac_fn)(const void *, const void *, int,
                                 const unsigned char *, size_t, unsigned char *,
                                 unsigned *);
static void fatal(const char *s) {
  fprintf(stderr, "prototype: %s (%s)\n", s, strerror(errno));
  exit(1);
}
static void *allocate(size_t n) {
  void *p = calloc(1, n ? n : 1);
  if (!p)
    fatal("allocation");
  return p;
}
static void symbol(void *lib, void *out, const char *name) {
  void *p = dlsym(lib, name);
  if (!p)
    fatal(name);
  memcpy(out, &p, sizeof p);
}
static void libraries(void) {
  void *j = dlopen("libjson-c.so.5", RTLD_NOW | RTLD_LOCAL);
  if (!j)
    j = dlopen("libjson-c.so.4", RTLD_NOW | RTLD_LOCAL);
  if (!j)
    fatal("json-c unavailable");
#define LOAD(ret, name, args) symbol(j, &name, #name);
  JSON_APIS(LOAD)
#undef LOAD
  void *c = dlopen("libcrypto.so.1.1", RTLD_NOW | RTLD_LOCAL);
  if (!c)
    c = dlopen("libcrypto.so.3", RTLD_NOW | RTLD_LOCAL);
  if (!c)
    fatal("libcrypto unavailable");
  symbol(c, &md_new, "EVP_MD_CTX_new");
  symbol(c, &md_free, "EVP_MD_CTX_free");
  symbol(c, &md_sha, "EVP_sha256");
  symbol(c, &md_init, "EVP_DigestInit_ex");
  symbol(c, &md_update, "EVP_DigestUpdate");
  symbol(c, &md_final, "EVP_DigestFinal_ex");
  symbol(c, &hmac_fn, "HMAC");
}
static double stamp(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t))
    fatal("clock");
  return t.tv_sec * 1000.0 + t.tv_nsec / 1e6;
}
static void writeall(int fd, const void *v, size_t n) {
  const unsigned char *p = v;
  while (n) {
    ssize_t k = write(fd, p, n);
    if (k < 0 && errno == EINTR)
      continue;
    if (k <= 0)
      fatal("write");
    p += k;
    n -= k;
  }
}
static void random_bytes(void *p, size_t n) {
  int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
  if (fd < 0)
    fatal("random");
  size_t at = 0;
  while (at < n) {
    ssize_t k = read(fd, (char *)p + at, n - at);
    if (k <= 0)
      fatal("random read");
    at += k;
  }
  close(fd);
}
static void hex(const unsigned char *p, size_t n, char *out) {
  static const char digits[] = "0123456789abcdef";
  for (size_t i = 0; i < n; i++) {
    out[2 * i] = digits[p[i] >> 4];
    out[2 * i + 1] = digits[p[i] & 15];
  }
  out[2 * n] = 0;
}
static int hexvalid(const char *p, size_t n) {
  if (!p || strlen(p) != n)
    return 0;
  for (size_t i = 0; i < n; i++)
    if (!strchr("0123456789abcdef", p[i]))
      return 0;
  return 1;
}
static int unhex(const char *s, unsigned char *p, size_t n) {
  if (!hexvalid(s, n * 2))
    return 0;
  for (size_t i = 0; i < n; i++) {
    unsigned a, b;
    char c[2] = {s[2 * i], 0}, d[2] = {s[2 * i + 1], 0};
    a = (unsigned)strtoul(c, NULL, 16);
    b = (unsigned)strtoul(d, NULL, 16);
    p[i] = (a << 4) | b;
  }
  return 1;
}
static void *digest_start(void) {
  void *m = md_new();
  if (!m || !md_init(m, md_sha(), NULL))
    fatal("digest init");
  return m;
}
static void digest_finish(void *m, char out[65]) {
  unsigned char d[32];
  unsigned n = 0;
  if (!md_final(m, d, &n) || n != 32)
    fatal("digest final");
  md_free(m);
  hex(d, 32, out);
}
static void digest(const void *p, size_t n, char out[65]) {
  void *m = digest_start();
  if (!md_update(m, p, n))
    fatal("digest update");
  digest_finish(m, out);
}
static int filedigest_progress(int fd, char out[65], void (*progress)(void)) {
  unsigned char b[65536];
  struct stat before, after;
  if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size < 0 ||
      before.st_size > LIMIT)
    return 0;
  off_t at = 0;
  void *m = digest_start();
  /* Bound work to the initial file size. A growing file must not turn progress
   * notifications into an unbounded request. In-place edits still require the
   * caller to quiesce external writers; this is not a snapshot guarantee. */
  while (at < before.st_size) {
    size_t wanted = before.st_size - at > (off_t)sizeof b
                        ? sizeof b : (size_t)(before.st_size - at);
    ssize_t n = pread(fd, b, wanted, at);
    if (n < 0 && errno == EINTR)
      continue;
    if (n <= 0) {
      md_free(m);
      return 0;
    }
    if (!md_update(m, b, n))
      fatal("digest update");
    at += n;
    if (progress)
      progress();
  }
  if (fstat(fd, &after) || after.st_size != before.st_size) {
    md_free(m);
    return 0;
  }
  digest_finish(m, out);
  return 1;
}
static int filedigest(int fd, char out[65]) {
  return filedigest_progress(fd, out, NULL);
}
static char *base64(const void *v, size_t n) {
  static const char a[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const unsigned char *p = v;
  char *s = allocate((n + 2) / 3 * 4 + 1);
  size_t j = 0;
  for (size_t i = 0; i < n; i += 3) {
    unsigned x = (unsigned)p[i] << 16;
    if (i + 1 < n)
      x |= (unsigned)p[i + 1] << 8;
    if (i + 2 < n)
      x |= p[i + 2];
    s[j++] = a[x >> 18];
    s[j++] = a[(x >> 12) & 63];
    s[j++] = i + 1 < n ? a[(x >> 6) & 63] : '=';
    s[j++] = i + 2 < n ? a[x & 63] : '=';
  }
  return s;
}
static int b64val(char c) {
  const char
      *a = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
      *p = strchr(a, c);
  return c && p ? (int)(p - a) : -1;
}
static unsigned char *decode(const char *s, size_t *length) {
  size_t n = strlen(s);
  if (n % 4 || n > FRAME)
    return NULL;
  unsigned char *p = allocate(n / 4 * 3 + 1);
  size_t j = 0;
  for (size_t i = 0; i < n; i += 4) {
    int a = b64val(s[i]), b = b64val(s[i + 1]),
        c = s[i + 2] == '=' ? 0 : b64val(s[i + 2]),
        d = s[i + 3] == '=' ? 0 : b64val(s[i + 3]);
    if (a < 0 || b < 0 || c < 0 || d < 0 ||
        (s[i + 2] == '=' && s[i + 3] != '=') ||
        ((s[i + 2] == '=' || s[i + 3] == '=') && i + 4 != n) ||
        (s[i + 2] == '=' && (b & 15)) ||
        (s[i + 3] == '=' && s[i + 2] != '=' && (c & 3))) {
      free(p);
      return NULL;
    }
    unsigned v = (a << 18) | (b << 12) | (c << 6) | d;
    p[j++] = v >> 16;
    if (s[i + 2] != '=')
      p[j++] = v >> 8;
    if (s[i + 3] != '=')
      p[j++] = v;
  }
  *length = j;
  return p;
}
static char *format(const char *fmt, ...) {
  va_list a;
  va_start(a, fmt);
  char *p = NULL;
  if (vasprintf(&p, fmt, a) < 0)
    fatal("format");
  va_end(a);
  return p;
}
static J *obj(void) { return json_object_new_object(); }
static void str(J *j, const char *k, const char *v) {
  json_object_object_add(j, k, json_object_new_string(v));
}
static void num(J *j, const char *k, int64_t v) {
  json_object_object_add(j, k, json_object_new_int64(v));
}
static void boolean(J *j, const char *k, int v) {
  json_object_object_add(j, k, json_object_new_boolean(v));
}
static J *get(J *j, const char *key) {
  J *v = NULL;
  json_object_object_get_ex(j, key, &v);
  return v;
}
static const char *textval(J *j, const char *key) {
  J *v = get(j, key);
  if (!v || !json_object_is_type(v, 6))
    return NULL;
  const char *s = json_object_get_string(v);
  return strlen(s) == (size_t)json_object_get_string_len(v) ? s : NULL;
}
static int integer(J *j, const char *key, int64_t *out) {
  J *v = get(j, key);
  if (!v || !json_object_is_type(v, 3))
    return 0;
  *out = json_object_get_int64(v);
  return 1;
}
static int64_t number(J *j, const char *key) {
  int64_t n;
  if (!integer(j, key, &n))
    fatal(key);
  return n;
}
static const char *json(J *j) { return json_object_to_json_string_ext(j, 0); }
static J *parse(const char *s) {
  /* Reject extra documents/trailing bytes, embedded NUL is checked by caller.
   */
  int depth = 0, quoted = 0, escape = 0, done = 0;
  const char *start = s;
  while (isspace((unsigned char)*start))
    start++;
  if (*start != '{')
    return NULL;
  for (const char *p = start; *p; p++) {
    if (done) {
      if (!isspace((unsigned char)*p))
        return NULL;
      continue;
    }
    if (quoted) {
      if (escape)
        escape = 0;
      else if (*p == '\\')
        escape = 1;
      else if (*p == '"')
        quoted = 0;
      continue;
    }
    if (*p == '"')
      quoted = 1;
    else if (*p == '{' || *p == '[') {
      if (++depth > 32)
        return NULL;
    } else if (*p == '}' || *p == ']') {
      if (--depth < 0)
        return NULL;
      if (!depth)
        done = 1;
    }
  }
  if (!done || quoted)
    return NULL;
  int error = 0;
  J *j = json_tokener_parse_verbose(s, &error);
  if (error || !j || !json_object_is_type(j, 4)) {
    if (j)
      json_object_put(j);
    return NULL;
  }
  return j;
}
typedef struct {
  int fd;
  unsigned char buffer[65536], nonce[32], secret[32];
  size_t at, end;
} Wire;
static void exact(Wire *w, void *v, size_t n) {
  unsigned char *p = v;
  while (n) {
    if (w->at == w->end) {
      ssize_t k = read(w->fd, w->buffer, sizeof w->buffer);
      if (k < 0 && errno == EINTR)
        continue;
      if (k <= 0)
        fatal("truncated wire");
      w->at = 0;
      w->end = k;
    }
    size_t k = w->end - w->at;
    if (k > n)
      k = n;
    memcpy(p, w->buffer + w->at, k);
    w->at += k;
    p += k;
    n -= k;
  }
}
static char *bounded_line(Wire *w, size_t maximum) {
  size_t n = 0, cap = 4096;
  char *p = allocate(cap);
  for (;;) {
    unsigned char c;
    exact(w, &c, 1);
    if (c == '\n')
      break;
    if (!c || n == maximum)
      fatal("invalid frame length");
    if (n + 1 == cap) {
      cap *= 2;
      char *q = realloc(p, cap);
      if (!q)
        fatal("line allocation");
      p = q;
    }
    p[n++] = c;
  }
  p[n] = 0;
  return p;
}
static char *line(Wire *w) { return bounded_line(w, FRAME); }
static void mac(Wire *w, const char *payload, char out[65]) {
  size_t n = strlen(payload);
  unsigned char *m = allocate(33 + n), d[32];
  memcpy(m, w->nonce, 32);
  memcpy(m + 33, payload, n);
  unsigned len = 0;
  if (!hmac_fn(md_sha(), w->secret, 32, m, 33 + n, d, &len) || len != 32)
    fatal("HMAC");
  free(m);
  hex(d, 32, out);
}
static void sendframe(Wire *w, const char *p) {
  char h[65];
  mac(w, p, h);
  writeall(w->fd, p, strlen(p));
  writeall(w->fd, "\t", 1);
  writeall(w->fd, h, 64);
  writeall(w->fd, "\n", 1);
}
static char *receive(Wire *w) {
  char *p = line(w), *sep = strrchr(p, '\t');
  if (!sep)
    fatal("missing MAC");
  *sep++ = 0;
  char h[65];
  mac(w, p, h);
  if (strlen(sep) != 64)
    fatal("MAC length");
  unsigned diff = 0;
  for (int i = 0; i < 64; i++)
    diff |= (unsigned char)h[i] ^ (unsigned char)sep[i];
  if (diff)
    fatal("bad MAC");
  return p;
}
static int fields(char *p, char **f, int max) {
  int n = 0;
  for (;;) {
    if (n == max)
      return -1;
    f[n++] = p;
    char *s = strchr(p, '\t');
    if (!s)
      return n;
    *s = 0;
    p = s + 1;
  }
}
static int decimal(const char *s, int64_t *out) {
  if (!s || !*s)
    return 0;
  for (const char *p = s; *p; p++)
    if (*p < '0' || *p > '9')
      return 0;
  errno = 0;
  char *end;
  long long v = strtoll(s, &end, 10);
  if (errno || *end || v < 0)
    return 0;
  *out = v;
  return 1;
}
static void readtext(const char *path, char *out, size_t size) {
  int fd = open(path, O_RDONLY | O_CLOEXEC);
  if (fd < 0)
    fatal("read text");
  ssize_t n = read(fd, out, size - 1);
  close(fd);
  if (n < 0)
    fatal("read text");
  out[n] = 0;
  while (n > 0 && isspace((unsigned char)out[n - 1]))
    out[--n] = 0;
}
#endif
