"""Lets the pure-Python parts of the integration be tested without a Home Assistant installation"""
import sys
import types
import pathlib

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "solarman"

def _stub(name: str, **attrs):
    module = sys.modules.setdefault(name, types.ModuleType(name))
    for k, v in attrs.items():
        setattr(module, k, v)
    return module

try:
    import homeassistant  # noqa: F401
except ImportError:
    _stub("homeassistant")
    _stub("homeassistant.util", slugify = lambda text, separator = "_": str(text).lower().replace(" ", separator))
    _stub("homeassistant.helpers")
    _stub("homeassistant.helpers.device_registry", CONNECTION_NETWORK_MAC = "mac", DeviceInfo = dict, format_mac = lambda mac: mac)

# Import the component modules as the package "solarman" without running the component's __init__ (which needs Home Assistant)
package = types.ModuleType("solarman")
package.__path__ = [str(COMPONENT)]
sys.modules["solarman"] = package
