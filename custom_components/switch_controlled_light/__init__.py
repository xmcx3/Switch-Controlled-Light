"""The Switch Controlled Light integration."""

from __future__ import annotations

import logging

from homeassistant.components import switch as switch_domain
from homeassistant.components import timer
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_CLOSE_TIMER, CONF_SWITCHES, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Switch Controlled Light integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Switch Controlled Light from a config entry."""
    timer_entity_id: str | None = entry.options.get(CONF_CLOSE_TIMER)
    switch_entity_ids: list[str] = entry.options[CONF_SWITCHES]

    async def auto_close_switch(event: Event) -> None:
        if event.data.get("entity_id") != timer_entity_id:
            return
        await hass.services.async_call(
            switch_domain.DOMAIN,
            switch_domain.SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: switch_entity_ids},
            blocking=False,
        )

    if timer_entity_id:
        entry.async_on_unload(
            hass.bus.async_listen(timer.EVENT_TIMER_FINISHED, auto_close_switch)
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
