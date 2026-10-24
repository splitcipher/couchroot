#!/bin/sh
# Run only through an admitted maintenance transport with independent rescue.
# The caller journals this invocation and binds the HTTPS listener's process.
# A submitted start is not readiness; verify a new host and worker afterward.
set -eu
test "$#" -eq 3 || exit 64
boot=$1; coordinator=$2; started=$3
printf '%s\n' "$boot" | grep -Eq '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$' || exit 64
case "$coordinator:$started" in *[!0-9:]*|:*|*:) exit 64;; esac
test "$coordinator" -gt 1 && test "$started" -gt 0 || exit 64
test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot"

same_host() {
    line=$(cat "/proc/$coordinator/stat") || return 1
    case "$line" in
        "$coordinator (wrt-service) "*) ;;
        "$coordinator (MiniRoot01.Serv) "*)
            # QN90A names its host after the app; bind the real executable too.
            test "$(readlink "/proc/$coordinator/exe")" = /usr/bin/wrt-service || return 1;;
        *) return 1;;
    esac
    rest=${line##*) }
    # Split the kernel's stat fields after removing the parenthesized name.
    # shellcheck disable=SC2086
    set -- $rest
    test "$#" -ge 20 || return 1
    shift 19
    test "$1" = "$started"
}
same_host
test "$(app_launcher -r MiniRoot01.Service)" = 'result: running'
app_launcher -k MiniRoot01.Service

# S90D can reuse the still-exiting WRT host if start follows stop immediately.
# A new worker in that host can become ready, then die with its pending shutdown.
# Wait for the bound host to disappear, not a fixed sleep or wrapper status.
remaining=120
while test -d "/proc/$coordinator"; do
    if ! same_host; then
        # Exit can race the stat read. Only actual absence permits progress.
        test ! -d "/proc/$coordinator" && break
        echo 'Service host identity unavailable or changed' >&2; exit 1
    fi
    test "$remaining" -gt 0 || { echo 'Service host did not exit; start withheld' >&2; exit 1; }
    remaining=$((remaining - 1))
    sleep 1
done
test "$(cat /proc/sys/kernel/random/boot_id)" = "$boot"
status=0
running=$(app_launcher -r MiniRoot01.Service) || status=$?
test "$status" -eq 1
case "$running" in
    'result: not running'|'Failed to get filter count
result: not running') ;;
    *) echo 'Unexpected stopped-service status' >&2; exit 1;;
esac
echo SERVICE_STOPPED
app_launcher -s MiniRoot01.Service
echo SERVICE_START_SUBMITTED
