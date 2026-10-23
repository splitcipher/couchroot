#!/bin/sh
# Standalone application build. Does not invoke the repository setup builder.
set -eu
: "${WEBVIEW_OUTPUT_DIR:?Set an absolute output directory outside the repository}"
case "$WEBVIEW_OUTPUT_DIR" in /*) ;; *) exit 2 ;; esac
source_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$source_dir/../.." && pwd)
python3 - "$repo_dir" "$WEBVIEW_OUTPUT_DIR" <<'PYCHECK'
from pathlib import Path
import sys
repo, out = (Path(p).resolve() for p in sys.argv[1:])
if out == repo or repo in out.parents or out in repo.parents:
    raise SystemExit('Output must be outside the repository, not one of its ancestors')
PYCHECK
mkdir -p "$WEBVIEW_OUTPUT_DIR"
# minimal-hub-procsample is a diagnostic sampler for private measurement runs;
# it is never part of the installed launcher.
for program in host:minimal-hub-webview procsample:minimal-hub-procsample; do
# The host must load libpthread at startup, not later through EFL/Chromium's
# dlopen: without it Chromium's first browser context corrupted the heap in
# about 1 in 8 cold starts on QN90A's glibc 2.30 (README, "Startup crash").
threads=
[ "${program%%:*}" = host ] && threads="-Wl,--no-as-needed -lpthread -Wl,--as-needed"
docker run --rm --platform linux/amd64 --network none \
  -v "$source_dir/..:/src:ro" -v "$WEBVIEW_OUTPUT_DIR:/out" samsung-native-collector:bullseye \
  arm-linux-gnueabi-gcc -std=c99 -O2 -Wall -Wextra -Werror \
  -fstack-protector-strong -D_FORTIFY_SOURCE=2 -Wl,-z,relro,-z,now \
  -march=armv7-a -mfpu=vfpv3-d16 -mfloat-abi=softfp \
  "/src/webview/${program%%:*}.c" -ldl $threads -o "/out/${program#*:}"
docker run --rm --platform linux/amd64 --network none \
  -v "$WEBVIEW_OUTPUT_DIR:/out:ro" samsung-native-collector:bullseye \
  arm-linux-gnueabi-readelf -V "/out/${program#*:}" | python3 -c '
import re, sys
versions = set(re.findall(r"GLIBC_(\d+)\.(\d+)", sys.stdin.read()))
if not versions or any(tuple(map(int, v)) > (2, 17) for v in versions):
    raise SystemExit("Missing or incompatible GLIBC requirements: " + repr(versions))
print("ARM build: GLIBC requirements <= 2.17 (" + sys.argv[1] + ")")
' "${program#*:}"
if [ "${program%%:*}" = host ]; then
docker run --rm --platform linux/amd64 --network none \
  -v "$WEBVIEW_OUTPUT_DIR:/out:ro" samsung-native-collector:bullseye \
  arm-linux-gnueabi-readelf -d "/out/${program#*:}" | python3 -c '
import sys
if "[libpthread.so.0]" not in sys.stdin.read():
    raise SystemExit("Host does not load libpthread at startup (see README, Startup crash)")
print("ARM build: libpthread loaded at startup")
'
fi
done
rm -rf "$WEBVIEW_OUTPUT_DIR/diagnostic" "$WEBVIEW_OUTPUT_DIR/hub"
cp -R "$source_dir/diagnostic" "$WEBVIEW_OUTPUT_DIR/"
# Native bundle: the shared unconfigured Hub sources minus the manifest, plus
# the native adapter loaded directly after model.js. web/ is not modified.
python3 - "$repo_dir" "$source_dir" "$WEBVIEW_OUTPUT_DIR/hub" <<'PY'
import shutil, sys
from pathlib import Path
repo, source, out = map(Path, sys.argv[1:])
sys.path.insert(0, str(repo))
from tvsetup.planner import hub_sources
out.mkdir(parents=True)
for name, data in hub_sources(None).items():
    if name != 'config.xml':
        (out / name).write_bytes(data)
shutil.copyfile(source / 'native-shim.js', out / 'native-shim.js')
# native-shim.css must block the first paint: it keeps the static default tiles
# transparent until the shim reveals the rendered Home. Appending it to the
# bundle's copy of style.css avoids another request while Chromium is starved.
page = (out / 'index.html').read_text()
if page.count('<link rel="stylesheet" href="style.css">') != 1:
    raise SystemExit('index.html no longer has exactly one style.css link')
with open(out / 'style.css', 'a') as css:
    css.write('\n' + (source / 'native-shim.css').read_text())
anchor = '<script src="model.js" defer></script>'
if page.count(anchor) != 1:
    raise SystemExit('index.html no longer has exactly one model.js script tag')
(out / 'index.html').write_text(page.replace(anchor, anchor + '\n  <script src="native-shim.js" defer></script>'))
print('Native Hub bundle:', ', '.join(sorted(p.name for p in out.iterdir())))
PY
