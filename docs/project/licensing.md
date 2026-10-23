# Licensing

Couchroot's original code and documentation are licensed under [0BSD](../../LICENSE).
Attribution is welcome but is not required for that original work.

Bundled third-party code retains its own license:

- `agent/service/vendor/`: Vetro modules, MIT. Preserve the
  [copyright and license notice](../../agent/service/vendor/LICENSE).
- `tests/autonomous-root/protocol.test.cjs`: adapted from Vetro, MIT; its
  source header points to the retained Vetro license.
- Exact upstream revisions and file hashes are in
  [UPSTREAM.json](../../agent/UPSTREAM.json).

Samsung TV root C# payloads are obtained through the pinned Vetro source tree
and built locally; their source is not bundled here. `agent/payload/` contains
only the retained [Unlicense notice](../../agent/payload/LICENSE).

[Sources & Credits](credits.md) distinguishes bundled code from research references.
Dependencies are fetched from their maintainers and retain their own licenses.
Samsung SDKs, firmware, vendor libraries, signing material and installed app
binaries are not distributed here. Product names and app marks identify compatible
services; no trademark rights or endorsement are granted by this project's license.
