"""Test the Switch Controlled Light light platform."""

from __future__ import annotations

import pytest

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.switch_controlled_light.const import (
    CONF_CLOSE_TIMER,
    CONF_CONTROL_LIGHTS,
    CONF_SWITCHES,
    DOMAIN,
)

from tests.common import MockConfigEntry

pytestmark = pytest.mark.usefixtures("hass_states")


@pytest.fixture
async def hass_states(hass: HomeAssistant) -> None:
    """Register entities used by the test fixtures."""
    hass.states.async_set("switch.kitchen_a", STATE_ON, {"friendly_name": "A"})
    hass.states.async_set("switch.kitchen_b", STATE_OFF, {"friendly_name": "B"})
    hass.states.async_set(
        "light.kitchen_ceiling",
        STATE_ON,
        {
            ATTR_BRIGHTNESS: 200,
            ATTR_HS_COLOR: (30.0, 50.0),
            "color_mode": "hs",
            "supported_color_modes": ["hs"],
            "supported_features": 0,
        },
    )
    hass.states.async_set("timer.kitchen_auto_off", "idle")

    registry = er.async_get(hass)
    registry.async_get_or_create(domain="switch", platform="test", unique_id="a")
    registry.async_get_or_create(domain="switch", platform="test", unique_id="b")
    registry.async_get_or_create(domain="light", platform="test", unique_id="c")
    registry.async_get_or_create(domain="timer", platform="test", unique_id="t")


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a config entry and let the integration set itself up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "name": "Kitchen",
            CONF_SWITCHES: ["switch.kitchen_a", "switch.kitchen_b"],
            CONF_CONTROL_LIGHTS: "light.kitchen_ceiling",
            CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
        },
        entry_id="test_entry",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _record_service_calls(hass: HomeAssistant) -> list[dict]:
    """Subscribe to every call_service event so we can inspect forwarded calls."""
    calls: list[dict] = []

    async def listener(event: Event) -> None:
        calls.append(event.data)

    hass.bus.async_listen("call_service", listener)
    return calls


async def test_state_mirrors_controlled_light(hass: HomeAssistant) -> None:
    """Both switches on ⇒ virtual light is on and mirrors the controlled light."""
    await _setup_entry(hass)
    hass.states.async_set("switch.kitchen_b", STATE_ON, {})
    await hass.async_block_till_done()

    state = hass.states.get("light.kitchen")
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 200
    assert state.attributes[ATTR_HS_COLOR] == (30.0, 50.0)


async def test_state_off_when_any_switch_off(hass: HomeAssistant) -> None:
    """One of the required switches is off ⇒ virtual light reports off."""
    await _setup_entry(hass)
    state = hass.states.get("light.kitchen")
    assert state is not None
    assert state.state == STATE_OFF


async def test_turn_on_turns_on_off_switches(hass: HomeAssistant) -> None:
    """Calling turn_on turns on any off switches (via service)."""
    await _setup_entry(hass)
    assert await async_setup_component(hass, SWITCH_DOMAIN, {})
    assert await async_setup_component(hass, TIMER_DOMAIN, {})
    await hass.async_block_till_done()

    calls = _record_service_calls(hass)

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "light.kitchen", ATTR_BRIGHTNESS: 100},
        blocking=True,
    )
    await hass.async_block_till_done()

    switch_on = [c for c in calls if c["domain"] == SWITCH_DOMAIN]
    assert len(switch_on) == 1
    targets = switch_on[0]["service_data"][ATTR_ENTITY_ID]
    assert "switch.kitchen_b" in targets
    assert "switch.kitchen_a" not in targets

    light_on = [
        c
        for c in calls
        if c["domain"] == LIGHT_DOMAIN
        and c["service_data"].get(ATTR_ENTITY_ID) == "light.kitchen_ceiling"
    ]
    assert len(light_on) == 1
    assert light_on[0]["service_data"][ATTR_BRIGHTNESS] == 100


async def test_turn_off_only_targets_controlled_light(hass: HomeAssistant) -> None:
    """Calling turn_off forwards to the controlled light; no switches are touched."""
    await _setup_entry(hass)
    assert await async_setup_component(hass, SWITCH_DOMAIN, {})
    assert await async_setup_component(hass, TIMER_DOMAIN, {})
    await hass.async_block_till_done()

    calls = _record_service_calls(hass)

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "light.kitchen"},
        blocking=True,
    )
    await hass.async_block_till_done()

    switch_off = [c for c in calls if c["domain"] == SWITCH_DOMAIN]
    assert len(switch_off) == 0

    light_off = [
        c
        for c in calls
        if c["domain"] == LIGHT_DOMAIN
        and c["service"] == "turn_off"
        and c["service_data"].get(ATTR_ENTITY_ID) == "light.kitchen_ceiling"
    ]
    assert len(light_off) == 1

    timer_calls = [c for c in calls if c["domain"] == TIMER_DOMAIN]
    assert len(timer_calls) == 2  # cancel + start
    assert {c["service"] for c in timer_calls} == {"cancel", "start"}