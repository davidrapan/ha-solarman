from unittest.mock import patch

import pytest

from custom_components.solarman.common import discover_mac


async def _agen(items):
    for i in items:
        yield i


@pytest.mark.asyncio
async def test_discover_mac_returns_normalised_mac_for_matching_host(hass):
    records = [{"ip": "192.168.1.50", "mac": "E8:FD:F8:AA:BB:CC", "hostname": "1", "serial": 1}]
    with patch("custom_components.solarman.common.discover", return_value=_agen(records)):
        mac = await discover_mac(hass, "192.168.1.50")
    assert mac == "e8:fd:f8:aa:bb:cc"


@pytest.mark.asyncio
async def test_discover_mac_returns_none_when_no_match(hass):
    with patch("custom_components.solarman.common.discover", return_value=_agen([])):
        mac = await discover_mac(hass, "192.168.1.99")
    assert mac is None
