/* Original Couchroot code. SPDX-License-Identifier: 0BSD */
/* Allocate optional MQTT descriptors under the existing job-table lock, leaving
 * room for an already-admitted protocol operation (peak five) and one monitor
 * record. No lock is held during network I/O, sampling, fork or child waits.
 * External rlimit changes still cannot be made atomic with a following syscall.
 */
static int mqtt_fd_lock(int needed) {
#ifdef COUCHROOT_NATIVE_WORKER
  pthread_mutex_lock(&jobs_mutex);
  if (!descriptor_capacity(needed + 6)) {
    pthread_mutex_unlock(&jobs_mutex);
    return 0;
  }
#else
  (void)needed; /* Host harness: libc returns EMFILE normally. */
#endif
  return 1;
}
static void mqtt_fd_unlock(void) {
#ifdef COUCHROOT_NATIVE_WORKER
  pthread_mutex_unlock(&jobs_mutex);
#endif
}
