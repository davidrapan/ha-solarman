"""Device registry lookups of the config flow, the services and the device removal."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solarman import async_remove_config_entry_device
from custom_components.solarman.common import find_device, get_device_config_entry_id
from custom_components.solarman.const import CONF_HOST, DOMAIN, IP_ANY, SERVICES_PARAM_DEVICE
from custom_components.solarman.coordinator import Coordinator
from custom_components.solarman.services import _get_device

MAC = "e8:fd:f8:aa:bb:cc"
SERIAL = "2712345678"


def add_entry(hass: HomeAssistant, host: str = "192.168.1.10", *, mac: str | None = MAC, identifiers: bool = True):
    """Add a config entry and its device to the registries."""
    entry = MockConfigEntry(domain = DOMAIN, version = 2, minor_version = 0, title = host, options = {CONF_HOST: host})
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id = entry.entry_id,
        connections = {(dr.CONNECTION_NETWORK_MAC, mac)} if mac else set(),
        identifiers = {(DOMAIN, entry.entry_id), (DOMAIN, SERIAL)} if identifiers else set(),
    )
    return entry, device


def dhcp(ip: str, mac: str = MAC) -> DhcpServiceInfo:
    return DhcpServiceInfo(ip = ip, hostname = "logger", macaddress = mac.replace(":", ""))


async def discover(hass: HomeAssistant, ip: str, mac: str = MAC):
    return await hass.config_entries.flow.async_init(DOMAIN, context = {"source": SOURCE_DHCP}, data = dhcp(ip, mac))


def assert_no_deprecation_warnings(caplog: pytest.LogCaptureFixture):
    assert "deprecated" not in caplog.text


async def test_dhcp_updates_the_host_of_the_entry_that_owns_the_mac(hass: HomeAssistant, caplog):
    entry, _ = add_entry(hass)

    result = await discover(hass, "192.168.1.55")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured_device"
    assert entry.options[CONF_HOST] == "192.168.1.55"
    assert_no_deprecation_warnings(caplog)


async def test_dhcp_keeps_the_host_when_it_did_not_change(hass: HomeAssistant, caplog):
    entry, _ = add_entry(hass)

    result = await discover(hass, "192.168.1.10")

    assert result["reason"] == "already_configured_device"
    assert entry.options[CONF_HOST] == "192.168.1.10"
    assert_no_deprecation_warnings(caplog)


async def test_integration_discovery_without_an_address_keeps_the_host(hass: HomeAssistant):
    entry, _ = add_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context = {"source": SOURCE_INTEGRATION_DISCOVERY},
        data = {"ip": IP_ANY, "mac": MAC, "serial": SERIAL},
    )

    assert result["reason"] == "already_configured_device"
    assert entry.options[CONF_HOST] == "192.168.1.10"


async def test_dhcp_only_updates_the_entry_that_owns_the_device(hass: HomeAssistant):
    other, _ = add_entry(hass, "192.168.1.20", mac = "e8:fd:f8:11:22:33", identifiers = False)
    entry, _ = add_entry(hass)

    result = await discover(hass, "192.168.1.55")

    assert result["reason"] == "already_configured_device"
    assert entry.options[CONF_HOST] == "192.168.1.55"
    assert other.options[CONF_HOST] == "192.168.1.20"


async def test_dhcp_matches_the_host_and_remembers_the_mac(hass: HomeAssistant, caplog):
    entry, device = add_entry(hass, mac = None)
    assert not device.connections

    result = await discover(hass, "192.168.1.10")

    assert result["reason"] == "already_configured_device"
    assert dr.async_get(hass).async_get(device.id).connections == {(dr.CONNECTION_NETWORK_MAC, MAC)}
    assert_no_deprecation_warnings(caplog)


async def test_dhcp_of_an_unknown_logger_starts_the_setup(hass: HomeAssistant):
    add_entry(hass)

    result = await discover(hass, "192.168.1.77", "e8:fd:f8:00:00:01")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


def test_find_device_is_limited_to_one_config_entry(hass: HomeAssistant):
    first, device = add_entry(hass)
    registry = dr.async_get(hass)
    second = MockConfigEntry(domain = DOMAIN)
    second.add_to_hass(hass)

    connection = (dr.CONNECTION_NETWORK_MAC, MAC)
    assert find_device(registry, first.entry_id, connection = connection) == device
    assert find_device(registry, first.entry_id, identifier = (DOMAIN, first.entry_id)) == device
    assert find_device(registry, second.entry_id, connection = connection) is None
    assert find_device(registry, second.entry_id, identifier = (DOMAIN, first.entry_id)) is None


def test_the_config_entry_of_a_device_is_found(hass: HomeAssistant, caplog):
    entry, device = add_entry(hass)

    assert get_device_config_entry_id(device) == entry.entry_id
    assert_no_deprecation_warnings(caplog)


def test_older_home_assistant_versions_use_the_previous_lookups():
    device = SimpleNamespace(config_entries = {"a"}, primary_config_entry = "a")
    calls = []

    class OldRegistry:
        def async_get_device(self, connections = None, identifiers = None):
            calls.append((connections, identifiers))
            return device

    connection = (dr.CONNECTION_NETWORK_MAC, MAC)
    assert find_device(OldRegistry(), "a", connection = connection) is device
    assert find_device(OldRegistry(), "a", identifier = (DOMAIN, "a")) is device
    assert find_device(OldRegistry(), "b", connection = connection) is None
    assert calls == [({connection}, None), (None, {(DOMAIN, "a")}), ({connection}, None)]
    assert get_device_config_entry_id(device) == "a"


async def test_a_device_can_be_removed_unless_it_belongs_to_the_entry(hass: HomeAssistant, caplog):
    entry, device = add_entry(hass)
    _, stray_device = add_entry(hass, "192.168.1.30", mac = "e8:fd:f8:44:55:66", identifiers = False)
    entry.runtime_data = MagicMock(device = MagicMock(modbus = MagicMock(serial = SERIAL)))

    assert await async_remove_config_entry_device(hass, entry, device) is False
    assert await async_remove_config_entry_device(hass, entry, stray_device) is True
    assert_no_deprecation_warnings(caplog)


def test_a_service_call_reaches_the_device_of_its_config_entry(hass: HomeAssistant, caplog):
    entry, device = add_entry(hass)
    entry.runtime_data = MagicMock(spec = Coordinator)
    entry.runtime_data.device = MagicMock()
    call = MagicMock(hass = hass, data = {SERVICES_PARAM_DEVICE: device.id})

    assert _get_device(call) is entry.runtime_data.device
    assert_no_deprecation_warnings(caplog)


def test_a_service_call_for_another_domain_is_rejected(hass: HomeAssistant):
    other = MockConfigEntry(domain = "other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id = other.entry_id, identifiers = {("other", "1")})
    call = MagicMock(hass = hass, data = {SERVICES_PARAM_DEVICE: device.id})

    with pytest.raises(ServiceValidationError):
        _get_device(call)
