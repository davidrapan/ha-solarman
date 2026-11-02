"""Offline profile regressions: python -B tools/test_deye_profiles.py -v.

Requires PyYAML, not a running Home Assistant or a Modbus connection. Load the
actual parser and its pure helpers without importing integration startup code.
Only HA's ASCII entity-name slugifier and asynchronous local YAML I/O are stubbed.
The number writer is the real production method with an AsyncMock transport.
Public register fixtures below are synthetic.
"""
from __future__ import annotations

import ast
import copy
import re
import unittest
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from unittest.mock import AsyncMock

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "solarman"
PROFILES = COMPONENT / "inverter_definitions"
SPECIFIC = "deye_sg02hp3_30k.yaml"
VOLTAGE_SETTINGS = (
    "Battery Equalization", "Battery Absorption", "Battery Float",
    "Battery Shutdown Voltage", "Battery Restart Voltage", "Battery Low Voltage",
    "SmartLoad Off Voltage", "SmartLoad On Voltage",
)
PURE_HELPERS = {
    "bulk_inherit", "create_request", "all_same", "group_when", "unwrap",
    "slugify", "entity_key", "enforce_parameters", "preprocess_descriptions",
    "get_code", "get_start_addr", "get_addr_value", "get_request_code",
    "strepr", "get_number", "get_or_def", "from_bit_index", "lookup_value",
    "ilen", "concat_hex", "div_mod", "split_p16b",
}


def load_runtime():
    namespace = {"__name__": "offline_deye_tests", "Any": Any, "Iterable": Iterable}
    constants = ast.parse((COMPONENT / "const.py").read_text(encoding="utf-8"))
    constants.body = [
        node for node in constants.body
        if not (isinstance(node, ast.ImportFrom) and node.module == "aiohttp")
        and not (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {"LOGGER_AUTH", "LOGGER_RESTART_DATA"}
            for target in node.targets
        ))
    ]
    exec(compile(constants, "const.py", "exec"), namespace)
    common = ast.parse((COMPONENT / "common.py").read_text(encoding="utf-8"))
    common.body = [
        node for node in common.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        or isinstance(node, ast.FunctionDef) and node.name in PURE_HELPERS
    ]
    namespace["_slugify"] = lambda value, separator="_": re.sub(
        r"[^a-z0-9_]+", separator, value.lower()
    ).strip(separator)
    exec(compile(common, "common.py", "exec"), namespace)

    @lru_cache
    def original_yaml(filename):
        return yaml.safe_load(Path(filename).read_text(encoding="utf-8"))

    async def yaml_open(filename):
        return copy.deepcopy(original_yaml(filename))

    namespace["yaml_open"] = yaml_open
    parser = ast.parse((COMPONENT / "parser.py").read_text(encoding="utf-8"))
    parser.body = [node for node in parser.body if not (
        isinstance(node, ast.ImportFrom) and node.level
    )]
    exec(compile(parser, "parser.py", "exec"), namespace)
    number = ast.parse((COMPONENT / "number.py").read_text(encoding="utf-8"))
    writer = next(
        method for node in number.body
        if isinstance(node, ast.ClassDef) and node.name == "SolarmanNumberEntity"
        for method in node.body
        if isinstance(method, ast.AsyncFunctionDef) and method.name == "async_set_native_value"
    )
    number_imports = [node for node in number.body if isinstance(node, ast.ImportFrom)
                      and node.module in {"__future__", "decimal"}]
    exec(compile(ast.Module(body=number_imports + [writer], type_ignores=[]), "number.py", "exec"), namespace)
    return namespace


RUNTIME = load_runtime()


def complete_inline(coroutine):
    """Our local I/O and AsyncMock complete immediately; no event-loop sockets."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    finally:
        coroutine.close()
    raise AssertionError("Offline fixture unexpectedly suspended")


def load_profile(filename, mod=0, mppt=3, pack=-1):
    parser = RUNTIME["ParameterParser"]()
    return complete_inline(parser.init(
        str(PROFILES) + "/", filename, {"mod": mod, "mppt": mppt, "l": 3, "pack": pack}
    ))


def description(parser, name, platform=None):
    items = [i for i in parser._items if i["name"] == name
             and parser.is_enabled(i) and (platform is None or i["platform"] == platform)]
    if len(items) != 1:
        raise AssertionError(f"Expected one enabled {name!r}/{platform}: {len(items)}")
    return items[0]


def decode(parser, name, words, platform=None):
    item = description(parser, name, platform)
    parser.reset()
    parser.schedule_requests(0)
    data = {(RUNTIME["get_code"](item, "read"), register): [raw]
            for register, raw in zip(item["registers"], words, strict=True)}
    return parser.process(data)[item["key"]][0]


class SharedProfileTests(unittest.TestCase):
    def test_hv_thresholds_below_380_volts(self):
        for mod in (1, 2):
            for name in VOLTAGE_SETTINGS:
                with self.subTest(mod=mod, name=name):
                    parser = load_profile("deye_p3.yaml", mod)
                    self.assertEqual(decode(parser, name, [2000]), 200)

    def test_raw_minimum_matches_displayed_minimum(self):
        for mod in (0, 1, 2):
            parser = load_profile("deye_p3.yaml", mod)
            for name in VOLTAGE_SETTINGS:
                with self.subTest(mod=mod, name=name):
                    item = description(parser, name)
                    self.assertEqual(item["range"]["min"] * item["scale"],
                                     item["configurable"]["min"])

    def test_lv_limits_and_conversion_unchanged(self):
        parser = load_profile("deye_p3.yaml", 0)
        for raw, expected in ((3799, None), (3800, 38), (5000, 50), (6100, 61), (6101, None)):
            with self.subTest(raw=raw):
                self.assertEqual(decode(parser, "Battery Float", [raw]), expected)

    def test_shared_energy_variants_unchanged(self):
        for mod, expected in ((0, 2.7), (1, 2.7), (2, 27)):
            self.assertEqual(decode(load_profile("deye_p3.yaml", mod),
                                    "Today Production", [27]), expected)


class SpecificProfileTests(unittest.TestCase):
    def test_identity_and_keys(self):
        specific = load_profile(SPECIFIC)
        shared = load_profile("deye_p3.yaml", 2)
        self.assertEqual(specific.info["model"], "SUN-30K-SG02HP3-EU-AM3")
        shared_keys = {(i["name"], i["platform"]): i["key"] for i in shared._items}
        for item in specific._items:
            self.assertEqual(item["key"], shared_keys[item["name"], item["platform"]])

    def test_hv_boundaries_independent_of_modifier(self):
        for mod in (0, 1, 2):
            parser = load_profile(SPECIFIC, mod)
            for name in VOLTAGE_SETTINGS:
                item = description(parser, name)
                self.assertEqual(item["scale"], 0.1)
                self.assertEqual(item["configurable"]["step"], 0.1)
                for raw, expected in ((1599, None), (1600, 160), (2000, 200),
                                      (7000, 700), (7001, None)):
                    with self.subTest(mod=mod, name=name, raw=raw):
                        self.assertEqual(decode(parser, name, [raw]), expected)

    def test_optional_voltage_thresholds_keep_zero(self):
        parser = load_profile(SPECIFIC)
        names = ["Battery Generator Charging Start Voltage", "Battery Grid Charging Start Voltage"]
        names += [f"Program {n} Voltage" for n in range(1, 7)]
        for name in names:
            self.assertEqual(decode(parser, name, [0]), 0)
            self.assertEqual(decode(parser, name, [7000]), 700)
            self.assertIsNone(decode(parser, name, [7001]))

    def test_battery_current_limits(self):
        parser = load_profile(SPECIFIC)
        for name in ("Battery Max Charging Current", "Battery Max Discharging Current",
                     "Battery Grid Charging Current", "Battery Generator Charging Current"):
            item = description(parser, name)
            scale = item.get("scale", 1)
            self.assertEqual(item["range"]["max"] * scale, 75)
            self.assertEqual(decode(parser, name, [int(75 / scale)]), 75)
            self.assertIsNone(decode(parser, name, [int(75 / scale) + 1]))

    def test_all_direct_energy_counters(self):
        for mod, scale in ((0, 1), (1, 0.1), (2, 1)):
            parser = load_profile(SPECIFIC, mod)
            counters = [i for i in parser._items if i.get("class") == "energy"
                        and i.get("registers") and i["rule"] in (1, 3)
                        and "sensors" not in i]
            self.assertEqual(len(counters), 14)
            for item in counters:
                with self.subTest(mod=mod, name=item["name"]):
                    words = [27] + [0] * (len(item["registers"]) - 1)
                    self.assertAlmostEqual(decode(parser, item["name"], words), 27 * scale)

    def test_computed_losses_follow_energy_modifier(self):
        daily = {520: 30, 529: 100, 536: 0, 515: 10, 521: 5, 526: 80, 514: 20}
        totals = {522: 30, 523: 0, 534: 100, 535: 0, 537: 0, 538: 0, 518: 10,
                  519: 0, 524: 5, 525: 0, 527: 80, 528: 0, 516: 20, 517: 0}
        for mod, scale in ((0, 1), (1, 0.1), (2, 1)):
            parser = load_profile(SPECIFIC, mod)
            for name, values in (("Today Losses", daily), ("Total Losses", totals)):
                item = description(parser, name)
                self.assertEqual(decode(parser, name, [values[r] for r in item["registers"]]), 35 * scale)

    def test_unsigned_counter_word_order(self):
        parser = load_profile(SPECIFIC)
        self.assertEqual(decode(parser, "Today Production", [65535]), 65535)
        self.assertEqual(decode(parser, "Total Production", [0x2345, 0x0001]), 0x12345)
        self.assertEqual(decode(parser, "Today Production", [0]), 0)

    def test_only_three_mppts_even_with_default_mppt_option(self):
        parser = load_profile(SPECIFIC, mppt=12)
        forbidden = {675, 682, 683, *range(727, 747)}
        for item in parser._items:
            self.assertFalse(set(item.get("registers", [])) & forbidden, item["name"])
            if re.match(r"PV\d+ ", item["name"]):
                self.assertLessEqual(int(re.match(r"PV(\d+)", item["name"])[1]), 3)
        self.assertEqual(description(parser, "PV Power", "sensor")["registers"], [672, 673, 674])

    def test_power_and_other_measurements_unchanged(self):
        parser = load_profile(SPECIFIC)
        self.assertEqual(decode(parser, "PV Power", [100, 200, 300], "sensor"), 6000)
        self.assertEqual(decode(parser, "Battery Power", [65536 - 123]), -1230)
        self.assertEqual(decode(parser, "Battery Voltage", [2100]), 210)
        self.assertEqual(decode(parser, "PV1 Voltage", [4412]), 441.2)
        self.assertEqual(decode(parser, "PV1 Current", [90]), 9)

    def test_profile_needs_no_redirect_or_autodetection(self):
        self.assertNotIn(SPECIFIC, RUNTIME["AUTODETECTION_REDIRECT"])
        self.assertNotIn(SPECIFIC, RUNTIME["PROFILE_REDIRECT"])
        parser = load_profile(SPECIFIC)
        self.assertEqual(decode(parser, "Battery Voltage", [2100]), 210)
        self.assertEqual(decode(parser, "Today Production", [27]), 27)


class NumberEncodingTests(unittest.TestCase):
    def test_voltage_step_round_trips_through_real_writer(self):
        for volts, raw in ((160, 1600), (160.1, 1601), (160.3, 1603),
                           (200, 2000), (227, 2270), (203.5, 2035), (700, 7000)):
            with self.subTest(volts=volts):
                entity = SimpleNamespace(scale=0.1, offset=None, write=AsyncMock())
                complete_inline(RUNTIME["async_set_native_value"](entity, volts))
                entity.write.assert_awaited_once_with(raw, volts)

    def test_power_current_and_offset_encodings(self):
        for scale, offset, native, raw in ((10, None, 30000, 3000),
                                           (None, None, 75, 75), (0.1, 1000, 25, 1250),
                                           (0.01, None, 38.01, 3801), (0.1, None, 160.19, 1601)):
            entity = SimpleNamespace(scale=scale, offset=offset, write=AsyncMock())
            complete_inline(RUNTIME["async_set_native_value"](entity, native))
            entity.write.assert_awaited_once_with(raw, native)


if __name__ == "__main__":
    unittest.main()
