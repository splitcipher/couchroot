# Offline MQTT MAIN-window model

`tvwindow.cjs` is a bounded read-only normalizer tested with synthetic APIs. It is
not packaged, imported by the service, or enabled by any MQTT flag. The production
agent does not request TV-window privilege. No hardware was contacted.

Samsung's [TVWindow API](https://developer.samsung.com/smarttv/develop/api-references/tizen-web-device-api-references/tvwindow-api.html)
returns the selected input and timing for a TV window. That window may be hidden
behind a native streaming app. A signal-present flag is not a visibility test.
The model accepts only explicit signal presence, known source IDs and bounded
integer pixel/Hz values; it makes no claim about the visible picture.

Promotion requires per-model/per-firmware evidence for visible-source ownership,
no-signal and stale-timing behavior, HDMI/TV/streaming transitions, CEC labels and
actual units. Add those fixtures and the qualified foreground gate before a
production adapter can enable Input/Resolution/Refresh rate. Do not probe setters,
show/hide a window, switch source or launch a foreground helper to obtain state.
See the [feature-2 guide](../../docs/guides/mqtt-state.md) for the full boundary.
