"""Test the Switch Controlled Light config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.switch_controlled_light.const import (
    CONF_CLOSE_TIMER,
    CONF_CONTROL_LIGHTS,
    CONF_SWITCHES,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("mock_dependencies")


@pytest.fixture
async def mock_dependencies(hass: HomeAssistant) -> AsyncMock:
    """Register a few entities the config flow expects to pick."""
    hass.states.async_set("switch.kitchen", "off")
    hass.states.async_set("light.kitchen_ceiling", "off")
    hass.states.async_set("timer.kitchen_auto_off", "idle")

    registry = er.async_get(hass)
    registry.async_get_or_create(domain="switch", platform="test", unique_id="k1")
    registry.async_get_or_create(domain="light", platform="test", unique_id="l1")
    registry.async_get_or_create(domain="timer", platform="test", unique_id="t1")
    return AsyncMock()


async def test_show_user_form(hass: HomeAssistant) -> None:
    """The user step is rendered with the expected fields."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_create_entry(hass: HomeAssistant) -> None:
    """Submitting the form yields a finished config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen",
            CONF_SWITCHES: ["switch.kitchen"],
            CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
            CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    # SchemaConfigFlowHandler stores the user input in ``options``, leaving
    # ``data`` empty.
    assert result["options"] == {
        CONF_NAME: "Kitchen",
        CONF_SWITCHES: ["switch.kitchen"],
        CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
        CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
    }


async def test_duplicate_aborted(hass: HomeAssistant) -> None:
    """Configuring the same combination twice aborts as already configured."""
    user_input = {
        CONF_NAME: "Kitchen",
        CONF_SWITCHES: ["switch.kitchen"],
        CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
