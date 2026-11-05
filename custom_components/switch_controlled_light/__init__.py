"""The Switch Controlled Light integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from homeassistant.components import switch as switch_domain
from homeassistant.components import timer
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_ENTITY_ID, CONF_NAME, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CLOSE_TIMER,
    CONF_CONTROL_LIGHTS,
    CONF_SWITCHES,
    DOMAIN,
    PLATFORMS,
    SUBENTRY_TYPE_LIGHT,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SharedConfig:
    """Configuration shared by every light of a config entry."""

    name: str
    switch_entity_ids: list[str]
    timer_entity_id: str | None


type SwitchControlledLightConfigEntry = ConfigEntry[SharedConfig]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CONFIG_ENTRY_VERSION = 2
CONFIG_ENTRY_MINOR_VERSION = 1


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Switch Controlled Light integration."""
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: SwitchControlledLightConfigEntry) -> bool:
    """Migrate old config entries to the subentry based layout.

    Version 1 kept ``control_lights`` in ``entry.options``. Version 2 keeps the
    shared configuration (name, switches and timer) in ``entry.options`` and
    moves the controlled light into one ``light`` subentry.

    Entries describing the same switch group (same set of switches and the same
    timer) are merged into one entry. The entry with the smallest ``entry_id``
    is kept as primary; its switches/timer/name win. The other entries' lights
    become subentries of the primary and the duplicate entries are removed
    asynchronously (never while this migration is holding the entry setup lock).
    """
    if entry.version > CONFIG_ENTRY_VERSION:
        _LOGGER.error(
            "Config entry %s has version %s which is newer than the supported version %s",
            entry.entry_id,
            entry.version,
            CONFIG_ENTRY_VERSION,
        )
        return False

    if entry.version == CONFIG_ENTRY_VERSION:
        # Already migrated; never touch a version 2 entry.
        return True

    options = dict(entry.options)
    control_light = options.pop(CONF_CONTROL_LIGHTS, None)

    duplicates = _async_duplicate_entries(hass, entry)
    if duplicates:
        primary = min([entry, *duplicates], key=lambda candidate: candidate.entry_id)
        if primary is not entry:
            # Another entry is the primary. Move this entry's light over and ask
            # for this entry to be removed in the background. The migration must
            # not await another entry's setup lock, see _schedule_entry_removal.
            if _async_merge_lights(hass, entry, primary):
                _LOGGER.info(
                    "Merging config entry %s into %s (same switches and timer)",
                    entry.entry_id,
                    primary.entry_id,
                )
                _schedule_entry_removal(hass, entry.entry_id)
                return True
            _LOGGER.warning(
                "Could not merge config entry %s into %s; migrating it separately",
                entry.entry_id,
                primary.entry_id,
            )
            duplicates = []

    subentry: ConfigSubentry | None = None

    if isinstance(control_light, str) and control_light:
        # Another duplicate's migration may already have added a subentry with
        # this light to us (the non-primary path adds its light before the
        # primary migrates), so look it up by unique id instead of assuming
        # this entry has no subentries yet.
        subentry = next(
            (
                existing
                for existing in entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
                if existing.unique_id == control_light
            ),
            None,
        )
        if subentry is None:
            subentry = ConfigSubentry(
                data=MappingProxyType({CONF_CONTROL_LIGHTS: control_light}),
                subentry_type=SUBENTRY_TYPE_LIGHT,
                title=str(options.get(CONF_NAME) or entry.title),
                unique_id=control_light,
            )
            hass.config_entries.async_add_subentry(entry, subentry)

    if subentry is not None:
        _async_migrate_entity_registry(hass, entry, control_light, subentry)

    merged_duplicates: list[ConfigEntry] = []
    for duplicate in duplicates:
        if _async_merge_lights(hass, duplicate, entry):
            merged_duplicates.append(duplicate)
        else:
            _LOGGER.warning(
                "Could not merge all lights of config entry %s; keeping that entry",
                duplicate.entry_id,
            )

    hass.config_entries.async_update_entry(
        entry,
        version=CONFIG_ENTRY_VERSION,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
        options=options,
    )

    for duplicate in merged_duplicates:
        _schedule_entry_removal(hass, duplicate.entry_id)

    _LOGGER.debug("Migrated config entry %s to version 2", entry.entry_id)
    return True


def _shared_config_key(entry: ConfigEntry) -> tuple[frozenset[str], str | None]:
    """Return the identity used to decide whether entries describe one group.

    Switch order does not matter: the same set of switches is the same switch
    group. The timer has to match exactly (``None`` when not configured).
    """
    switches = entry.options.get(CONF_SWITCHES, [])
    timer = entry.options.get(CONF_CLOSE_TIMER)
    return (
        frozenset(str(switch) for switch in switches),
        timer if isinstance(timer, str) else None,
    )


def _async_duplicate_entries(hass: HomeAssistant, entry: ConfigEntry) -> list[ConfigEntry]:
    """Return other enabled entries describing the same switch group."""
    key = _shared_config_key(entry)
    return [
        other
        for other in hass.config_entries.async_entries(
            DOMAIN, include_ignore=False, include_disabled=False
        )
        if other.entry_id != entry.entry_id
        and other.version <= CONFIG_ENTRY_VERSION
        and _shared_config_key(other) == key
    ]


def _light_configs(entry: ConfigEntry) -> list[tuple[dict[str, Any], str, str | None]]:
    """Return the controlled lights of an entry, before or after migration."""
    if entry.version >= CONFIG_ENTRY_VERSION:
        return [
            (dict(subentry.data), subentry.title, subentry.unique_id)
            for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
        ]

    control_light = entry.options.get(CONF_CONTROL_LIGHTS)
    if not isinstance(control_light, str) or not control_light:
        return []
    return [
        (
            {CONF_CONTROL_LIGHTS: control_light},
            str(entry.options.get(CONF_NAME) or entry.title),
            control_light,
        )
    ]


def _async_merge_lights(hass: HomeAssistant, source: ConfigEntry, target: ConfigEntry) -> bool:
    """Copy the controlled lights of ``source`` to ``target``.

    Returns True when every light is present on ``target`` (either added now or
    already present). A light already present is skipped, which keeps merging
    idempotent and handles two entries controlling the same light without a
    duplicate subentry unique id.
    """
    merged = True
    for data, title, unique_id in _light_configs(source):
        merged = _async_add_merged_light(hass, target, data, title, unique_id) and merged
    return merged


def _async_add_merged_light(
    hass: HomeAssistant,
    target: ConfigEntry,
    data: dict[str, Any],
    title: str,
    unique_id: str | None,
) -> bool:
    """Add a controlled light to ``target`` unless it is already there."""
    if unique_id is not None and any(
        subentry.unique_id == unique_id for subentry in target.subentries.values()
    ):
        _LOGGER.warning(
            "Skipping duplicate controlled light %s while merging into config entry %s",
            unique_id,
            target.entry_id,
        )
        return True

    try:
        hass.config_entries.async_add_subentry(
            target,
            ConfigSubentry(
                data=MappingProxyType(dict(data)),
                subentry_type=SUBENTRY_TYPE_LIGHT,
                title=title,
                unique_id=unique_id,
            ),
        )
    except AbortFlow:
        # Another concurrent migration added the same unique id first.
        _LOGGER.warning(
            "Skipping already merged controlled light %s for config entry %s",
            unique_id,
            target.entry_id,
        )
        return True
    except Exception:
        _LOGGER.warning(
            "Could not merge controlled light %s into config entry %s",
            unique_id,
            target.entry_id,
            exc_info=True,
        )
        return False
    return True


def _schedule_entry_removal(hass: HomeAssistant, entry_id: str) -> None:
    """Remove a duplicate entry after the current setup finishes.

    ``ConfigEntries.async_remove`` takes the target entry's ``setup_lock``.
    Migrations run while holding their own entry's ``setup_lock`` and entries
    are set up concurrently, so awaiting the removal here could deadlock if two
    entries tried to remove each other. The removal therefore runs as a
    non-eager background task: the migration never waits for another entry's
    lock, and only the deterministic primary (or a non-primary removing itself)
    schedules removals.

    Removing an entry that is already gone (two migrations racing) is harmless.
    """

    async def _async_remove_entry() -> None:
        try:
            await hass.config_entries.async_remove(entry_id)
        except HomeAssistantError as err:
            _LOGGER.debug(
                "Config entry %s was already removed or could not be removed: %s",
                entry_id,
                err,
            )

    hass.async_create_task(
        _async_remove_entry(),
        f"{DOMAIN} merge removal {entry_id}",
        eager_start=False,
    )


def _async_migrate_entity_registry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    control_light: str,
    subentry: ConfigSubentry,
) -> None:
    """Re-key the old virtual light registry entry to the new unique id."""
    registry = entity_registry.async_get(hass)
    old_unique_id = f"{entry.entry_id}_{control_light}"
    entity_id = registry.async_get_entity_id(Platform.LIGHT, DOMAIN, old_unique_id)
    if entity_id is None:
        return
    registry.async_update_entity(
        entity_id,
        new_unique_id=f"{entry.entry_id}_{subentry.subentry_id}",
        config_subentry_id=subentry.subentry_id,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Switch Controlled Light from a config entry."""
    options = entry.options
    name: str = str(options.get(CONF_NAME) or entry.title)
    timer_entity_id: str | None = options.get(CONF_CLOSE_TIMER)
    switch_entity_ids: list[str] = list(options.get(CONF_SWITCHES, []))

    entry.runtime_data = SharedConfig(
        name=name,
        switch_entity_ids=switch_entity_ids,
        timer_entity_id=timer_entity_id,
    )

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
        entry.async_on_unload(hass.bus.async_listen(timer.EVENT_TIMER_FINISHED, auto_close_switch))

    # Subentries and options are edited through flows which update the entry
    # directly, so reload on any entry update to (re)build entities.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_remove_legacy_shared_device(hass, entry)
    return True


@callback
def _async_remove_legacy_shared_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the empty shared device left behind by older versions.

    Older versions attached every light to one device identified by
    ``(DOMAIN, entry_id)``. The per-light device model uses the subentry id as
    identifier instead, so the old device stays behind as an empty shell.

    The device is removed only if all of the following hold, so a device still
    in use can never be deleted:
    - its identifiers are exactly ``{(DOMAIN, entry_id)}`` (legacy format),
    - it is not attached to a config subentry,
    - no enabled or disabled entity is attached to it,
    - it has no child devices.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = entity_registry.async_get(hass)
    legacy_identifiers = {(DOMAIN, entry.entry_id)}

    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        if device.identifiers != legacy_identifiers:
            continue
        if device.config_subentry_id is not None:
            continue
        if entity_registry.async_entries_for_device(
            ent_reg, device.id, include_disabled_entities=True
        ):
            continue
        if dr.async_entries_for_parent_device(dev_reg, device.id):
            continue
        try:
            dev_reg.async_remove_device(device.id)
        except KeyError:
            _LOGGER.warning(
                "Could not remove legacy device %s of config entry %s: device disappeared",
                device.id,
                entry.entry_id,
            )
        else:
            _LOGGER.debug(
                "Removed legacy shared device %s of config entry %s",
                device.id,
                entry.entry_id,
            )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after it was updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear the subentries of a removed config entry.

    ``ConfigEntries._async_remove`` deletes the entry from ``_entries`` before
    calling this hook, so ``async_remove_subentry`` cannot be used here: it
    goes through ``_async_update_entry``, which raises ``UnknownEntry`` once
    the entry is no longer registered. HA exposes no public API to reset the
    subentries of an already removed entry, so the detached in-memory mapping
    is cleared directly. Devices and entities are already cleaned up by
    ``ConfigEntries._async_clean_up`` (and the entry is no longer part of the
    store), so this only prevents a stale ``entry.subentries`` mapping from
    lingering in memory.

    This intentionally is not done in ``async_unload_entry``: unloading also
    happens on every reload (including our own options/subentry reloads), where
    clearing the subentries would destroy the integration's configuration.
    """
    if not entry.subentries:
        return
    try:
        entry.subentries = MappingProxyType({})
    except Exception:
        _LOGGER.warning(
            "Could not clear subentries of removed config entry %s",
            entry.entry_id,
            exc_info=True,
        )
    else:
        _LOGGER.debug("Cleared subentries of removed config entry %s", entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
