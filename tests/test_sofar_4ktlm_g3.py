"""Regression coverage using the real parser and synthetic register samples.

Run: python -m unittest discover -s tests -v
Requires aiohttp, aiofiles, voluptuous and PyYAML. Only the Home Assistant
slug/device metadata imports are shimmed; decoding and scheduling are real.
SOLARMAN_TEST_COMPONENT may point to an extracted stable release.
"""
import asyncio
import importlib
import os
from pathlib import Path
import re
import sys
import types
import unittest

COMPONENT = Path(os.environ.get('SOLARMAN_TEST_COMPONENT', Path(__file__).resolve().parents[1] / 'custom_components/solarman'))
PROFILE = 'sofar_4ktlm-g3.yaml'

# Do not execute the integration's __init__, which requires a running HA instance.
package = types.ModuleType('_solarman_profile_test')
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package
if importlib.util.find_spec('homeassistant') is None:
    for name in ('homeassistant', 'homeassistant.util', 'homeassistant.helpers', 'homeassistant.helpers.device_registry'):
        sys.modules[name] = types.ModuleType(name)
    sys.modules['homeassistant.util'].slugify = lambda value, separator='_': re.sub(r'[^a-z0-9]+', separator, value.lower()).strip(separator)
    device = sys.modules['homeassistant.helpers.device_registry']
    device.CONNECTION_NETWORK_MAC = 'mac'
    device.DeviceInfo = dict
    device.format_mac = lambda value: value
Parser = importlib.import_module(package.__name__ + '.parser').ParameterParser


class SofarProfileTest(unittest.TestCase):
    def parser(self):
        return asyncio.run(Parser().init(str(COMPONENT / 'inverter_definitions') + '/', PROFILE, {'mod':0, 'mppt':2, 'l':1, 'pack':-1}))

    def decode(self, registers):
        parser = self.parser()
        requests = parser.schedule_requests(0)
        data = {(3,r['start']):[registers.get(a,0) for a in range(r['start'],r['end']+1)] for r in requests}
        return parser.process(data)

    def test_complete_aligned_blocks_on_every_cycle(self):
        parser = self.parser()
        for runtime in (0,5,30,60):
            self.assertEqual([(r['code'],r['start'],r['end'],r['count']) for r in parser.schedule_requests(runtime)], [(3,0x400,0x42e,47),(3,0x480,0x4af,48),(3,0x580,0x589,10),(3,0x680,0x69b,28)])

    def test_power_voltage_and_energy_word_order(self):
        result = self.decode({0x404:2,0x484:6000,0x485:97,0x48d:2200,0x48e:441,0x584:2600,0x585:200,0x586:52,0x589:51,0x684:0,0x685:321,0x686:1,0x687:0x2345})
        for key, expected in {'pv1_power_sensor':520,'pv2_power_sensor':510,'pv1_voltage_sensor':260,'pv1_current_sensor':2,'output_active_power_sensor':970,'l1_voltage_sensor':220,'l1_current_sensor':4.41,'grid_frequency_sensor':60,'daily_production_sensor':3.21,'total_production_sensor':0x12345*.1}.items():
            self.assertAlmostEqual(result[key][0],expected,msg=key)

    def test_g3_status_and_raw_faults(self):
        result = self.decode({0x404:4,0x405:3,0x410:0x8000})
        self.assertEqual(result['inverter_status_sensor'][0], 'Recoverable Fault')
        self.assertEqual(result['fault_1_sensor'][0], 3)
        self.assertEqual(result['fault_2_sensor'][0], 0)
        self.assertEqual(result['fault_12_sensor'][0], 0x8000)

    def test_two_mppt_single_phase_without_write_controls(self):
        items = self.parser().get_entity_descriptions('sensor')
        names = [i['name'] for i in items]
        self.assertEqual(len(names),len(set(names)))
        for name in ('L2 Voltage','L3 Voltage','Battery','Inverter module temperature'):
            self.assertNotIn(name,names)
        self.assertIn('Inverter radiator temperature', names)
        self.assertFalse(any('write' in i.get('code',{}) for i in items if isinstance(i.get('code'),dict)))
        self.assertEqual(self.parser().get_entity_descriptions('number'), [])


if __name__ == '__main__':
    unittest.main()
