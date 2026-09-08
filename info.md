# Switch Controlled Light

A virtual light entity that mirrors a chosen light's state, brightness, color
and effects — but is only considered *on* when every selected switch is on.

## Configuration

- **Name** — friendly name used for the device and the virtual light.
- **Required switches** — one or more switches; every one must be on for the
  virtual light to report `on`.
- **Controlled light** — the underlying light entity whose state is mirrored.
- **Auto-close timer (optional)** — a `timer.*` entity that is restarted on
  every on/off action; when it finishes, the required switches are turned off.

See the [repository README](https://github.com/xmcx3/switch_controlled_light)
for installation instructions and details.