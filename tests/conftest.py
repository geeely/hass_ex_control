import pathlib

import custom_components
import pytest

# The plugin ships its own custom_components package and imports it first;
# put ours in front of it.
_ours = str(pathlib.Path(__file__).parent.parent / "custom_components")
custom_components.__path__ = [_ours] + [p for p in custom_components.__path__ if p != _ours]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
