"""Read services must preserve address zero without contacting a real device."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from custom_components.solarman import services
from custom_components.solarman.pysolarman.umodbus.functions import FUNCTION_CODE


class ReadServicesTest(unittest.IsolatedAsyncioTestCase):
    async def test_holding_register_zero(self):
        await self.check_read(services._read_holding_registers, FUNCTION_CODE.READ_HOLDING_REGISTERS, {"address": 0}, 0)

    async def test_input_register_zero(self):
        await self.check_read(services._read_input_registers, FUNCTION_CODE.READ_INPUT_REGISTERS, {"address": 0}, 0)

    async def test_explicit_zero_takes_precedence_over_legacy_register(self):
        await self.check_read(services._read_holding_registers, FUNCTION_CODE.READ_HOLDING_REGISTERS, {"address": 0, "register": 99}, 0)

    async def test_nonzero_address(self):
        await self.check_read(services._read_holding_registers, FUNCTION_CODE.READ_HOLDING_REGISTERS, {"address": 53}, 53)

    async def test_legacy_register_fallback(self):
        await self.check_read(services._read_holding_registers, FUNCTION_CODE.READ_HOLDING_REGISTERS, {"register": 0}, 0)

    async def check_read(self, handler, code, address_fields, expected_address):
        device = SimpleNamespace(execute=AsyncMock(return_value=[3, 0]))
        call = SimpleNamespace(data={"count": 2} | address_fields)
        with patch.object(services, "_get_device", return_value=device):
            result = await handler(call)
        self.assertEqual(result, {expected_address: 3, expected_address + 1: 0})
        device.execute.assert_awaited_once_with(code, expected_address, count=2)


if __name__ == "__main__":
    unittest.main()
