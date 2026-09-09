"""Config flow for Switch Controlled Light."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import (
    light as light_domain,
)
from homeassistant.components import (
    switch as switch_domain,
)
from homeassistant.components import (
    timer as timer_domain,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowFormStep,
)

from .const import CONF_CLOSE_TIMER, CONF_CONTROL_LIGHTS, CONF_SWITCHES, DOMAIN

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_SWITCHES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=switch_domain.DOMAIN,
                multiple=True,
            )
        ),
        vol.Required(CONF_CONTROL_LIGHTS): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=light_domain.DOMAIN)
        ),
        vol.Optional(CONF_CLOSE_TIMER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=timer_domain.DOMAIN)
        ),
    }
)

# The options form omits the name (which becomes the entry title and is set
# during creation); switches, controlled light and timer can all be re-picked.
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SWITCHES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=switch_domain.DOMAIN,
                multiple=True,
            )
        ),
        vol.Required(CONF_CONTROL_LIGHTS): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=light_domain.DOMAIN)
        ),
        vol.Optional(CONF_CLOSE_TIMER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=timer_domain.DOMAIN)
        ),
    }
)

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(schema=USER_SCHEMA),
}
OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(schema=OPTIONS_SCHEMA),
}


class SwitchControlledLightConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config flow for Switch Controlled Light."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    # Reload the entry automatically when options are saved so listeners and
    # the virtual light are rebuilt from the new options.
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return options[CONF_NAME]

    def async_config_flow_finished(self, options: Mapping[str, Any]) -> None:
        """Abort if the same instance already exists."""
        self._async_abort_entries_match(dict(options))
