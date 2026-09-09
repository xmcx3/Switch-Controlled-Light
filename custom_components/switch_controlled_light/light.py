"""Support for Switch Controlled Light."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import light as light_domain
from homeassistant.components import switch as switch_domain
from homeassistant.components import timer as timer_domain
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_MAX_COLOR_TEMP_KELVIN,
    ATTR_MIN_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ATTR_WHITE,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_CLOSE_TIMER, CONF_CONTROL_LIGHTS, CONF_SWITCHES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Attributes forwarded to the controlled light's turn_on service.
FORWARDED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        ATTR_BRIGHTNESS,
        ATTR_COLOR_TEMP_KELVIN,
        ATTR_EFFECT,
        ATTR_FLASH,
        ATTR_HS_COLOR,
        ATTR_RGB_COLOR,
        ATTR_RGBW_COLOR,
        ATTR_RGBWW_COLOR,
        ATTR_TRANSITION,
        ATTR_WHITE,
        ATTR_XY_COLOR,
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Switch Controlled Light from a config entry."""
    name: str = entry.options["name"]
    switch_entity_ids: list[str] = list(entry.options[CONF_SWITCHES])
    control_light_entity_id: str = entry.options[CONF_CONTROL_LIGHTS]
    timer_id: str | None = entry.options.get(CONF_CLOSE_TIMER)

    async_add_entities(
        [
            SwitchControlledLight(
                hass,
                name,
                switch_entity_ids,
                control_light_entity_id,
                timer_id,
                entry.entry_id,
            )
        ]
    )


class SwitchControlledLight(LightEntity):
    """Representation of a Switch Controlled Light."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        switch_entity_ids: list[str],
        control_light_entity_id: str,
        timer_id: str | None,
        entry_id: str,
    ) -> None:
        """Initialize the Switch Controlled Light."""
        self._hass = hass
        self._switch_entity_ids = switch_entity_ids
        self._control_light_entity_id = control_light_entity_id
        self._timer_id = timer_id

        # Until the controlled light has reported state we cannot derive
        # accurate capabilities; fall back to on/off as the safe default.
        self._attr_color_mode: ColorMode | str | None = ColorMode.UNKNOWN
        self._attr_supported_color_modes: set[ColorMode | str] | None = {ColorMode.ONOFF}

        self._attr_unique_id = f"{entry_id}_{control_light_entity_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="Switch Controlled Light",
        )

    async def async_added_to_hass(self) -> None:
        """Register state change listeners when the entity is added."""
        await super().async_added_to_hass()

        for switch_entity_id in self._switch_entity_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self._hass, switch_entity_id, self._switch_state_changed
                )
            )

        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                self._control_light_entity_id,
                self._control_light_state_changed,
            )
        )

        self._update_state()

    @callback
    def _switch_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle switch state changes."""
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _control_light_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle controlled light state changes."""
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _update_state(self) -> None:
        """Update the entity state from switches and the controlled light."""
        light_state = self._hass.states.get(self._control_light_entity_id)
        if light_state is None:
            return

        switch_states = [
            state
            for switch_id in self._switch_entity_ids
            if (state := self._hass.states.get(switch_id)) is not None
        ]
        all_states = [light_state, *switch_states]

        self._attr_available = all(state.state != STATE_UNAVAILABLE for state in all_states)
        self._attr_is_on = all(state.state == STATE_ON for state in all_states)

        attrs = light_state.attributes
        self._attr_brightness = attrs.get(ATTR_BRIGHTNESS)
        self._attr_hs_color = attrs.get(ATTR_HS_COLOR)
        self._attr_rgb_color = attrs.get(ATTR_RGB_COLOR)
        self._attr_rgbw_color = attrs.get(ATTR_RGBW_COLOR)
        self._attr_rgbww_color = attrs.get(ATTR_RGBWW_COLOR)
        self._attr_xy_color = attrs.get(ATTR_XY_COLOR)
        self._attr_color_temp_kelvin = attrs.get(ATTR_COLOR_TEMP_KELVIN)
        self._attr_min_color_temp_kelvin = attrs.get(ATTR_MIN_COLOR_TEMP_KELVIN)
        self._attr_max_color_temp_kelvin = attrs.get(ATTR_MAX_COLOR_TEMP_KELVIN)
        self._attr_effect_list = attrs.get(ATTR_EFFECT_LIST)
        self._attr_effect = attrs.get(ATTR_EFFECT)

        color_mode = attrs.get(ATTR_COLOR_MODE)
        if (supported := attrs.get(ATTR_SUPPORTED_COLOR_MODES)) is not None:
            self._attr_supported_color_modes = set(supported)
            if color_mode is None:
                # Some lights omit color_mode from their state; fall back to the
                # first supported mode so HA's on-state validation passes.
                self._attr_color_mode = (
                    next(iter(self._attr_supported_color_modes))
                    if len(self._attr_supported_color_modes) == 1
                    else ColorMode.UNKNOWN
                )
            else:
                self._attr_color_mode = color_mode
        elif color_mode is not None:
            self._attr_color_mode = color_mode
        self._attr_supported_features = (
            LightEntityFeature(0)
            if (features := attrs.get("supported_features")) is None
            else LightEntityFeature(features)
        )

    async def _restart_timer(self) -> None:
        """Restart the configured auto-close timer, if any."""
        if not self._timer_id:
            return

        await self._hass.services.async_call(
            timer_domain.DOMAIN,
            timer_domain.SERVICE_CANCEL,
            {ATTR_ENTITY_ID: self._timer_id},
            blocking=True,
            context=self._context,
        )
        await self._hass.services.async_call(
            timer_domain.DOMAIN,
            timer_domain.SERVICE_START,
            {ATTR_ENTITY_ID: self._timer_id},
            blocking=True,
            context=self._context,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the virtual light on by energizing switches and the controlled light."""
        service_data = {key: value for key, value in kwargs.items() if key in FORWARDED_ATTRIBUTES}
        service_data[ATTR_ENTITY_ID] = self._control_light_entity_id

        off_switches = [
            switch_id
            for switch_id in self._switch_entity_ids
            if (state := self._hass.states.get(switch_id)) is not None and state.state == STATE_OFF
        ]

        await self._hass.services.async_call(
            switch_domain.DOMAIN,
            switch_domain.SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: off_switches},
            blocking=True,
            context=self._context,
        )
        await self._hass.services.async_call(
            light_domain.DOMAIN,
            light_domain.SERVICE_TURN_ON,
            service_data,
            blocking=True,
            context=self._context,
        )
        await self._restart_timer()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the virtual light off by switching the controlled light off."""
        data: dict[str, Any] = {ATTR_ENTITY_ID: self._control_light_entity_id}
        if ATTR_TRANSITION in kwargs:
            data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]

        await self._hass.services.async_call(
            light_domain.DOMAIN,
            light_domain.SERVICE_TURN_OFF,
            data,
            blocking=True,
            context=self._context,
        )
        await self._restart_timer()
