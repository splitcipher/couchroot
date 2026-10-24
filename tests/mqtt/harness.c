/* Host-only test entry point; never packaged. SPDX-License-Identifier: 0BSD */
#include "../../agent/native-worker/common.h"
#include <pthread.h>
static void lifecycle_signals(sigset_t *set) {
  sigemptyset(set);
  sigaddset(set, SIGTERM);
  sigaddset(set, SIGINT);
  sigaddset(set, SIGALRM);
}
#include "../../agent/native-worker/mqtt/bridge.h"
static volatile sig_atomic_t done;
static void stop_test(int sig) {
  (void)sig;
  done = 1;
}
int main(int argc, char **argv) {
  if (argc == 2 && !strcmp(argv[1], "--mqtt-foreground"))
    return mqtt_foreground_main();
  libraries();
  signal(SIGPIPE, SIG_IGN);
  if (argc == 3 && !strcmp(argv[1], "command")) {
    char raw[4096];
    size_t n = fread(raw, 1, sizeof raw - 1, stdin);
    raw[n] = 0;
    const char *error;
    J *j = mqtt_command(argv[2], raw, &error);
    if (j) {
      puts("valid");
      json_object_put(j);
    } else
      puts(error);
    return 0;
  }
  if (argc == 2 && !strcmp(argv[1], "debounce")) {
    MqttState s = {0};
    assert(mqtt_state_update(&s, "one", 100));
    assert(!mqtt_state_due(&s, 349));
    assert(mqtt_state_update(&s, "two", 300));
    assert(mqtt_state_due(&s, 350));
    assert(!strcmp(s.latest, "two"));
    s.dirty = 0;
    assert(mqtt_state_update(&s, "two", 400));
    assert(!s.dirty);
    assert(mqtt_state_update(&s, "three", 500));
    assert(!mqtt_state_due(&s, 749));
    for (int i = 0; i < 10000; i++)
      assert(mqtt_state_update(&s, i % 2 ? "a" : "b", 501 + i));
    assert(sizeof s < 5000);
    puts("ok");
    return 0;
  }
  if (argc == 3 && !strcmp(argv[1], "foreground")) {
    char value[257];
    int rc = mqtt_foreground_read(argv[2], value, mqtt_cancelled);
    J *j = obj();
    num(j, "support", rc);
    str(j, "id", value);
    puts(json(j));
    json_object_put(j);
    return 0;
  }
  if (argc == 2 &&
      (!strcmp(argv[1], "metrics") || !strcmp(argv[1], "projection"))) {
    char raw[32768];
    size_t n = fread(raw, 1, sizeof raw - 1, stdin);
    raw[n] = 0;
    J *request = parse(raw);
    if (!request)
      return 65;
    if (!strcmp(argv[1], "metrics")) {
      MqttCpu previous = {0};
      J *samples = get(request, "samples"), *results = json_object_new_array();
      for (size_t i = 0; i < json_object_array_length(samples); i++) {
        J *sample = json_object_array_get_idx(samples, i), *r = obj();
        json_object_object_add(r, "cpu",
                               mqtt_cpu_sample(&previous,
                                               textval(sample, "stat"),
                                               number(sample, "at")));
        json_object_object_add(r, "memory",
                               mqtt_memory_sample(textval(sample, "mem")));
        json_object_array_add(results, r);
      }
      puts(json(results));
      json_object_put(results);
    } else {
      J *state = mqtt_initial_state(), *features = obj(), *result = obj();
      mqtt_project(get(request, "observation"),
                   mqtt_supported(request, "fresh"),
                   textval(request, "foreground"), state, features);
      MqttConfig c = {.state = 1};
      strcpy(c.device, "qn90a");
      strcpy(c.name, "Example TV");
      json_object_object_add(result, "state", state);
      json_object_object_add(result, "features", features);
      json_object_object_add(result, "discovery", mqtt_discovery(&c, features));
      puts(json(result));
      json_object_put(result);
    }
    json_object_put(request);
    return 0;
  }
  if (argc < 4)
    return 64;
  MqttConfig c;
  int good =
      mqtt_config(argv[2], argv[3], "TEST-FIRMWARE-1.0", "test-build", &c);
  if (!strcmp(argv[1], "config")) {
    puts(good ? "valid" : "invalid");
    mqtt_wipe(&c, sizeof c);
    return 0;
  }
  if (!good)
    return 65;
  if (!strcmp(argv[1], "discovery")) {
    J *j = mqtt_discovery(&c, NULL);
    puts(json(j));
    json_object_put(j);
    mqtt_wipe(&c, sizeof c);
    return 0;
  }
  if (strcmp(argv[1], "run") && strcmp(argv[1], "expire") &&
      strcmp(argv[1], "simulate"))
    return 64;
  if (!c.enabled)
    return 0;
  mqtt_settings = c;
  mqtt_wipe(&c, sizeof c);
  mqtt_lease = stamp() + (!strcmp(argv[1], "expire") ? 1500 : 120000);
  signal(SIGTERM, stop_test);
  signal(SIGINT, stop_test);
  if (pthread_create(&mqtt_thread, NULL, mqtt_loop, NULL))
    return 1;
  mqtt_thread_started = mqtt_active = 1;
  puts("ready");
  fflush(stdout);
  while (!done) {
    struct pollfd input = {0, POLLIN, 0};
    if (!strcmp(argv[1], "simulate") && poll(&input, 1, 50) > 0 &&
        (input.revents & POLLIN)) {
      char raw[32768];
      if (fgets(raw, sizeof raw, stdin)) {
        J *request = obj();
        str(request, "observations", raw);
        mqtt_observe(request);
        json_object_put(request);
      }
    } else
      poll(NULL, 0, 50);
  }
  mqtt_stop();
  return 0;
}
