/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
#include <sys/prctl.h>
#include <sys/syscall.h>
static int mqtt_app_id(const char *s) {
  if (!s || !*s || strnlen(s, 257) > 256)
    return 0;
  for (; *s; s++)
    if (!isalnum((unsigned char)*s) && *s != '.' && *s != '_' && *s != '-')
      return 0;
  return 1;
}
/* Fixed read-only subprocess of this executable, not a service or command
 * dispatcher. vconf may block inside vendor code; the parent bounds its
 * lifetime. Same key/ownership as the existing telemetry collector and boot
 * relay. */
static int mqtt_foreground_main(void) {
  alarm(1);
  void *rt = dlopen("librt.so.1", RTLD_NOW | RTLD_GLOBAL);
  (void)rt; /* S90D vconf's undeclared shm_open dependency, as in recovery.c. */
  void *lib = dlopen("libvconf.so.0", RTLD_NOW | RTLD_LOCAL);
  if (!lib)
    return 3;
  char *(*read_value)(const char *);
  *(void **)(&read_value) = dlsym(lib, "vconf_get_str");
  if (!read_value)
    return 3;
  char *value = read_value("memory/appfw/current_fullscreen_appid");
  if (!value)
    return 2;
  int good = mqtt_app_id(value);
  if (good &&
      write(STDOUT_FILENO, value, strlen(value)) != (ssize_t)strlen(value))
    good = 0;
  free(value);
  return good ? 0 : 2;
}
static int mqtt_foreground_read(const char *exe, char out[257],
                                int (*cancel)(void)) {
  out[0] = 0;
  int pipes[2], nullfd;
  struct rlimit limit;
  if (getrlimit(RLIMIT_NOFILE, &limit) || limit.rlim_cur > 1048576)
    return -1;
  if (!mqtt_fd_lock(3))
    return -1;
  nullfd = open("/dev/null", O_RDWR | O_CLOEXEC);
  if (nullfd < 0) {
    mqtt_fd_unlock();
    return -1;
  }
  if (pipe2(pipes, O_CLOEXEC | O_NONBLOCK)) {
    close(nullfd);
    mqtt_fd_unlock();
    return -1;
  }
  mqtt_fd_unlock();
  pid_t parent = getpid(), child = fork();
  if (!child) {
    /* Only async-signal-safe operations until exec. No inherited broker/IPC,
     * credentials, log descriptors, dynamic-loader environment or child shell.
     */
    if (prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != parent)
      _exit(126);
    sigset_t empty;
    sigemptyset(&empty);
    if (sigprocmask(SIG_SETMASK, &empty, NULL) || dup2(pipes[1], 1) < 0 ||
        dup2(nullfd, 0) < 0 || dup2(nullfd, 2) < 0)
      _exit(126);
#ifdef SYS_close_range
    if (syscall(SYS_close_range, 3U, ~0U, 0) < 0)
#endif
      for (int fd = 3; (rlim_t)fd < limit.rlim_cur; fd++)
        close(fd);
    execve(exe, (char *const[]){(char *)exe, "--mqtt-foreground", NULL},
           (char *const[]){NULL});
    _exit(127);
  }
  close(nullfd);
  close(pipes[1]);
  if (child < 0) {
    close(pipes[0]);
    return -1;
  }
  double deadline = stamp() + 800;
  char raw[258];
  size_t used = 0;
  int status = 0, finished = 0, ownership_lost = 0;
  while (stamp() < deadline && !cancel()) {
    ssize_t n = read(pipes[0], raw + used, sizeof raw - used);
    if (n > 0)
      used += (size_t)n;
    if (used == sizeof raw)
      break;
    pid_t result = waitpid(child, &status, WNOHANG);
    if (result == child) {
      finished = 1;
      n = read(pipes[0], raw + used, sizeof raw - used);
      if (n > 0)
        used += (size_t)n;
      break;
    }
    if (result < 0 && errno != EINTR) {
      ownership_lost = 1;
      break;
    }
    poll(NULL, 0, 10);
  }
  close(pipes[0]);
  if (ownership_lost)
    return -1; /* Never signal a PID no longer owned. */
  if (!finished) {
    kill(child, SIGKILL);
    while (waitpid(child, &status, 0) < 0 && errno == EINTR) {
    }
    return -1;
  }
  if (!WIFEXITED(status))
    return -1;
  if (WEXITSTATUS(status) == 3)
    return 0; /* definitively absent adapter */
  if (WEXITSTATUS(status) == 2)
    return 1; /* supported, no foreground now */
  if (WEXITSTATUS(status) || used > 256 || memchr(raw, 0, used))
    return -1;
  raw[used] = 0;
  if (!mqtt_app_id(raw))
    return -1;
  strcpy(out, raw);
  return 1;
}
