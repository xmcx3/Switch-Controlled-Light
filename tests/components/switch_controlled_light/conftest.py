"""Define fixtures for Switch Controlled Light tests.

The `enable_custom_integrations` fixture is only required when the
integration lives under ``custom_components/``. When this same test
module is loaded by Home Assistant core (via a symlink in
``homeassistant/components/``), that fixture is unavailable, so we
make the wrapper fixture conditional.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

try:
    from pytest_homeassistant_custom_component.plugins import (  # noqa: F401
        enable_custom_integrations,
    )

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(
        enable_custom_integrations: None,  # noqa: F811
    ) -> Generator[None]:
        """Enable custom integrations defined in the test tree."""
        yield
except ImportError:
    # Running under Home Assistant core; no custom integration setup needed.
    pass