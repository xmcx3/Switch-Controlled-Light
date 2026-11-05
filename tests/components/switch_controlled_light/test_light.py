"""Test the Switch Controlled Light light platform."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
)
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

try:
    from homeassistant.components.switch_controlled_light import (
        async_migrate_entry as migrate_entry,
    )
    from homeassistant.components.switch_controlled_light.const import (
        CONF_CLOSE_TIMER,
        CONF_CONFIRM_DELETE,
        CONF_CONTROL_LIGHTS,
        CONF_DELETE_LIGHT,
        CONF_SWITCHES,
        DOMAIN,
        SUBENTRY_TYPE_LIGHT,
    )
except ImportError:
    from custom_components.switch_controlled_light import (
        async_migrate_entry as migrate_entry,
    )
    from custom_components.switch_controlled_light.const import (
        CONF_CLOSE_TIMER,
        CONF_CONFIRM_DELETE,
        CONF_CONTROL_LIGHTS,
        CONF_DELETE_LIGHT,
        CONF_SWITCHES,
        DOMAIN,
        SUBENTRY_TYPE_LIGHT,
    )

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
    hass.states.async_set(
        "light.living_room_ceiling",
        STATE_ON,
        {
            ATTR_BRIGHTNESS: 80,
            "color_mode": "brightness",
            "supported_color_modes": ["brightness"],
            "supported_features": 0,
        },
    )
    hass.states.async_set("timer.kitchen_auto_off", "idle")

    registry = er.async_get(hass)
    registry.async_get_or_create(domain="switch", platform="test", unique_id="a")
    registry.async_get_or_create(domain="switch", platform="test", unique_id="b")
    registry.async_get_or_create(domain="light", platform="test", unique_id="c")
    registry.async_get_or_create(domain="light", platform="test", unique_id="d")
    registry.async_get_or_create(domain="timer", platform="test", unique_id="t")


def _light_subentry(control_light: str, title: str) -> dict:
    """Build a ``light`` subentry payload for ``MockConfigEntry``."""
    return {
        "data": {CONF_CONTROL_LIGHTS: control_light},
        "subentry_type": SUBENTRY_TYPE_LIGHT,
        "title": title,
        "unique_id": control_light,
    }


async def _setup_entry(
    hass: HomeAssistant,
    subentries: list[dict] | None = None,
) -> MockConfigEntry:
    """Add a config entry and let the integration set itself up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "name": "Kitchen",
            CONF_SWITCHES: ["switch.kitchen_a", "switch.kitchen_b"],
            CONF_CLOSE_TIMER: "timer.kitchen_auto_off",
        },
        subentries_data=(
            [_light_subentry("light.kitchen_ceiling", "Kitchen")]
            if subentries is None
            else subentries
        ),
        entry_id="test_entry",
        version=2,
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

    state = hass.states.get("light.kitchen_ceiling_2")
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_BRIGHTNESS] == 200
    assert state.attributes[ATTR_HS_COLOR] == (30.0, 50.0)


async def test_state_off_when_any_switch_off(hass: HomeAssistant) -> None:
    """One of the required switches is off ⇒ virtual light reports off."""
    await _setup_entry(hass)
    state = hass.states.get("light.kitchen_ceiling_2")
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
        {ATTR_ENTITY_ID: "light.kitchen_ceiling_2", ATTR_BRIGHTNESS: 100},
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
        {ATTR_ENTITY_ID: "light.kitchen_ceiling_2"},
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


async def test_multiple_subentries_create_independent_lights(
    hass: HomeAssistant,
) -> None:
    """Each light gets its own entity and its own subentry-owned device."""
    entry = await _setup_entry(
        hass,
        subentries=[
            _light_subentry("light.kitchen_ceiling", "Kitchen"),
            _light_subentry("light.living_room_ceiling", "Living Room"),
        ],
    )

    kitchen = hass.states.get("light.kitchen_ceiling_2")
    living_room = hass.states.get("light.living_room_ceiling_2")
    assert kitchen is not None
    assert living_room is not None
    # switch.kitchen_b is off, so both virtual lights are off initially.
    assert kitchen.state == STATE_OFF
    assert living_room.state == STATE_OFF

    registry = er.async_get(hass)
    kitchen_entry = registry.async_get("light.kitchen_ceiling_2")
    living_room_entry = registry.async_get("light.living_room_ceiling_2")
    assert kitchen_entry is not None
    assert living_room_entry is not None
    assert kitchen_entry.unique_id != living_room_entry.unique_id
    # The entity id follows the controlled light, not the subentry title and
    # definitely not the shared device name. The underlying light owns its own
    # entity id, so HA adds a numeric suffix to the virtual one.
    assert kitchen_entry.entity_id == "light.kitchen_ceiling_2"
    assert living_room_entry.entity_id == "light.living_room_ceiling_2"
    assert not living_room_entry.entity_id.startswith("light.kitchen_")
    subentry_ids = {subentry.subentry_id for subentry in entry.subentries.values()}
    assert kitchen_entry.config_subentry_id in subentry_ids
    assert living_room_entry.config_subentry_id in subentry_ids
    assert kitchen_entry.config_subentry_id != living_room_entry.config_subentry_id

    devices = dr.async_get(hass)
    kitchen_device = devices.async_get(kitchen_entry.device_id or "")
    living_room_device = devices.async_get(living_room_entry.device_id or "")
    assert kitchen_device is not None
    assert living_room_device is not None
    # HA's device registry only allows one subentry per device, so every light
    # gets its own device, attributed to its own subentry.
    assert kitchen_device.id != living_room_device.id
    assert kitchen_device.name == "Kitchen"
    assert living_room_device.name == "Living Room"
    assert kitchen_device.config_subentry_id == kitchen_entry.config_subentry_id
    assert living_room_device.config_subentry_id == living_room_entry.config_subentry_id
    assert kitchen_device.identifiers == {(DOMAIN, kitchen_entry.config_subentry_id or "")}
    assert living_room_device.identifiers == {(DOMAIN, living_room_entry.config_subentry_id or "")}

    # Both switches on; both virtual lights mirror their own controlled light.
    hass.states.async_set("switch.kitchen_b", STATE_ON, {})
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_ceiling_2").state == STATE_ON
    assert hass.states.get("light.living_room_ceiling_2").state == STATE_ON

    # Turning off the living room light must not affect the kitchen light.
    hass.states.async_set("light.living_room_ceiling", STATE_OFF, {})
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_ceiling_2").state == STATE_ON
    assert hass.states.get("light.living_room_ceiling_2").state == STATE_OFF


async def test_turn_on_targets_only_own_controlled_light(hass: HomeAssistant) -> None:
    """Turning on one virtual light forwards to its own controlled light only."""
    await _setup_entry(
        hass,
        subentries=[
            _light_subentry("light.kitchen_ceiling", "Kitchen"),
            _light_subentry("light.living_room_ceiling", "Living Room"),
        ],
    )
    assert await async_setup_component(hass, SWITCH_DOMAIN, {})
    assert await async_setup_component(hass, TIMER_DOMAIN, {})
    await hass.async_block_till_done()

    calls = _record_service_calls(hass)

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "light.living_room_ceiling_2"},
        blocking=True,
    )
    await hass.async_block_till_done()

    light_calls = [
        c for c in calls if c["domain"] == LIGHT_DOMAIN and c["service"] == SERVICE_TURN_ON
    ]
    targets = [c["service_data"][ATTR_ENTITY_ID] for c in light_calls]
    assert "light.living_room_ceiling" in targets
    assert "light.kitchen_ceiling" not in targets


async def test_removing_subentry_removes_entity(hass: HomeAssistant) -> None:
    """Removing a light subentry removes its entity and its device."""
    entry = await _setup_entry(hass)
    subentry_id = next(iter(entry.subentries))

    registry = er.async_get(hass)
    registry_entry = registry.async_get("light.kitchen_ceiling_2")
    assert registry_entry is not None
    device_id = registry_entry.device_id

    hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()

    assert subentry_id not in entry.subentries
    assert hass.states.get("light.kitchen_ceiling_2") is None
    assert registry.async_get("light.kitchen_ceiling_2") is None
    # The device belongs to the removed subentry, so it is cleaned up too.
    assert dr.async_get(hass).async_get(device_id or "") is None
    assert entry.state is ConfigEntryState.LOADED


async def test_adding_and_removing_light_keeps_sibling_intact(
    hass: HomeAssistant,
) -> None:
    """Adding or removing a light must not touch another light's entity/device."""
    entry = await _setup_entry(hass)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)

    kitchen_entity = registry.async_get("light.kitchen_ceiling_2")
    assert kitchen_entity is not None
    kitchen_device_id = kitchen_entity.device_id
    kitchen_device = devices.async_get(kitchen_device_id or "")
    assert kitchen_device is not None
    kitchen_subentry_id = kitchen_entity.config_subentry_id

    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MappingProxyType({CONF_CONTROL_LIGHTS: "light.living_room_ceiling"}),
            subentry_type=SUBENTRY_TYPE_LIGHT,
            title="Living Room",
            unique_id="light.living_room_ceiling",
        ),
    )
    await hass.async_block_till_done()

    # The existing light keeps its entity and its device.
    kitchen_entity = registry.async_get("light.kitchen_ceiling_2")
    assert kitchen_entity is not None
    assert kitchen_entity.device_id == kitchen_device_id
    assert kitchen_entity.config_subentry_id == kitchen_subentry_id
    assert dr.async_get(hass).async_get(kitchen_device_id or "") is not None

    # The new light gets its own device and subentry attribution.
    living_entity = registry.async_get("light.living_room_ceiling_2")
    assert living_entity is not None
    assert living_entity.device_id != kitchen_device_id
    living_device = dr.async_get(hass).async_get(living_entity.device_id or "")
    assert living_device is not None
    assert living_device.config_subentry_id == living_entity.config_subentry_id
    assert living_device.identifiers == {(DOMAIN, living_entity.config_subentry_id or "")}

    living_subentry_id = living_entity.config_subentry_id
    assert living_subentry_id is not None
    hass.config_entries.async_remove_subentry(entry, living_subentry_id)
    await hass.async_block_till_done()

    # Removing the sibling leaves the first light and its device untouched.
    assert hass.states.get("light.kitchen_ceiling_2") is not None
    kitchen_entity = registry.async_get("light.kitchen_ceiling_2")
    assert kitchen_entity is not None
    assert kitchen_entity.device_id == kitchen_device_id
    assert dr.async_get(hass).async_get(kitchen_device_id or "") is not None
    assert hass.states.get("light.living_room_ceiling_2") is None
    assert registry.async_get("light.living_room_ceiling_2") is None
    assert dr.async_get(hass).async_get(living_entity.device_id or "") is None


async def test_options_flow_updates_and_reloads_entry(hass: HomeAssistant) -> None:
    """Options flow updates entry.options and reloads; subentries are kept."""
    entry = await _setup_entry(hass)
    subentry_id = next(iter(entry.subentries))

    # A new switch we'll switch to; the original kitchen_b will be dropped.
    hass.states.async_set("switch.kitchen_c", STATE_OFF, {"friendly_name": "C"})
    registry = er.async_get(hass)
    registry.async_get_or_create(domain="switch", platform="test", unique_id="c")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SWITCHES: ["switch.kitchen_a", "switch.kitchen_c"],
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # Entry options reflect the submission and the entry was reloaded cleanly.
    assert entry.options[CONF_SWITCHES] == ["switch.kitchen_a", "switch.kitchen_c"]
    assert CONF_CLOSE_TIMER not in entry.options
    assert entry.state is ConfigEntryState.LOADED
    assert subentry_id in entry.subentries

    # The virtual light now considers kitchen_c (off) instead of kitchen_b.
    # With kitchen_a on and kitchen_c off, the virtual light must be off.
    state = hass.states.get("light.kitchen_ceiling_2")
    assert state is not None
    assert state.state == STATE_OFF


async def test_options_flow_deletes_single_light(hass: HomeAssistant) -> None:
    """The options flow can delete one controlled light without the entry."""
    entry = await _setup_entry(
        hass,
        subentries=[
            _light_subentry("light.kitchen_ceiling", "Kitchen"),
            _light_subentry("light.living_room_ceiling", "Living Room"),
        ],
    )
    living_room_subentry = next(
        subentry for subentry in entry.subentries.values() if subentry.title == "Living Room"
    )

    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    living_entity = registry.async_get("light.living_room_ceiling_2")
    kitchen_entity = registry.async_get("light.kitchen_ceiling_2")
    assert living_entity is not None
    assert kitchen_entity is not None
    living_device_id = living_entity.device_id
    kitchen_device_id = kitchen_entity.device_id
    assert living_device_id != kitchen_device_id

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    # The deletion selector is only offered when a light exists.
    assert any(
        getattr(key, "schema", key) == CONF_DELETE_LIGHT for key in result["data_schema"].schema
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SWITCHES: ["switch.kitchen_a", "switch.kitchen_b"],
            CONF_DELETE_LIGHT: living_room_subentry.subentry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "delete_light"

    # Declining the confirmation keeps the light.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIRM_DELETE: False},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "delete_not_confirmed"}
    assert living_room_subentry.subentry_id in entry.subentries

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_CONFIRM_DELETE: True},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert living_room_subentry.subentry_id not in entry.subentries
    assert hass.states.get("light.living_room_ceiling_2") is None
    assert hass.states.get("light.kitchen_ceiling_2") is not None
    assert entry.state is ConfigEntryState.LOADED
    # The deletion-only fields never leak into the stored options.
    assert CONF_DELETE_LIGHT not in entry.options
    assert CONF_CONFIRM_DELETE not in entry.options

    registry = er.async_get(hass)
    assert registry.async_get("light.living_room_ceiling_2") is None
    remaining_entry = registry.async_get("light.kitchen_ceiling_2")
    assert remaining_entry is not None
    # Deleting a sibling must not rename the remaining light or remove/move its
    # device. The deleted light's own device is cleaned up with its subentry.
    assert remaining_entry.entity_id == "light.kitchen_ceiling_2"
    assert remaining_entry.device_id == kitchen_device_id
    assert devices.async_get(kitchen_device_id or "") is not None
    assert devices.async_get(living_device_id or "") is None

    # The remaining light still works.
    hass.states.async_set("switch.kitchen_b", STATE_ON, {})
    await hass.async_block_till_done()
    assert hass.states.get("light.kitchen_ceiling_2").state == STATE_ON


async def test_existing_entity_id_is_preserved(hass: HomeAssistant) -> None:
    """An already registered entity keeps its entity id after reload."""
    entry = await _setup_entry(hass)
    registry = er.async_get(hass)
    original = registry.async_get("light.kitchen_ceiling_2")
    assert original is not None

    # Simulate the user renaming the entity (or the id created by an older
    # version, e.g. light.kitchen). Reloading must keep the registry id even
    # though the integration now suggests a different object id.
    registry.async_update_entity(original.entity_id, new_entity_id="light.my_kitchen")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("light.my_kitchen") is not None
    assert hass.states.get("light.kitchen_ceiling_2") is None
    preserved = registry.async_get("light.my_kitchen")
    assert preserved is not None
    assert preserved.unique_id == original.unique_id
    assert entry.state is ConfigEntryState.LOADED


async def test_migrate_v1_entry_to_v2(hass: HomeAssistant) -> None:
    """A version 1 entry is migrated: the light moves into a subentry."""
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
        version=1,
    )
    entry.add_to_hass(hass)

    # Simulate the entity registry entry created by the old single-light code.
    registry = er.async_get(hass)
    old_registry_entry = registry.async_get_or_create(
        domain="light",
        platform=DOMAIN,
        unique_id="test_entry_light.kitchen_ceiling",
        config_entry=entry,
        suggested_object_id="kitchen",
    )
    assert old_registry_entry.entity_id == "light.kitchen"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.state is ConfigEntryState.LOADED
    assert CONF_CONTROL_LIGHTS not in entry.options
    assert entry.options[CONF_SWITCHES] == ["switch.kitchen_a", "switch.kitchen_b"]
    assert entry.options[CONF_CLOSE_TIMER] == "timer.kitchen_auto_off"

    subentries = entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
    assert len(subentries) == 1
    subentry = subentries[0]
    assert subentry.title == "Kitchen"
    assert subentry.data == {CONF_CONTROL_LIGHTS: "light.kitchen_ceiling"}
    assert subentry.unique_id == "light.kitchen_ceiling"

    # The existing registry entry was re-keyed instead of being duplicated.
    migrated_registry_entry = registry.async_get("light.kitchen")
    assert migrated_registry_entry is not None
    assert migrated_registry_entry.unique_id == f"test_entry_{subentry.subentry_id}"
    assert migrated_registry_entry.config_subentry_id == subentry.subentry_id

    state = hass.states.get("light.kitchen")
    assert state is not None
    assert state.state == STATE_OFF


async def test_migrate_v1_without_controlled_light(hass: HomeAssistant) -> None:
    """Migration only moves what exists; no subentry is invented."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "name": "Kitchen",
            CONF_SWITCHES: ["switch.kitchen_a"],
        },
        entry_id="test_entry",
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.state is ConfigEntryState.LOADED
    assert entry.subentries == {}
    assert hass.states.get("light.kitchen") is None


async def test_migration_is_idempotent(hass: HomeAssistant) -> None:
    """Migrating an already migrated entry leaves it untouched."""
    entry = await _setup_entry(hass)

    options = dict(entry.options)
    subentries = dict(entry.subentries)

    assert await migrate_entry(hass, entry) is True
    await hass.async_block_till_done()

    assert entry.version == 2
    assert dict(entry.options) == options
    assert dict(entry.subentries) == subentries


def _v1_entry(
    entry_id: str,
    name: str,
    switches: list[str],
    control_light: str,
    timer: str | None = None,
) -> MockConfigEntry:
    """Build a version 1 config entry with a single controlled light."""
    options: dict[str, object] = {
        CONF_NAME: name,
        CONF_SWITCHES: switches,
        CONF_CONTROL_LIGHTS: control_light,
    }
    if timer is not None:
        options[CONF_CLOSE_TIMER] = timer
    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options=options,
        entry_id=entry_id,
        title=name,
        version=1,
    )


async def _setup_v1_entries(hass: HomeAssistant, entries: list[MockConfigEntry]) -> None:
    """Add and set up version 1 entries concurrently, like HA startup does."""
    for entry in entries:
        entry.add_to_hass(hass)
    # Setting up the component makes HA set up every entry concurrently via
    # setup.py, which is the situation the merge logic has to survive.
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def test_migrate_merges_entries_with_same_switches_and_timer(
    hass: HomeAssistant,
) -> None:
    """Entries with the same switches and timer are merged into the smallest id."""
    primary_entry = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a", "switch.kitchen_b"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    duplicate_entry = _v1_entry(
        "bbb_entry",
        "Balcony",
        ["switch.kitchen_a", "switch.kitchen_b"],
        "light.living_room_ceiling",
        "timer.kitchen_auto_off",
    )

    await _setup_v1_entries(hass, [primary_entry, duplicate_entry])

    primary = hass.config_entries.async_get_entry("aaa_entry")
    assert primary is not None
    assert primary.version == 2
    assert hass.config_entries.async_get_entry("bbb_entry") is None

    subentries = primary.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
    assert len(subentries) == 2
    assert {subentry.unique_id for subentry in subentries} == {
        "light.kitchen_ceiling",
        "light.living_room_ceiling",
    }
    # The primary entry's name wins.
    assert primary.options[CONF_NAME] == "Kitchen"
    assert CONF_CONTROL_LIGHTS not in primary.options

    registry = er.async_get(hass)
    entities = list(registry.entities.get_entries_for_config_entry_id("aaa_entry"))
    assert len(entities) == 2
    assert {entity.config_entry_id for entity in entities} == {"aaa_entry"}
    for entity in entities:
        assert entity.config_subentry_id in set(primary.subentries)
        device = dr.async_get(hass).async_get(entity.device_id or "")
        assert device is not None
        assert device.config_subentry_id == entity.config_subentry_id

    # The duplicate entry and all of its registry entries are gone.
    assert not list(registry.entities.get_entries_for_config_entry_id("bbb_entry"))
    assert not dr.async_entries_for_config_entry(dr.async_get(hass), "bbb_entry")

    # Both lights are live and virtual ids follow their controlled lights.
    assert hass.states.get("light.kitchen_ceiling_2") is not None
    assert hass.states.get("light.living_room_ceiling_2") is not None
    assert primary.state is ConfigEntryState.LOADED


async def test_migrate_keeps_entries_with_different_timers(
    hass: HomeAssistant,
) -> None:
    """The same switches with different timers are different switch groups."""
    first = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a", "switch.kitchen_b"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    second = _v1_entry(
        "bbb_entry",
        "Kitchen",
        ["switch.kitchen_a", "switch.kitchen_b"],
        "light.living_room_ceiling",
        None,
    )

    await _setup_v1_entries(hass, [first, second])

    for entry_id in ("aaa_entry", "bbb_entry"):
        entry = hass.config_entries.async_get_entry(entry_id)
        assert entry is not None
        assert entry.version == 2
        assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)) == 1


async def test_migrate_keeps_entries_with_different_switches(
    hass: HomeAssistant,
) -> None:
    """Different switch sets mean different switch groups."""
    first = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    second = _v1_entry(
        "bbb_entry",
        "Kitchen",
        ["switch.kitchen_a", "switch.kitchen_b"],
        "light.living_room_ceiling",
        "timer.kitchen_auto_off",
    )

    await _setup_v1_entries(hass, [first, second])

    assert hass.config_entries.async_get_entry("aaa_entry") is not None
    assert hass.config_entries.async_get_entry("bbb_entry") is not None
    assert hass.config_entries.async_get_entry("aaa_entry").subentries != {}
    assert hass.config_entries.async_get_entry("bbb_entry").subentries != {}


async def test_migrate_merges_entries_when_switches_order_differs(
    hass: HomeAssistant,
) -> None:
    """Switch order is irrelevant; the switch sets are compared."""
    first = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a", "switch.kitchen_b"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    second = _v1_entry(
        "bbb_entry",
        "Kitchen",
        ["switch.kitchen_b", "switch.kitchen_a"],
        "light.living_room_ceiling",
        "timer.kitchen_auto_off",
    )

    await _setup_v1_entries(hass, [first, second])

    primary = hass.config_entries.async_get_entry("aaa_entry")
    assert primary is not None
    assert hass.config_entries.async_get_entry("bbb_entry") is None
    assert {s.unique_id for s in primary.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)} == {
        "light.kitchen_ceiling",
        "light.living_room_ceiling",
    }


async def test_migrate_merge_keeps_primary_name(hass: HomeAssistant) -> None:
    """Entries with different names merge; the primary entry's name is kept."""
    first = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    second = _v1_entry(
        "bbb_entry",
        "Living Room Group",
        ["switch.kitchen_a"],
        "light.living_room_ceiling",
        "timer.kitchen_auto_off",
    )

    await _setup_v1_entries(hass, [second, first])

    primary = hass.config_entries.async_get_entry("aaa_entry")
    assert primary is not None
    assert primary.title == "Kitchen"
    assert primary.options[CONF_NAME] == "Kitchen"
    assert hass.config_entries.async_get_entry("bbb_entry") is None
    assert len(primary.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)) == 2


async def test_migrate_merge_skips_duplicate_controlled_light(
    hass: HomeAssistant,
) -> None:
    """Two entries controlling the same light merge without duplicate unique ids."""
    first = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    second = _v1_entry(
        "bbb_entry",
        "Kitchen again",
        ["switch.kitchen_a"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )

    await _setup_v1_entries(hass, [first, second])

    primary = hass.config_entries.async_get_entry("aaa_entry")
    assert primary is not None
    assert primary.version == 2
    assert hass.config_entries.async_get_entry("bbb_entry") is None
    subentries = primary.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
    assert len(subentries) == 1
    assert subentries[0].unique_id == "light.kitchen_ceiling"
    entities = list(er.async_get(hass).entities.get_entries_for_config_entry_id("aaa_entry"))
    assert len(entities) == 1
    assert entities[0].entity_id == "light.kitchen_ceiling_2"


async def test_migrate_merge_is_idempotent(hass: HomeAssistant) -> None:
    """Running the migration again does not change an already merged entry."""
    first = _v1_entry(
        "aaa_entry",
        "Kitchen",
        ["switch.kitchen_a"],
        "light.kitchen_ceiling",
        "timer.kitchen_auto_off",
    )
    second = _v1_entry(
        "bbb_entry",
        "Balcony",
        ["switch.kitchen_a"],
        "light.living_room_ceiling",
        "timer.kitchen_auto_off",
    )

    await _setup_v1_entries(hass, [first, second])

    primary = hass.config_entries.async_get_entry("aaa_entry")
    assert primary is not None
    subentries = {sid: sub.as_dict() for sid, sub in primary.subentries.items()}
    devices_before = {
        device.id
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), primary.entry_id)
    }

    assert await migrate_entry(hass, primary) is True
    await hass.async_block_till_done()
    assert primary.version == 2
    assert {sid: sub.as_dict() for sid, sub in primary.subentries.items()} == subentries
    assert {
        device.id
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), primary.entry_id)
    } == devices_before

    assert await hass.config_entries.async_reload(primary.entry_id)
    await hass.async_block_till_done()
    assert {sid: sub.as_dict() for sid, sub in primary.subentries.items()} == subentries


async def test_legacy_empty_shared_device_is_removed(hass: HomeAssistant) -> None:
    """The empty shared device from older versions is removed on setup."""
    entry = await _setup_entry(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    # The device an older version created for the whole config entry.
    legacy_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Kitchen",
    )
    current_entity = ent_reg.async_get("light.kitchen_ceiling_2")
    assert current_entity is not None
    current_device_id = current_entity.device_id
    assert current_device_id is not None
    assert current_device_id != legacy_device.id

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert dev_reg.async_get(legacy_device.id) is None
    # The new per-subentry device is not touched.
    current_entity = ent_reg.async_get("light.kitchen_ceiling_2")
    assert current_entity is not None
    assert current_entity.device_id == current_device_id
    new_device = dev_reg.async_get(current_device_id)
    assert new_device is not None
    assert new_device.config_subentry_id == current_entity.config_subentry_id

    # The cleanup is idempotent.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert dev_reg.async_get(legacy_device.id) is None
    assert dev_reg.async_get(current_device_id) is not None


async def test_legacy_shared_device_with_entity_is_kept(hass: HomeAssistant) -> None:
    """A legacy device that still has an entity is never removed."""
    entry = await _setup_entry(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    legacy_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Kitchen",
    )
    legacy_entity = ent_reg.async_get_or_create(
        domain="light",
        platform="test",
        unique_id="legacy_entity",
        config_entry=entry,
        device_id=legacy_device.id,
    )

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert dev_reg.async_get(legacy_device.id) is not None
    assert ent_reg.async_get(legacy_entity.entity_id) is not None
    assert ent_reg.async_get(legacy_entity.entity_id).device_id == legacy_device.id


async def test_remove_entry_clears_subentries_and_registries(
    hass: HomeAssistant,
) -> None:
    """Removing a config entry clears its subentries and registry entries."""
    entry = await _setup_entry(
        hass,
        subentries=[
            _light_subentry("light.kitchen_ceiling", "Kitchen"),
            _light_subentry("light.living_room_ceiling", "Living Room"),
        ],
    )
    subentry_ids = set(entry.subentries)
    assert len(subentry_ids) == 2

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    entity_ids = ["light.kitchen_ceiling_2", "light.living_room_ceiling_2"]
    device_ids: list[str] = []
    for entity_id in entity_ids:
        registry_entry = ent_reg.async_get(entity_id)
        assert registry_entry is not None
        assert registry_entry.device_id is not None
        device_ids.append(registry_entry.device_id)
    assert dev_reg.async_get(device_ids[0]) is not None
    assert dev_reg.async_get(device_ids[1]) is not None

    result = await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert result == {"require_restart": False}
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert entry.subentries == {}
    assert entry.state is ConfigEntryState.NOT_LOADED

    for entity_id in entity_ids:
        assert ent_reg.async_get(entity_id) is None
    for device_id in device_ids:
        assert dev_reg.async_get(device_id) is None
