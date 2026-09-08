# Switch Controlled Light

A virtual light entity that mirrors a chosen light's state, brightness, color
and effects — but is only considered *on* when every selected switch is on.

## Use cases

- Only light a room when the door contact is closed and the motion sensor's
  relay is on.
- Force a smart bulb to follow a wall switch's state without losing color and
  brightness control.
- Combine with an `input_boolean` or `input_number` (via a `template switch`)
  to drive complex conditions without writing YAML.

## Features

- Mirrors all light attributes from the controlled entity (HS/RGB/RGBW/RGBWW
  color, color temperature, brightness, effects, transitions).
- Reports `available` only when every tracked entity is available.
- Optional auto-close timer that switches the controlled switches off when the
  timer finishes.
- Bronze-tier Home Assistant quality scale: config flow, options flow,
  tests, translations.

## Installation

### HACS (recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed.
2. Add this repository as a **Custom repository** in HACS (category
   *Integration*).
3. Install *Switch Controlled Light* from HACS.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/switch_controlled_light/` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

*Settings → Devices & Services → Add integration → Switch Controlled Light*

You will be asked for:

- **Name** — the friendly name used for the device and the virtual light.
- **Required switches** — one or more switches; every one must be on for the
  virtual light to report `on`.
- **Controlled light** — the underlying light entity whose state is mirrored.
- **Auto-close timer (optional)** — a `timer.*` entity that is restarted on
  every on/off action; when it finishes, the required switches are turned off.

## Limitations

- The integration only reports `on` when *all* required switches are on. It
  does not turn them off automatically except through the optional timer.
- The virtual light is read-only regarding the controlled light's underlying
  state — if you turn the controlled light on manually while a required
  switch is off, the virtual light will still report `off`.

## Development

```bash
# Lint and format
uv run prek run --all-files

# Run tests
uv run pytest tests/test_config_flow.py
```