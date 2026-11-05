"""Constants for the Switch Controlled Light integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "switch_controlled_light"
PLATFORMS: list[Platform] = [Platform.LIGHT]

CONF_CLOSE_TIMER = "timer"
CONF_CONFIRM_DELETE = "confirm_delete"
CONF_CONTROL_LIGHTS = "control_lights"
CONF_DELETE_LIGHT = "delete_light"
CONF_SWITCHES = "switches"

# Subentry type holding a single controlled light. A config entry may own
# several of these so one switch group can drive multiple lights.
SUBENTRY_TYPE_LIGHT = "light"

# Event fired by the timer integration when a timer finishes. The constant
# lives in ``homeassistant.components.timer`` on older releases and moved to
# ``homeassistant.components.timer.const`` later without being re-exported, so
# the event name is spelled out here to stay compatible with both.
EVENT_TIMER_FINISHED = "timer.finished"
