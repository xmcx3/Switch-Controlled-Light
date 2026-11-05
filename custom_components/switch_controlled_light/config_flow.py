"""Config flow for Switch Controlled Light."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.components import (
    light as light_domain,
)
from homeassistant.components import (
    switch as switch_domain,
)
from homeassistant.components import (
    timer as timer_domain,
)
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    FlowType,
    SubentryFlowContext,
    SubentryFlowResult,
    UnknownSubEntry,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)

from .const import (
    CONF_CLOSE_TIMER,
    CONF_CONFIRM_DELETE,
    CONF_CONTROL_LIGHTS,
    CONF_DELETE_LIGHT,
    CONF_SWITCHES,
    DOMAIN,
    SUBENTRY_TYPE_LIGHT,
)

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): selector.TextSelector(),
        probatio.Required(CONF_SWITCHES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=switch_domain.DOMAIN,
                multiple=True,
            )
        ),
        probatio.Optional(CONF_CLOSE_TIMER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=timer_domain.DOMAIN)
        ),
    }
)

# The options form omits the name (which becomes the entry title and is set
# during creation); switches and timer can both be re-picked. Controlled lights
# are managed as subentries instead.
OPTIONS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_SWITCHES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=switch_domain.DOMAIN,
                multiple=True,
            )
        ),
        probatio.Optional(CONF_CLOSE_TIMER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=timer_domain.DOMAIN)
        ),
    }
)

SUBENTRY_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): selector.TextSelector(),
        probatio.Required(CONF_CONTROL_LIGHTS): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=light_domain.DOMAIN)
        ),
    }
)

CONFIRM_DELETE_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_CONFIRM_DELETE, default=False): selector.BooleanSelector(),
    }
)


async def _async_options_schema(handler: SchemaCommonFlowHandler) -> probatio.Schema:
    """Build the options schema, listing the lights that can be deleted."""
    parent = handler.parent_handler
    if not isinstance(parent, SchemaOptionsFlowHandler):
        return OPTIONS_SCHEMA

    fields: dict[Any, Any] = dict(OPTIONS_SCHEMA.schema)
    subentries = parent.config_entry.get_subentries_of_type(SUBENTRY_TYPE_LIGHT)
    if subentries:
        fields[probatio.Optional(CONF_DELETE_LIGHT)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(value=subentry.subentry_id, label=subentry.title)
                    for subentry in subentries
                ],
                mode=selector.SelectSelectorMode.LIST,
            )
        )
    return probatio.Schema(fields)


async def _async_options_next_step(options: dict[str, Any]) -> str | None:
    """Continue to the confirmation step when a light was selected."""
    if options.get(CONF_DELETE_LIGHT):
        return "delete_light"
    return None


async def _async_delete_light_placeholders(
    handler: SchemaCommonFlowHandler,
) -> dict[str, str]:
    """Return the title of the light selected for deletion."""
    parent = handler.parent_handler
    if not isinstance(parent, SchemaOptionsFlowHandler):
        return {"name": ""}
    subentry = parent.config_entry.subentries.get(str(handler.options.get(CONF_DELETE_LIGHT, "")))
    return {"name": subentry.title if subentry else ""}


async def _async_confirm_delete_light(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Delete the selected controlled light after confirmation."""
    if not user_input.get(CONF_CONFIRM_DELETE):
        raise SchemaFlowError("delete_not_confirmed")

    parent = handler.parent_handler
    if not isinstance(parent, SchemaOptionsFlowHandler):
        raise SchemaFlowError("light_not_found")

    entry = parent.config_entry
    subentry_id = handler.options.get(CONF_DELETE_LIGHT)
    if not isinstance(subentry_id, str) or subentry_id not in entry.subentries:
        raise SchemaFlowError("light_not_found")

    handler.options.pop(CONF_DELETE_LIGHT, None)
    parent.hass.config_entries.async_remove_subentry(entry, subentry_id)
    return {}


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(schema=USER_SCHEMA),
}
OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        schema=_async_options_schema,
        next_step=_async_options_next_step,
    ),
    "delete_light": SchemaFlowFormStep(
        schema=CONFIRM_DELETE_SCHEMA,
        validate_user_input=_async_confirm_delete_light,
        description_placeholders=_async_delete_light_placeholders,
    ),
}


class SwitchControlledLightConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config flow for Switch Controlled Light."""

    VERSION = 2
    MINOR_VERSION = 1

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {SUBENTRY_TYPE_LIGHT: LightSubentryFlowHandler}

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return options[CONF_NAME]

    def async_config_flow_finished(self, options: Mapping[str, Any]) -> None:
        """Abort if the same instance already exists."""
        self._async_abort_entries_match(dict(options))

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Continue with the subentry flow to add the first light."""
        subentry_result = await self.hass.config_entries.subentries.async_init(
            (result["result"].entry_id, SUBENTRY_TYPE_LIGHT),
            context=SubentryFlowContext(source=SOURCE_USER),
        )
        result["next_flow"] = (
            FlowType.CONFIG_SUBENTRIES_FLOW,
            subentry_result["flow_id"],
        )
        return result


class LightSubentryFlowHandler(ConfigSubentryFlow):
    """Handle adding, reconfiguring or deleting a single controlled light."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle adding a new controlled light."""
        return await self._async_step(user_input, reconfigure=False)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle editing an existing controlled light."""
        return await self._async_step(user_input, reconfigure=True)

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Delete the controlled light of the current subentry.

        HA Core does not provide a delete hook on ``ConfigSubentryFlow`` (the
        standard deletion is the ``config_entries/subentries/delete``
        websocket command). Implementing the step here still allows the flow
        to be started with a ``delete`` source and a ``subentry_id`` context.
        """
        entry = self._get_entry()
        subentry = self._get_selected_subentry(entry)

        if user_input is not None:
            self.hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
            return self.async_abort(reason="delete_successful")

        return self.async_show_form(
            step_id="delete",
            description_placeholders={"name": subentry.title},
        )

    def _get_selected_subentry(self, entry: ConfigEntry) -> ConfigSubentry:
        """Return the subentry referenced by the flow context."""
        subentry_id = self.context.get("subentry_id")
        if not subentry_id or subentry_id not in entry.subentries:
            raise UnknownSubEntry(subentry_id)
        return entry.subentries[subentry_id]

    async def _async_step(
        self,
        user_input: dict[str, Any] | None,
        *,
        reconfigure: bool,
    ) -> SubentryFlowResult:
        """Show the form or process its submission."""
        entry = self._get_entry()
        subentry: ConfigSubentry | None = self._get_reconfigure_subentry() if reconfigure else None

        if user_input is not None:
            control_light: str = user_input[CONF_CONTROL_LIGHTS]
            title: str = str(user_input.get(CONF_NAME) or "").strip() or control_light
            data = {CONF_CONTROL_LIGHTS: control_light}
            if subentry is not None:
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    title=title,
                    data=data,
                    # Reusing the controlled light as unique_id lets HA reject
                    # adding the same light twice to the same entry.
                    unique_id=control_light,
                )
            return self.async_create_entry(
                title=title,
                data=data,
                unique_id=control_light,
            )

        suggested_values: dict[str, Any] = {}
        if subentry is not None:
            suggested_values = {
                CONF_NAME: subentry.title,
                CONF_CONTROL_LIGHTS: subentry.data.get(CONF_CONTROL_LIGHTS),
            }

        return self.async_show_form(
            step_id="reconfigure" if reconfigure else "user",
            data_schema=self.add_suggested_values_to_schema(
                SUBENTRY_SCHEMA, suggested_values or None
            ),
            description_placeholders={"name": entry.title},
        )
