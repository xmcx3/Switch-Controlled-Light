"""Constants for the Switch Controlled Light integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "switch_controlled_light"
PLATFORMS: list[Platform] = [Platform.LIGHT]

CONF_CLOSE_TIMER = "timer"
CONF_CONTROL_LIGHTS = "control_lights"
CONF_SWITCHES = "switches"
