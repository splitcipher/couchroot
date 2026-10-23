/* Native is the only packaged worker; no managed fallback is attempted.
 * Original Couchroot code. SPDX-License-Identifier: 0BSD */
#define COUCHROOT_NATIVE_WORKER 1
#include "common.h"
#include "fault-events.h"
#include "progress.h"
#include "request-io.h"
#include <dirent.h>
#include <pthread.h>
typedef struct {
  int fd, upload, parent;
  char id[33], name[256], temp[48], sha[65], expected[65], path[PATH_MAX];
  int64_t size;
} Transfer;
static Transfer transfers[8];
static unsigned lifetime_seconds = 300;
static int production_mode, bootstrap_mode;
static char worker_start_ticks[32], guardian_start_ticks[32];
static int directory = -1;
static char root[PATH_MAX], launcher[PATH_MAX], launcher_sha[65], worker_id[33];
/* Hash of the private launch token, not the token itself. It binds every
 * startup checkpoint to the coordinator's durable attempt before readiness. */
static char startup_token_sha256[65];
#include "file-policy.h"
static volatile sig_atomic_t active_child = 0;
/* Async-signal-safe. Callers keep the leader unreaped until after this group
 * kill, so a recycled PID can never become the target. */
static void kill_group(pid_t pid) {
  kill(-pid, SIGKILL);
  kill(pid, SIGKILL);
}
static int wait_code(int status) {
  return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
/* Milliseconds until a monotonic stamp, rounded up and bounded for poll(). */
static int wait_ms(double until, int cap) {
  double left = until - stamp();
  return left <= 0 ? 0 : left >= cap ? cap : (int)left + 1;
}
/* Directory stream for an already-opened directory; the caller's descriptor
 * stays open and owned by the caller. */
static DIR *scan_directory(int dir) {
  int scan = openat(dir, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  DIR *d = scan < 0 ? NULL : fdopendir(scan);
  if (!d && scan >= 0)
    close(scan);
  return d;
}
/* Lifecycle signals are delivered only to the protocol thread or guardian. */
static void lifecycle_signals(sigset_t *set) {
  sigemptyset(set);
  sigaddset(set, SIGTERM);
  sigaddset(set, SIGINT);
  sigaddset(set, SIGALRM);
}
static void start_thread(pthread_t *thread, void *(*body)(void *), int *started,
                         const char *what) {
  sigset_t blocked, previous;
  lifecycle_signals(&blocked);
  if (pthread_sigmask(SIG_BLOCK, &blocked, &previous))
    fatal(what);
  int error = pthread_create(thread, NULL, body, NULL);
  if (!error)
    *started = 1;
  if (pthread_sigmask(SIG_SETMASK, &previous, NULL) || error)
    fatal(what);
}
static void release(Transfer *t) {
  if (t->fd >= 0)
    close(t->fd);
  if (t->temp[0])
    unlinkat(t->parent >= 0 ? t->parent : directory, t->temp, 0);
  if (t->parent >= 0)
    close(t->parent);
  memset(t, 0, sizeof *t);
  t->fd = t->parent = -1;
}
static void jobs_cleanup(void);
static void helpers_cleanup(void);
static void runtime_cleanup(void);
static void containment_worker_stop(void);
static void cleanup(void) {
  if (active_child > 0) {
    pid_t pid = active_child;
    kill_group(pid);
    active_child = 0;
    while (waitpid(pid, NULL, 0) < 0 && errno == EINTR) {
    }
  }
  runtime_cleanup();
  jobs_cleanup();
  containment_worker_stop();
  for (int i = 0; i < 8; i++)
    release(&transfers[i]);
  if (directory >= 0)
    close(directory);
}
static int leaf(const char *path, const char **name) {
  size_t n = strlen(root);
  if (!path || strncmp(path, root, n) || path[n] != '/')
    return 0;
  const char *p = path + n + 1;
  if (!*p || strlen(p) > 255 || strchr(p, '/') || !strcmp(p, ".") ||
      !strcmp(p, "..") || !strcmp(p, ".jobs") || !strcmp(p, ".views") ||
      !strncmp(p, ".upload-", 8))
    return 0;
  *name = p;
  return 1;
}
static int regular(int fd, int64_t *size) {
  struct stat s;
  if (fstat(fd, &s) || !S_ISREG(s.st_mode) || s.st_size < 0 ||
      s.st_size > LIMIT)
    return 0;
  *size = s.st_size;
  return 1;
}
static Transfer *lookup(const char *id) {
  for (int i = 0; i < 8; i++)
    if (id && transfers[i].fd >= 0 && !strcmp(id, transfers[i].id))
      return &transfers[i];
  return NULL;
}
static J *failure(const char *s) {
  J *j = obj();
  boolean(j, "ok", 0);
  str(j, "error", s);
  str(j, "outcome", "failed");
  return j;
}
static J *success(J *value) {
  J *j = obj();
  boolean(j, "ok", 1);
  json_object_object_add(j, "result", value);
  return j;
}
static J *snapshot(Transfer *t) {
  J *j = obj();
  str(j, "transfer_id", t->id);
  num(j, "size", t->size);
  str(j, "sha256", t->sha);
  if (t->upload)
    str(j, "expected_sha256", t->expected);
  else
    json_object_object_add(j, "expected_sha256", NULL);
  num(j, "chunk_bytes", CHUNK);
  int64_t size;
  if (!regular(t->fd, &size))
    fatal("transfer stat");
  num(j, "offset", size);
  boolean(j, "upload", t->upload);
  str(j, "path", t->path);
  return j;
}
static J *writechunk(const char *id, int64_t offset, const unsigned char *data,
                     size_t length, const char *sha) {
  Transfer *t = lookup(id);
  if (!t)
    return failure("Unknown transfer");
  if (!t->upload)
    return failure("Not an upload");
  char actual[65];
  digest(data, length, actual);
  if (!length || length > CHUNK || !sha || strcmp(actual, sha))
    return failure("Invalid chunk digest");
  int64_t size;
  if (!regular(t->fd, &size))
    return failure("Transfer stat failed");
  if (offset != size || offset < 0 || length > (uint64_t)(t->size - offset) ||
      offset > t->size)
    return failure("Offset conflict");
  size_t at = 0;
  while (at < length) {
    ssize_t n = request_pwrite(t->fd, data + at, length - at, offset + at);
    if (n < 0 && errno == EINTR)
      continue;
    if (n <= 0)
      return failure("Chunk write failed; inspect offset");
    at += n;
  }
  if (request_sync(t->fd))
    return failure("Chunk flush failed; inspect offset");
  J *j = obj();
  num(j, "offset", offset + length);
  return success(j);
}
typedef struct {
  unsigned char *out, *err;
  size_t outlen, errlen;
  int code, timed, truncated;
} Result;
static Result execute(const char *command, int timeout, int app) {
  Result r = {0};
  r.out = allocate(CHUNK + 1);
  r.err = allocate(CHUNK + 128);
  int pipes[2][2];
  if (pipe2(pipes[0], O_CLOEXEC) || pipe2(pipes[1], O_CLOEXEC))
    fatal("pipe");
  pid_t pid = fork();
  if (pid < 0)
    fatal("fork");
  if (!pid) {
    if (setsid() < 0)
      _exit(126);
    if (dup2(pipes[0][1], 1) < 0 || dup2(pipes[1][1], 2) < 0)
      _exit(126);
    int null = open("/dev/null", O_RDONLY);
    if (null < 0 || dup2(null, 0) < 0)
      _exit(126);
    close(null);
    for (int i = 0; i < 2; i++) {
      close(pipes[i][0]);
      close(pipes[i][1]);
    }
    if (app)
      execve(launcher,
             (char *const[]){launcher, "--command", (char *)command, NULL},
             environ);
    else
      execve("/bin/sh", (char *const[]){"sh", "-c", (char *)command, NULL},
             environ);
    _exit(127);
  }
  active_child = pid;
  close(pipes[0][1]);
  close(pipes[1][1]);
  struct pollfd f[2] = {{pipes[0][0], POLLIN, 0}, {pipes[1][0], POLLIN, 0}};
  for (int i = 0; i < 2; i++)
    if (ioctl(f[i].fd, FIONBIO, &(int){1}) < 0)
      fatal("nonblocking pipe");
  double deadline = stamp() + timeout;
  int finished = 0, status = 0, openpipes = 2, exit_wait = 1;
  while (!finished || openpipes) {
    progress_touch(&progress_main);
    if (stamp() >= deadline && !r.timed) {
      r.timed = 1;
      kill_group(pid);
    }
    if (!finished) {
      siginfo_t info;
      memset(&info, 0, sizeof info);
      if (waitid(P_PID, pid, &info, WEXITED | WNOHANG | WNOWAIT) < 0) {
        if (errno != EINTR) {
          active_child = 0;
          fatal("waitid");
        }
      } else if (info.si_pid)
        finished = 1;
    }
    if (r.timed && stamp() > deadline + 2000)
      break;
    /* Output and EOF wake poll directly. While a pipe is open, only the
     * deadline, its post-kill drain bound and the progress lease need a timed
     * wake. Once both pipes close, poll briefly for the exit status. */
    int wait;
    if (openpipes)
      wait = wait_ms(r.timed ? deadline + 2001 : deadline, 1000);
    else {
      wait = exit_wait;
      exit_wait = exit_wait < 8 ? exit_wait * 2 : 10;
    }
    int rc = poll(f, 2, wait);
    if (rc < 0 && errno != EINTR)
      fatal("poll");
    for (int i = 0; i < 2; i++) {
      if (f[i].fd < 0 || !f[i].revents)
        continue;
      unsigned char buffer[8192];
      ssize_t n = read(f[i].fd, buffer, sizeof buffer);
      if (n == 0) {
        close(f[i].fd);
        f[i].fd = -1;
        openpipes--;
      } else if (n > 0) {
        size_t *used = i ? &r.errlen : &r.outlen;
        unsigned char *out = i ? r.err : r.out;
        size_t keep = (size_t)n;
        if (keep > CHUNK - *used) {
          keep = CHUNK - *used;
          r.truncated |= 1 << i;
        }
        memcpy(out + *used, buffer, keep);
        *used += keep;
      } else if (errno != EINTR && errno != EAGAIN)
        fatal("pipe read");
    }
  }
  /* Keep the leader waitable until its process group is killed; a reaped PID
   * must never remain a cancellation target while descendants hold pipes. */
  kill_group(pid);
  active_child = 0;
  while (waitpid(pid, &status, 0) < 0)
    if (errno != EINTR)
      fatal("wait");
  for (int i = 0; i < 2; i++)
    if (f[i].fd >= 0)
      close(f[i].fd);
  if (r.truncated) {
    const char *streams = r.truncated == 3   ? "stdout and stderr"
                          : r.truncated == 1 ? "stdout"
                                             : "stderr";
    int n = snprintf(
        (char *)r.err + r.errlen, 128,
        "\n[samsung-tv-root: %s exceeded the 1 MiB capture limit]\n", streams);
    if (n < 0 || n >= 128)
      fatal("output notice");
    r.errlen += (size_t)n;
  }
  r.code = r.timed ? 124 : wait_code(status);
  return r;
}
static void result_free(Result *r) {
  free(r->out);
  free(r->err);
}
static int verified_launcher(void) {
  int fd = open(launcher, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (fd < 0)
    return 0;
  struct stat s;
  char actual[65];
  int good = !fstat(fd, &s) && S_ISREG(s.st_mode) && s.st_uid == 0 &&
             !(s.st_mode & 022) && request_filedigest(fd, actual) &&
             !strcmp(actual, launcher_sha);
  close(fd);
  return good;
}
/* Fault binaries only: terminate before opening any command channel. */
static void startup_fault(const char *stage) {
#ifdef NATIVE_WORKER_FAULT_TEST
  const char *selected = getenv("COUCHROOT_NATIVE_STARTUP_FAULT");
  if (selected && !strcmp(selected, stage))
    _exit(86);
#else
  (void)stage;
#endif
}
#include "jobs.h"

#include "helpers.h"

#include "runtime.h"

static void stop_signal(int sig);
#include "containment.h"

#include "guardian.h"
#include "reconcile.h"
static void runtime_cleanup(void) {
  if (!runtime_owned || !runtime_sweep() || !containment_cleanup())
    return;
  if (guardian_temporary_owned) {
    if (unlinkat(jobs_dir, guardian_temporary_owned, 0) && errno != ENOENT)
      return;
    guardian_temporary_owned = NULL;
  }
  if (guardian_journal_owned) {
    if (unlinkat(jobs_dir, "guardian", 0) && errno != ENOENT)
      return;
    guardian_journal_owned = 0;
  }
  if (jobs_dir >= 0)
    fsync(jobs_dir);
}
static volatile sig_atomic_t signal_socket = -1;
static void stop_signal(int sig) {
  (void)sig;
  if (signal_socket >= 0)
    shutdown(signal_socket, SHUT_RDWR);
  pid_t pid = active_child;
  if (pid > 0)
    kill_group(pid);
}
#include "fault-test.h"
/* Protocol-thread allocations outside the job operations. Under the job mutex
 * the monitor holds no descriptor; afterwards it opens at most one record at a
 * time, so admission keeps one slot in reserve for it. */
static int descriptor_admission(int needed) {
  pthread_mutex_lock(&jobs_mutex);
  int good = descriptor_capacity(needed + 1);
  pthread_mutex_unlock(&jobs_mutex);
  return good;
}
/* Peak descriptors each operation holds at once. A command needs both pipes
 * plus its child's /dev/null; helper staging holds source, directory and
 * target. Transfers keep one descriptor until closed. */
static int operation_descriptors(const char *op) {
  if (production_files &&
      (!strcmp(op, "file.begin") || !strcmp(op, "file.open") ||
       !strcmp(op, "file.commit")))
    return 2;
  if (!strcmp(op, "app.exec"))
    return 5;
  if (!strcmp(op, "helper.prepare"))
    return 3;
  return !strcmp(op, "file.begin") || !strcmp(op, "file.open") ||
         !strcmp(op, "file.commit") || !strcmp(op, "helper.release");
}
/* Transfer/helper tables are owned by the serialized request thread; the job
 * monitor shares its table under jobs_mutex. Retained disk records and detached
 * descendants are not inventoried here. Empty tables do not prove quiescence. */
static J *resource_inventory(void) {
  J *r = obj(), *ts = json_object_new_array(), *js = json_object_new_array(),
    *hs = json_object_new_array();
  num(r, "schema", 1);
  str(r, "scope", "worker-owned");
  for (int i = 0; i < 8; i++) {
    if (transfers[i].fd >= 0) {
      J *t = obj();
      str(t, "id", transfers[i].id);
      str(t, "direction", transfers[i].upload ? "upload" : "download");
      json_object_array_add(ts, t);
    }
    if (helpers[i].id[0])
      json_object_array_add(hs, json_object_new_string(helpers[i].id));
  }
  pthread_mutex_lock(&jobs_mutex);
  for (int i = 0; i < 16; i++) {
    if (!jobs[i].id[0]) continue;
    J *j = obj();
    str(j, "id", jobs[i].id);
    str(j, "state", jobs[i].state);
    boolean(j, "monitor_finished", jobs[i].finished);
    json_object_array_add(js, j);
  }
  pthread_mutex_unlock(&jobs_mutex);
  json_object_object_add(r, "transfers", ts);
  json_object_object_add(r, "jobs", js);
  json_object_object_add(r, "helpers", hs);
  return r;
}
static J *operation(J *request, Wire *w, const char *seq) {
  const char *op = textval(request, "op");
  if (!op)
    return failure("Invalid operation");
  if (bootstrap_mode && strcmp(op, "status"))
    return failure("Held bootstrap supports status and bounded exec only");
  int needed = operation_descriptors(op);
  if (needed && !descriptor_admission(needed))
    return failure("Insufficient descriptors; operation not started");
#ifdef NATIVE_WORKER_FAULT_TEST
  if (!strcmp(op, "test.stall")) {
    int64_t thread = number(request, "thread");
    if (thread != 0 && thread != 1)
      return failure("invalid stall target");
    fault_test_requested = thread ? 4 : 3;
    return success(obj());
  }
  if (!strcmp(op, "test.fault")) {
    int64_t thread = number(request, "thread");
    if (thread != 0 && thread != 1)
      return failure("Invalid fault test thread");
    fault_test_requested = thread ? 2 : 1;
    return success(obj());
  }
#endif
  if (!strncmp(op, "job.", 4))
    return job_operation(request, op);
  if (!strncmp(op, "helper.", 7))
    return helper_operation(request, op);
  if (!strcmp(op, "status")) {
    /* guardian_start forked this worker directly and checked the relationship
     * before opening the supervision gate. A fresh kernel parent check binds
     * the cached start identity to that original parent: a lost parent cannot
     * be replaced by a recycled numeric PID. No new descriptor is needed.
     * This is point-in-time evidence, not a promise of future guardian life. */
    if (guardian_pid <= 1 || getppid() != guardian_pid)
      return failure("Original guardian parent unavailable");
    J *j = obj(), *caps = json_object_new_array();
    str(j, "boot_id", current_boot); /* Read once at startup; fixed per boot. */
    /* /proc/uptime reports this clock in centiseconds; reading it needs no
     * descriptor. */
    struct timespec up;
    if (clock_gettime(CLOCK_BOOTTIME, &up))
      fatal("uptime");
    double uptime = (double)up.tv_sec + up.tv_nsec / 10000000 / 100.0;
    json_object_object_add(j, "uptime_seconds", json_object_new_double(uptime));
    str(j, "worker_id", worker_id);
    str(j, "startup_token_sha256", startup_token_sha256);
    J *processes = obj(), *worker = obj(), *guardian = obj();
    num(worker, "pid", getpid());
    str(worker, "start_ticks", worker_start_ticks);
    num(guardian, "pid", guardian_pid);
    str(guardian, "start_ticks", guardian_start_ticks);
    json_object_object_add(processes, "worker", worker);
    json_object_object_add(processes, "guardian", guardian);
    json_object_object_add(j, "processes", processes);
    json_object_object_add(j, "resources", resource_inventory());
    str(j, "implementation", bootstrap_mode ? "native-bootstrap" : "native-prototype");
    num(j, "guardian_pid", guardian_pid);
    boolean(j, "stale_guardian_reconciled", guardian_reconciled);
    str(j, "fault_supervision", "ptrace-owned-descendants");
    str(j, "command_fault_policy", "terminate-core-signals-before-handlers");
    json_object_object_add(j, "command_faults", fault_events_snapshot());
    num(j, "worker_dumpable", prctl(PR_GET_DUMPABLE));
    str(j, "freezer_group", freezer_name);
    num(j, "heartbeat_timeout_ms", 1000);
    num(j, "progress_timeout_ms", PROGRESS_GRACE_MS);
    num(j, "lifetime_seconds", lifetime_seconds);
    str(j, "lifetime_mode", bootstrap_mode ? "held-bootstrap" : production_mode ? "production" : "bounded");
    J *app = obj();
    str(app, "path", launcher);
    str(app, "sha256", launcher_sha);
    boolean(app, "independently_staged", 1);
    json_object_object_add(j, "app_launcher", app);
    const char *names[] = {production_files ? "prototype-production-files-v1"
                                            : "prototype-scoped-files-v1",
                           "binary-upload-v1",
                           "resource-inventory-v1",
                           "worker-process-identity-v1",
                           "guardian-parent-identity-v1",
                           "binary-download-v1",
                           "prototype-app-exec-v1",
                           "prototype-jobs-v1",
                           "prototype-helper-lifecycle-v1",
                           "prototype-independent-launcher-v1",
                           "prototype-crash-guardian-v1",
                           "startup-token-binding-v1",
                           "prototype-command-fault-diagnostics-v1"};
    if (bootstrap_mode) {
      const char *held[] = {"held-bootstrap-v1", "resource-inventory-v1", "worker-process-identity-v1", "guardian-parent-identity-v1"};
      for (size_t i = 0; i < sizeof held / sizeof *held; i++)
        json_object_array_add(caps, json_object_new_string(held[i]));
    } else for (size_t i = 0; i < sizeof names / sizeof *names; i++)
      json_object_array_add(caps, json_object_new_string(names[i]));
    json_object_object_add(j, "capabilities", caps);
    return success(j);
  }
  if (!strcmp(op, "app.exec")) {
    const char *command = textval(request, "command");
    int64_t timeout;
    if (!command || !*command || strlen(command) > 16384 ||
        !integer(request, "timeout_ms", &timeout) || timeout < 100 ||
        timeout > 25000)
      return failure("Invalid app command");
    if (!verified_launcher())
      return failure("Verified app launcher unavailable");
    Result r = execute(command, (int)timeout, 1);
    J *j = obj();
    num(j, "exit_code", r.code);
    boolean(j, "timed_out", r.timed);
    boolean(j, "output_truncated", r.truncated);
    json_object_object_add(j, "stdout",
                           json_object_new_string_len((char *)r.out, r.outlen));
    json_object_object_add(j, "stderr",
                           json_object_new_string_len((char *)r.err, r.errlen));
    result_free(&r);
    return success(j);
  }
  if (!strcmp(op, "file.begin") || !strcmp(op, "file.open")) {
    Transfer *t = NULL;
    for (int i = 0; i < 8; i++)
      if (transfers[i].fd < 0) {
        t = &transfers[i];
        break;
      }
    if (!t)
      return failure("Transfer limit");
    const char *name, *path = textval(request, "path");
    int upload = !strcmp(op, "file.begin");
    if (production_files ? !file_path_allowed(path, upload)
                         : !leaf(path, &name))
      return failure("Path outside file policy");
    int64_t size = 0;
    const char *sha = NULL, *expected = NULL;
    if (upload) {
      sha = textval(request, "sha256");
      expected = textval(request, "expected_sha256");
      if (!integer(request, "size", &size) || size < 0 || size > LIMIT ||
          !hexvalid(sha, 64) || !expected ||
          (strcmp(expected, "absent") && !hexvalid(expected, 64)))
        return failure("Invalid upload metadata");
    }
    char leafname[256];
    int parent =
        production_files ? file_parent(path, upload, leafname) : directory;
    if (parent < 0)
      return failure("File parent unavailable");
    if (production_files)
      name = leafname;
    /* Reject a symlink destination even for create-only uploads. */
    struct stat named;
    if (upload && fstatat(parent, name, &named, AT_SYMLINK_NOFOLLOW) == 0 &&
        !S_ISREG(named.st_mode)) {
      if (production_files)
        close(parent);
      return failure("Regular destination required");
    }
    t->parent = production_files ? parent : -1;
    strcpy(t->path, path);
    unsigned char id[16];
    random_bytes(id, sizeof id);
    hex(id, sizeof id, t->id);
    strcpy(t->name, name);
    t->upload = upload;
    t->size = size;
    if (upload) {
      strcpy(t->sha, sha);
      strcpy(t->expected, expected);
      memcpy(t->temp, ".upload-", 8);
      memcpy(t->temp + 8, t->id, sizeof t->id);
      t->fd = openat(parent, t->temp,
                     O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    } else
      t->fd =
          openat(parent, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    if (t->fd < 0) {
      t->temp[0] =
          0; // Never unlink an existing file after exclusive creation failed.
      release(t);
      return failure("Cannot open transfer");
    }
    if (!regular(t->fd, &size) || (!upload && !request_filedigest(t->fd, t->sha))) {
      release(t);
      return failure("Not a bounded regular file");
    }
    if (!upload) {
      t->size = size;
      if (t->parent >= 0)
        close(t->parent);
      t->parent = -1;
    }
    J *opened = snapshot(t);
    num(opened, "offset", 0);
    return success(opened);
  }
  if (strncmp(op, "file.", 5))
    return failure("Unsupported in native prototype (no fallback)");
  Transfer *t = lookup(textval(request, "transfer_id"));
  if (!t)
    return failure("Unknown transfer");
  if (!strcmp(op, "file.status"))
    return success(snapshot(t));
  if (!strcmp(op, "file.close")) {
    release(t);
    J *j = obj();
    boolean(j, "closed", 1);
    return success(j);
  }
  if (!strcmp(op, "file.write")) {
    int64_t offset;
    const char *encoded = textval(request, "data"),
               *sha = textval(request, "sha256");
    if (!integer(request, "offset", &offset) || !encoded ||
        strlen(encoded) > ((CHUNK + 2) / 3) * 4 || !hexvalid(sha, 64))
      return failure("Invalid JSON upload chunk");
    size_t length;
    unsigned char *data = decode(encoded, &length);
    if (!data)
      return failure("Invalid chunk base64");
    J *r = writechunk(t->id, offset, data, length, sha);
    free(data);
    return r;
  }
  if (!strcmp(op, "file.read")) {
    int64_t offset, length;
    if (t->upload || !integer(request, "offset", &offset) ||
        !integer(request, "length", &length) || offset < 0 ||
        offset > t->size || length < 1 || length > CHUNK)
      return failure("Invalid byte range");
    if (length > t->size - offset)
      length = t->size - offset;
    unsigned char *data = allocate((size_t)length);
    size_t at = 0;
    while (at < (size_t)length) {
      ssize_t n = request_pread(t->fd, data + at, (size_t)length - at, offset + at);
      if (n < 0 && errno == EINTR)
        continue;
      if (n <= 0) {
        free(data);
        return failure("File changed during read");
      }
      at += n;
    }
    char sha[65];
    digest(data, length, sha);
    char *header = format("OPDATA\t%s\t%" PRId64 "\t%" PRId64 "\t%s", seq,
                          offset, length, sha);
    sendframe(w, header);
    writeall(w->fd, data, length);
    free(header);
    free(data);
    return NULL;
  }
  if (!strcmp(op, "file.commit")) {
    int64_t size;
    char actual[65];
    if (!t->upload || !regular(t->fd, &size) || size != t->size ||
        !request_filedigest(t->fd, actual) || strcmp(actual, t->sha))
      return failure("Upload digest or size mismatch");
    if (!file_parent_unchanged(t))
      return failure("Upload parent changed; retained for inspection");
    int parent = t->parent >= 0 ? t->parent : directory;
    if (!strcmp(t->expected, "absent")) {
      if (linkat(parent, t->temp, parent, t->name, 0))
        return failure("Target exists or cannot be created");
    } else {
      int fd = openat(parent, t->name,
                      O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
      int good = fd >= 0 && regular(fd, &size) && request_filedigest(fd, actual) &&
                 !strcmp(actual, t->expected);
      if (fd >= 0)
        close(fd);
      if (!good)
        return failure("Target hash conflict");
      if (renameat(parent, t->temp, parent, t->name))
        return failure("Atomic replacement failed");
    }
    J *j = obj();
    boolean(j, "committed", 1);
    str(j, "sha256", t->sha);
    num(j, "size", t->size);
    release(t);
    return success(j);
  }
  return failure("Unsupported file operation in native prototype");
}
#include "offline-reconcile.h"
int main(int argc, char **argv) {
  if (argc >= 2 && !strcmp(argv[1], "--reconcile-state"))
    return offline_reconcile(argc, argv);
#ifdef NATIVE_WORKER_FAULT_TEST
  if (argc == 2 && !strcmp(argv[1], "--test-child-fault"))
    fault_test_memory(NULL);
  if (argc == 2 && !strcmp(argv[1], "--test-child-thread-fault")) {
    fault_test_requested = 2;
    fault_test_execute();
  }
#endif
  bootstrap_mode = argc == 8 && !strcmp(argv[7], "--held-bootstrap");
  production_mode = argc == 8 && !strcmp(argv[7], "--production");
  production_files = production_mode ||
                     (argc == 8 && !strcmp(argv[7], "--production-files"));
  if (argc != 7 && !production_files && !bootstrap_mode) {
    fputs("usage: worker HOST PORT TOKEN EXPERIMENT_DIRECTORY "
          "LAUNCHER_SOURCE SHA256 [--production-files|--production|--held-bootstrap]\n",
          stderr);
    return 64;
  }
  if (getuid() || geteuid() || getgid() || getegid())
    return 77;
  /* Conservative admission before dlopen, token consumption, or scope changes.
   * Includes persistent scope/runtime/freezer descriptors, both pipes, monitor,
   * transport, and temporary reconciliation scans. Per-allocation guards remain
   * active throughout startup and in the guardian. This cannot protect the ELF
   * loader before main, nor reserve capacity against external concurrent changes.
   */
  if (!descriptor_capacity(32)) {
    errno = EMFILE;
    fatal("insufficient startup descriptors; state untouched");
  }
  signal(SIGPIPE, SIG_IGN);
  signal(SIGTERM, stop_signal);
  signal(SIGINT, stop_signal);
  signal(SIGALRM, stop_signal);
  const char *lifetime = getenv("COUCHROOT_NATIVE_LIFETIME_SECONDS");
  int64_t seconds;
  if (bootstrap_mode && (lifetime || strcmp(argv[1], "127.0.0.1")))
    fatal("held bootstrap requires loopback and fixed lifetime");
  if (production_mode && lifetime)
    fatal("production mode cannot use an experiment lifetime");
  if (production_mode)
    lifetime_seconds = 0;
  if (lifetime) {
    if (!decimal(lifetime, &seconds) || seconds < 300 || seconds > 86400)
      fatal("prototype lifetime must be 300..86400 seconds");
    lifetime_seconds = (unsigned)seconds;
  }
  alarm(lifetime_seconds);
  libraries();
  for (int i = 0; i < 8; i++)
    transfers[i].fd = transfers[i].parent = -1;
  atexit(cleanup);
  char resolved[PATH_MAX];
  if (!realpath(argv[4], resolved) || strcmp(resolved, argv[4]) ||
      strlen(resolved) > PATH_MAX - 257)
    fatal("canonical experiment directory required");
  strcpy(root, resolved);
  if (production_files) {
    if (!canonical_file(argv[3]))
      fatal("canonical token path required");
    strcpy(staging_root, argv[3]);
    *strrchr(staging_root, '/') = 0;
    if (!staging_root[0])
      fatal("private staging directory required");
  }
  directory = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  struct stat st;
  if (directory < 0 || fstat(directory, &st) || st.st_uid != 0 ||
      (st.st_mode & 077))
    fatal("private root-owned directory required");
  if (strlen(argv[5]) >= sizeof launcher || !hexvalid(argv[6], 64))
    fatal("launcher arguments");
  strcpy(launcher_sha, argv[6]);
  unsigned char id[16];
  random_bytes(id, sizeof id);
  hex(id, sizeof id, worker_id);
  struct rlimit core_limit = {0, 0};
  if (setrlimit(RLIMIT_CORE, &core_limit) || prctl(PR_SET_DUMPABLE, 0))
    fatal("disable prototype core dumps");
  signal(SIGCHLD, SIG_DFL);
  jobs_storage();
  guardian_reconcile();
  int startup_token = open(argv[3], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (startup_token < 0 || fstat(startup_token, &st) ||
      !S_ISREG(st.st_mode) || st.st_uid || (st.st_mode & 077) ||
      st.st_nlink != 1 || st.st_size < 1 || st.st_size > 64 ||
      !request_filedigest(startup_token, startup_token_sha256))
    fatal("private startup token binding required");
  close(startup_token);
  helpers_init();
  guardian_journal("namespace");
  startup_fault("namespace");
  if (!helper_parent_storage())
    fatal("initial runtime parent");
  startup_fault("runtime-parent-created");
  guardian_journal("runtime-reserved");
  startup_fault("runtime-reserved");
  if (!helper_storage())
    fatal("initial runtime storage");
  guardian_journal("runtime");
  startup_fault("runtime");
  launcher_stage(argv[5]);
  startup_fault("launcher");
  containment_storage();
  guardian_journal("freezer-reserved");
  startup_fault("freezer-reserved");
  containment_prepare();
  guardian_journal("contained");
  startup_fault("contained");
  guardian_journal("ready");
  startup_fault("ready");
  fault_events_init();
  guardian_start();
  if (!job_identity(getpid(), worker_start_ticks) ||
      !job_identity(guardian_pid, guardian_start_ticks))
    fatal("worker process identities");
  jobs_init();
  Wire w = {0};
  int token = open(argv[3], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
  if (token < 0 || fstat(token, &st) || !S_ISREG(st.st_mode) ||
      st.st_uid != 0 || (st.st_mode & 077) || st.st_nlink != 1)
    fatal("private token required");
  char encoded[128];
  ssize_t n = read(token, encoded, sizeof encoded - 1);
  close(token);
  if (n < 1 || n > 64)
    fatal("token size");
  char consumed_sha256[65];
  digest(encoded, (size_t)n, consumed_sha256);
  if (strcmp(consumed_sha256, startup_token_sha256))
    fatal("startup token changed");
  encoded[n] = 0;
  while (n && isspace((unsigned char)encoded[n - 1]))
    encoded[--n] = 0;
  size_t decoded;
  unsigned char *key = decode(encoded, &decoded);
  if (!key || decoded != 32)
    fatal("token encoding");
  memcpy(w.secret, key, 32);
  memset(key, 0, decoded);
  free(key);
  if (unlink(argv[3]))
    fatal("consume token");
  int64_t port;
  if (!decimal(argv[2], &port) || port < 1 || port > 65535)
    fatal("port");
  struct sockaddr_in addr = {.sin_family = AF_INET,
                             .sin_port = htons((uint16_t)port)};
  if (inet_pton(AF_INET, argv[1], &addr.sin_addr) != 1)
    fatal("host");
  w.fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
  if (w.fd < 0)
    fatal("socket");
  signal_socket = w.fd;
  int one = 1;
  setsockopt(w.fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
  /* Idle production connections have no lifetime. Individual reads/writes and
   * the first handshake remain bounded; active frame parsing has a progress
   * lease as well, so trickled bytes cannot keep an unfinished request alive. */
  struct timeval limit = {production_mode ? 30 : lifetime_seconds, 0};
  setsockopt(w.fd, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof limit);
  setsockopt(w.fd, SOL_SOCKET, SO_SNDTIMEO, &limit, sizeof limit);
  if (connect(w.fd, (struct sockaddr *)&addr, sizeof addr))
    fatal("connect");
  struct timeval handshake = {10, 0};
  setsockopt(w.fd, SOL_SOCKET, SO_RCVTIMEO, &handshake, sizeof handshake);
  char *hello = bounded_line(&w, PREAUTH_BYTES), *f[10];
  if (fields(hello, f, 10) != 2 || strcmp(f[0], "SAMSUNG-TV-ROOT/1") ||
      !unhex(f[1], w.nonce, 32))
    fatal("hello");
  free(hello);
  setsockopt(w.fd, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof limit);
  char smack[257];
#ifdef NATIVE_WORKER_TEST
  strcpy(smack, "host-test-without-Smack");
#else
  readtext("/proc/self/attr/current", smack, sizeof smack);
#endif
  char caps[32] = "", statusline[256];
  FILE *statusfile = fopen("/proc/self/status", "r");
  if (!statusfile)
    fatal("process identity");
  while (fgets(statusline, sizeof statusline, statusfile))
    if (sscanf(statusline, "CapEff: %31s", caps) == 1)
      break;
  fclose(statusfile);
  if (!*caps)
    fatal("effective capabilities");
  char *label = base64(smack, strlen(smack)),
       *auth = format("AUTH\t%d\t0\t0\t0\t0\t%s\t%s", getpid(), caps, label);
  sendframe(&w, auth);
  free(label);
  free(auth);
  /* The guardian's fork retains its own enabled guard. The initialized worker
   * now uses operation admission under the job mutex, including monitor reserve.
   */
  __atomic_store_n(&descriptor_guard, 0, __ATOMIC_RELAXED);
  int64_t previous = 0;
  for (;;) {
    progress_idle(&progress_main);
    if (production_mode && w.at == w.end) {
      if (request_wait_idle(w.fd) < 0)
        fatal("idle protocol wait");
    }
    if (production_mode)
      progress_touch(&progress_main);
    char *frame = receive(&w);
    progress_touch(&progress_main);
    int count = fields(frame, f, 10);
    int64_t seq;
    if (count < 2 || !decimal(f[1], &seq) || seq <= previous)
      fatal("sequence");
    previous = seq;
    if (!strcmp(f[0], "SHUTDOWN") && count == 2) {
      char *p = format("BYE\t%s", f[1]);
      sendframe(&w, p);
      free(p);
      free(frame);
      break;
    }
    J *reply = NULL;
    if (bootstrap_mode && !strcmp(f[0], "OPWRITE"))
      fatal("held bootstrap has no upload channel");
    if (!strcmp(f[0], "OPWRITE")) {
      int64_t offset, length;
      if (count != 6 || !hexvalid(f[2], 32) || !decimal(f[3], &offset) ||
          !decimal(f[4], &length) || offset > LIMIT || length < 1 ||
          length > CHUNK || length > LIMIT - offset || !hexvalid(f[5], 64))
        fatal("upload header");
      unsigned char *data = allocate(length);
      exact(&w, data, length);
      reply = writechunk(f[2], offset, data, length, f[5]);
      free(data);
    } else if (!strcmp(f[0], "OP") && count == 3) {
      size_t len;
      unsigned char *bytes = decode(f[2], &len);
      if (!bytes || len > ((CHUNK + 2) / 3) * 4 + 20000 ||
          strlen((char *)bytes) != len)
        fatal("operation encoding");
      J *request = parse((char *)bytes);
      free(bytes);
      if (!request)
        fatal("operation JSON");
      const char *op = textval(request, "op");
      if (len > 20000 && (!op || strcmp(op, "file.write")))
        fatal("operation size");
      reply = operation(request, &w, f[1]);
      json_object_put(request);
    } else if (!strcmp(f[0], "EXEC") && count == 4) {
      int64_t timeout;
      size_t len;
      unsigned char *command = decode(f[3], &len);
      if (!decimal(f[2], &timeout) || !exec_timeout_valid(timeout, bootstrap_mode) ||
          !command || !len || len > 65536 || strlen((char *)command) != len)
        fatal("exec input");
      /* Like a managed worker that cannot start a process, end the session
       * without running the command; never reach the kernel abort path. */
      if (!descriptor_admission(5)) {
        errno = EMFILE;
        fatal("insufficient descriptors; command not run");
      }
      Result r = execute((char *)command, (int)timeout, 0);
      char *out = base64(r.out, r.outlen), *err = base64(r.err, r.errlen),
           *p = format("RESULT\t%s\t%d\t%d\t%s\t%s", f[1], r.code, r.timed, out,
                       err);
      sendframe(&w, p);
      free(p);
      free(out);
      free(err);
      result_free(&r);
      free(command);
    } else if (!strcmp(f[0], "PING") && count == 2) {
      char *p = format("PONG\t%s\t0\t0\t0\t0", f[1]);
      sendframe(&w, p);
      free(p);
    } else
      fatal("unsupported frame");
    if (reply) {
      const char *s = json(reply);
      char *b = base64(s, strlen(s)), *p = format("OPRESULT\t%s\t%s", f[1], b);
      sendframe(&w, p);
      free(b);
      free(p);
      json_object_put(reply);
    }
    free(frame);
#ifdef NATIVE_WORKER_FAULT_TEST
    fault_test_execute();
#endif
  }
  memset(w.secret, 0, 32);
  signal_socket = -1;
  close(w.fd);
  return 0;
}
