#!/bin/sh
# Run only in a disposable Linux ARM64 container with a read-only checkout.
set -eu
# Fail before the long suites if the runner's container policy blocks mount tests.
mount_probe=$(mktemp -d)
mount -t tmpfs -o size=1m tmpfs "$mount_probe"
umount "$mount_probe"
rmdir "$mount_probe"
cc -std=c99 -O2 -Wall -Wextra -Werror -Wno-unused-function \
  -DNATIVE_WORKER_TEST -DNATIVE_WORKER_FAULT_TEST \
  agent/native-worker/worker.c -ldl -pthread -o /out/worker
cc -std=c99 -O2 -Wall -Wextra -Werror -Wno-unused-function \
  agent/native-worker/accept.c -ldl -pthread -o /out/accept
cc -std=c99 -O2 -Wall -Wextra -Werror \
  agent/native-observer/process-observer.c -o /out/process-observer
cc -shared -fPIC -Wall -Wextra -Werror tests/native-io/delay.c -ldl -o /out/io-delay.so
cc -std=c99 -O2 -Wall -Wextra -Werror -Wno-unused-function tests/mqtt/harness.c -ldl -pthread -o /out/mqtt-harness
export MQTT_HARNESS=/out/mqtt-harness
export COUCHROOT_PARITY_CONTAINER=1
export NATIVE_WORKER=/out/worker NATIVE_ACCEPT=/out/accept PROCESS_OBSERVER=/out/process-observer
export NATIVE_WORKER_FAULT_TEST=1 NATIVE_WORKER_STORAGE_TEST=1 NATIVE_IO_DELAY=/out/io-delay.so
python3 -m unittest discover -s tests -p 'native_*_test.py'
python3 -m unittest discover -s tests -p 'process_observer*_test.py'
# These suites use process-global retained state; run files sequentially.
for suite in tests/*.test.cjs; do
  if grep -Eq 'COUCHROOT_PARITY_CONTAINER|PROCESS_OBSERVER' "$suite"; then
    node --test --test-concurrency=1 "$suite"
  fi
done
