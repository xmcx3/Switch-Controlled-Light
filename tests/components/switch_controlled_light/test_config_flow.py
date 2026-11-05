"""Test the Switch Controlled Light config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

try:
    from homeassistant.components.switch_controlled_light.const import (
        CONF_CLOSE_TIMER,
        CONF_CONTROL_LIGHTS,
        CONF_SWITCHES,
        DOMAIN,
        SUBENTRY_TYPE_LIGHT,
    )
except ImportError:
    from custom_components.switch_controlled_light.const import (
        CONF_CLOSE_TIMER,
        CONF_CONTROL_LIGHTS,
        CONF_SWITCHES,
        DOMAIN,
        SUBENTRY_TYPE_LIGHT,
    )
pytestmark = pytest.mark.usefixtures("mock_dependencies")


@pytest.fixture
async def mock_dependencies(hass: HomeAssistant) -> AsyncMock:
    """Register a few entities the config flow expects to pick."""
    hass.states.async_set("switch.kitchen", "off")
    hass.states.async_set("light.kitchen_ceiling", "off")
    hass.states.async_set("light.kitchen_lamp", "off")
    hass.states.async_set("timer.kitchen_auto_off", "idle")

    registry = er.async_get(hass)
    registry.async_get_or_create(domain="switch", platform="test", unique_id="k1")
    registry.async_get_or_create(domain="light", platform="test", unique_id="l1")
    registry.async_get_or_create(domain="light", platform="test", unique_id="l2")
    registry.async_get_or_create(domain="timer", platform="test", unique_id="t1")
    return AsyncMock()


async def _create_entry(hass: HomeAssistant) -> config_entries.ConfigEntry:
    """Create a config entry through the user flow and add its first light."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen",
            CONF_SWITCHES: ["switch.kitchen"],
            CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    flow_type, flow_id = result["next_flow"]
    assert flow_type is config_entries.FlowType.CONFIG_SUBENTRIES_FLOW
    subentry_result = await hass.config_entries.subentries.async_configure(
        flow_id,
        user_input={
            CONF_NAME: "Kitchen",
            CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
        },
    )
    assert subentry_result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    return hass.config_entries.async_get_entry(result["result"].entry_id)


async def test_show_user_form(hass: HomeAssistant) -> None:
    """The user step is rendered with the expected fields."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert CONF_CONTROL_LIGHTS not in result["data_schema"].schema


async def test_create_entry(hass: HomeAssistant) -> None:
    """Submitting the user form creates the entry and continues with the light."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen",
            CONF_SWITCHES: ["switch.kitchen"],
            CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    # SchemaConfigFlowHandler stores the user input in ``options``, leaving
    # ``data`` empty. The controlled light is no longer part of the options.
    assert result["options"] == {
        CONF_NAME: "Kitchen",
        CONF_SWITCHES: ["switch.kitchen"],
        CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
    }
    assert result["next_flow"][0] is config_entries.FlowType.CONFIG_SUBENTRIES_FLOW
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(result["result"].entry_id)
    subentry_result = await hass.config_entries.subentries.async_configure(
        result["next_flow"][1],
        user_input={
            CONF_NAME: "Kitchen",
            CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
        },
    )
    assert subentry_result["type"] is FlowResultType.CREATE_ENTRY
    assert subentry_result["title"] == "Kitchen"
    await hass.async_block_till_done()

    subentries = entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
    assert len(subentries) == 1
    assert subentries[0].data == {CONF_CONTROL_LIGHTS: "light.kitchen_ceiling"}
    assert subentries[0].unique_id == "light.kitchen_ceiling"
    assert hass.states.get("light.kitchen_ceiling_2") is not None


async def test_duplicate_aborted(hass: HomeAssistant) -> None:
    """Configuring the same combination twice aborts as already configured."""
    user_input = {
        CONF_NAME: "Kitchen",
        CONF_SWITCHES: ["switch.kitchen"],
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], user_input)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_add_second_light_subentry(hass: HomeAssistant) -> None:
    """A second light subentry can be added without disturbing the first."""
    entry = await _create_entry(hass)

    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    first_entity = registry.async_get("light.kitchen_ceiling_2")
    assert first_entity is not None
    first_device_id = first_entity.device_id

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen lamp",
            CONF_CONTROL_LIGHTS: "light.kitchen_lamp",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)) == 2
    assert hass.states.get("light.kitchen_lamp_2") is not None
    # Adding the second light must not disturb the first one or its device.
    assert hass.states.get("light.kitchen_ceiling_2") is not None
    first_entity = registry.async_get("light.kitchen_ceiling_2")
    assert first_entity is not None
    assert first_entity.device_id == first_device_id
    assert devices.async_get(first_device_id or "") is not None

    second_entity = registry.async_get("light.kitchen_lamp_2")
    assert second_entity is not None
    assert second_entity.device_id != first_device_id
    second_device = devices.async_get(second_entity.device_id or "")
    assert second_device is not None
    assert second_device.config_subentry_id == second_entity.config_subentry_id


async def test_duplicate_light_aborted(hass: HomeAssistant) -> None:
    """The same controlled light cannot be added twice to one entry."""
    entry = await _create_entry(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Duplicate",
            CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)) == 1


async def test_reconfigure_light_subentry(hass: HomeAssistant) -> None:
    """Reconfiguring a light subentry updates its data and title."""
    entry = await _create_entry(hass)
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)[0]

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={
            "source": SOURCE_RECONFIGURE,
            "subentry_id": subentry.subentry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen lamp",
            CONF_CONTROL_LIGHTS: "light.kitchen_lamp",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    subentry = entry.subentries[subentry.subentry_id]
    assert subentry.title == "Kitchen lamp"
    assert subentry.data == {CONF_CONTROL_LIGHTS: "light.kitchen_lamp"}
    assert subentry.unique_id == "light.kitchen_lamp"


async def test_reconfigure_to_used_light_aborted(hass: HomeAssistant) -> None:
    """Reconfiguring to a light already used by another subentry is rejected."""
    entry = await _create_entry(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen lamp",
            CONF_CONTROL_LIGHTS: "light.kitchen_lamp",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    lamp_subentry = next(
        subentry
        for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
        if subentry.unique_id == "light.kitchen_lamp"
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={
            "source": SOURCE_RECONFIGURE,
            "subentry_id": lamp_subentry.subentry_id,
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Kitchen lamp",
            CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_delete_light_subentry_flow(hass: HomeAssistant) -> None:
    """The delete step removes only the selected controlled light."""
    entry = await _create_entry(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        user_input={
            CONF_NAME: "Lamp",
            CONF_CONTROL_LIGHTS: "light.kitchen_lamp",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    kitchen_entry = registry.async_get("light.kitchen_ceiling_2")
    lamp_entry = registry.async_get("light.kitchen_lamp_2")
    assert kitchen_entry is not None
    assert lamp_entry is not None
    # Different lights own different devices, each attributed to its subentry.
    assert kitchen_entry.device_id != lamp_entry.device_id
    devices = dr.async_get(hass)
    kitchen_device = devices.async_get(kitchen_entry.device_id or "")
    lamp_device = devices.async_get(lamp_entry.device_id or "")
    assert kitchen_device is not None
    assert lamp_device is not None
    assert kitchen_device.config_subentry_id == kitchen_entry.config_subentry_id
    assert lamp_device.config_subentry_id == lamp_entry.config_subentry_id
    assert lamp_device.identifiers == {(DOMAIN, lamp_entry.config_subentry_id or "")}
    kitchen_device_id = kitchen_device.id

    lamp_subentry = next(
        subentry
        for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
        if subentry.title == "Lamp"
    )

    # HA core has no SOURCE_DELETE; the flow manager uses the source as the
    # initial step id, so a "delete" source starts async_step_delete.
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_LIGHT),
        context={
            "source": "delete",
            "subentry_id": lamp_subentry.subentry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "delete"

    result = await hass.config_entries.subentries.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "delete_successful"
    await hass.async_block_till_done()

    assert lamp_subentry.subentry_id not in entry.subentries
    assert hass.states.get("light.kitchen_lamp_2") is None
    assert registry.async_get("light.kitchen_lamp_2") is None
    assert devices.async_get(lamp_entry.device_id or "") is None
    # The other light and its device are untouched.
    assert hass.states.get("light.kitchen_ceiling_2") is not None
    remaining_entry = registry.async_get("light.kitchen_ceiling_2")
    assert remaining_entry is not None
    # Deleting a sibling must not rename the remaining light or move its device.
    assert remaining_entry.entity_id == "light.kitchen_ceiling_2"
    assert remaining_entry.device_id == kitchen_device_id
    assert devices.async_get(kitchen_device_id) is not None
    assert entry.state is config_entries.ConfigEntryState.LOADED
