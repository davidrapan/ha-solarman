from __future__ import annotations

import re
import struct
import logging

from datetime import datetime

from .const import *
from .common import *

_LOGGER = logging.getLogger(__name__)

class ParameterParser:
    _update_interval = DEFAULT_REGISTERS_UPDATE_INTERVAL
    _code = DEFAULT_REGISTERS_CODE
    _min_span = DEFAULT_REGISTERS_MIN_SPAN
    _digits = DEFAULT_DIGITS
    _registers_table = {}
    _result = {}

    def __init__(self, profile):
        self._profile = profile

        if "default" in self._profile:
            default = self._profile["default"]
            if REQUEST_UPDATE_INTERVAL in default:
                self._update_interval = default[REQUEST_UPDATE_INTERVAL]
            if REQUEST_CODE in default:
                self._code = default[REQUEST_CODE]
            if REQUEST_MIN_SPAN in default:
                self._min_span = default[REQUEST_MIN_SPAN]
            if "digits" in default:
                self._digits = default["digits"]

        _LOGGER.debug(f"{'Defaults' if 'default' in self._profile else 'Stock values'} for update_interval: {self._update_interval}, code: {self._code}, min_span: {self._min_span}, digits: {self._digits}")

        requests_table = {}

        if "requests" in self._profile and not "requests_fine_control" in self._profile:
            for pr in self._profile["requests"]:
                for r in range(pr[REQUEST_START], pr[REQUEST_END] + 1):
                    requests_table[r] = get_request_code(pr)

        for p in self._profile["parameters"]:
            for i in p["items"]:
                if "registers" in i:
                    for r in i["registers"]:
                        self._registers_table[r] = (i["code"] if isinstance(i["code"], int) else i["code"]["read"]) if "code" in i else (p["code"] if "code" in p else (requests_table[r] if r in requests_table else self._code))

        registers_table_values = self._registers_table.values()

        self._is_single_code = all_same(list(registers_table_values))

        if self._is_single_code:
            self._code = next(iter(registers_table_values))

        self._lambda = lambda x, y: y - x > self._min_span
        self._lambda_code_aware = lambda x, y: self._registers_table[x] != self._registers_table[y] or y - x > self._min_span

        self._items = [inherit_descriptions(item, group) for group in self._profile["parameters"] for item in group["items"]]

    def flush_states(self):
        self._result = {}

    def is_valid(self, parameters):
        return "name" in parameters and "rule" in parameters  # and "registers" in parameters

    def is_enabled(self, parameters):
        return not "disabled" in parameters

    def is_requestable(self, parameters):
        return self.is_valid(parameters) and self.is_enabled(parameters) and parameters["rule"] > 0

    def is_scheduled(self, parameters, runtime):
        return "realtime" in parameters or (runtime % (parameters[REQUEST_UPDATE_INTERVAL] if REQUEST_UPDATE_INTERVAL in parameters else self._update_interval) == 0)

    def default_from_unit_of_measurement(self, parameters):
        return None if (uom := parameters["uom"] if "uom" in parameters else (parameters["unit_of_measurement"] if "unit_of_measurement" in parameters else "")) and re.match(r"\S+", uom) else ""

    def set_state(self, key, value):
        self._result[key] = {}
        self._result[key]["state"] = value

    def get_entity_descriptions(self):
        return [i for i in self._items if self.is_valid(i) and not "attribute" in i]

    def schedule_requests(self, runtime = 0):
        self.flush_states()

        if "requests" in self._profile and "requests_fine_control" in self._profile:
            _LOGGER.debug("Fine control of request sets is enabled!")
            return self._profile["requests"]

        registers = []

        for i in self._items:
            if self.is_requestable(i) and self.is_scheduled(i, runtime):
                self.set_state(i["name"], self.default_from_unit_of_measurement(i))
                if "registers" in i:
                    for r in i["registers"]:
                        registers.append(r)

        if len(registers) == 0:
            return {}

        registers.sort()

        groups = group_when(registers, self._lambda if self._is_single_code or all_same([self._registers_table[r] for r in registers]) else self._lambda_code_aware)

        return [{ REQUEST_START: r[0], REQUEST_END: r[-1], REQUEST_CODE: self._code if self._is_single_code else self._registers_table[r[0]] } for r in groups]

    def in_range(self, value, definition):
        if "range" in definition:
            range = definition["range"]
            if "min" in range and "max" in range:
                if value < range["min"] or value > range["max"]:
                    _LOGGER.debug(f"Value: {value} of {definition["registers"]} is out of range: {range}")
                    return False

        return True

    def lookup_value(self, value, keyvaluepairs):
        for o in keyvaluepairs:
            if "bit" in o:
                if 1 << o["bit"] == value or "default":
                    return o["value"]
            else:
                key = o["key"]
                if isinstance(key, list):
                    for k in key:
                        if k == value:
                            return o["value"]
                elif key == value or "default" in o or key == "default":
                    return o["value"]

        return keyvaluepairs[0]["value"]

    def do_validate(self, key, value, rule):
        if "min" in rule and (min := rule["min"]) and min > value:
            _LOGGER.debug(f"do_validate {key}: {value} < {min}")
            if "invalidate_all" in rule:
                raise ValueError(f"Invalidate complete dataset - {key}: {value} < {min}")
            return False

        if "max" in rule and (max := rule["max"]) and max < value:
            _LOGGER.debug(f"do_validate {key}: {value} > {max}")
            if "invalidate_all" in rule:
                raise ValueError(f"Invalidate complete dataset - {key}: {value} > {max}")
            return False

        return True

    def process(self, data):
        if data:
            for i in self._items:
                if not (self.is_valid(i) and self.is_enabled(i)):
                    continue

                # Try parsing if the register is present.
                if (registers := i.get("registers")) is None:
                    continue

                # Check that the first register in the definition is within the register set in the raw data.
                if get_start_addr(data, registers[0]) is not None:
                    self.try_parse(data, i)

        return self._result

    def try_parse(self, data, definition):
        try:
            self.try_parse_field(data, definition)
        except Exception as e:
            _LOGGER.error(f"ParameterParser.try_parse: data: {data}, definition: {definition} [{format_exception(e)}]")
            raise

    def try_parse_field(self, data, definition):
        match definition["rule"]:
            case 1 | 3:
                self.try_parse_unsigned(data, definition)
            case 2 | 4:
                self.try_parse_signed(data, definition)
            case 5:
                self.try_parse_ascii(data, definition)
            case 6:
                self.try_parse_bits(data, definition)
            case 7:
                self.try_parse_version(data, definition)
            case 8:
                self.try_parse_datetime(data, definition)
            case 9:
                self.try_parse_time(data, definition)
            case 10:
                self.try_parse_raw(data, definition)

    def _read_registers(self, data, definition):
        value = 0
        shift = 0

        for r in definition["registers"]:
            if (temp := get_addr_value(data, r)) is None:
                return None

            value += (temp & 0xFFFF) << shift
            shift += 16

        if not self.in_range(value, definition):
            return None

        if "mask" in definition:
            value &= definition["mask"]

        if "bit" in definition:
            value = (value >> definition["bit"]) & 1

        if "bitmask" in definition and (bitmask := definition["bitmask"]):
            value = int((value & bitmask) / bitmask)

        if "lookup" not in definition:
            if "offset" in definition:
                value -= definition["offset"]

            if "scale" in definition and (scale := definition["scale"]):
                value *= scale

            if "divide" in definition and (divide := definition["divide"]) and divide != 0:
                value //= divide

        return value

    def _read_registers_signed(self, data, definition):
        magnitude = definition["magnitude"] if "magnitude" in definition else False
        maxint = 0
        value = 0
        shift = 0

        for r in definition["registers"]:
            if (temp := get_addr_value(data, r)) is None:
                return None

            maxint <<= 16
            maxint |= 0xFFFF
            value += (temp & 0xFFFF) << shift
            shift += 16

        if not self.in_range(value, definition):
            return None

        if "offset" in definition:
            value -= definition["offset"]

        if value > (maxint >> 1):
            value = (value - maxint) if not magnitude else -(value & (maxint >> 1))

        if "scale" in definition and (scale := definition["scale"]):
            value *= scale

        if "divide" in definition and (divide := definition["divide"]) and divide != 0:
            value //= divide

        return value
    
    def _read_registers_custom(self, data, definition):
        value = 0

        for s in definition["sensors"]:
            if not "scale" in s and "scale" in definition and (scale := definition["scale"]):
                s["scale"] = scale

            if (n := (self._read_registers(data, s) if not "signed" in s else self._read_registers_signed(data, s))) is None:
                return None

            if (validation := get_or_default(s, "validation")) and not self.do_validate(s["registers"], n, validation):
                if not "default" in validation:
                    continue
                n = validation["default"]

            if "multiply" in s and (s_multiply := s["multiply"]):
                if not "scale" in s_multiply and "scale" in s and (s_scale := s["scale"]):
                    s_multiply["scale"] = s_scale
                if (c := self._read_registers(data, s_multiply)) is not None:
                    n *= c
            if not "operator" in s:
                value += n
            else:
                match s["operator"]:
                    case "subtract":
                        value -= n
                    case "multiply":
                        value *= n
                    case "divide" if n != 0:
                        value /= n
                    case _:
                        value += n

        return value

    def try_parse_unsigned(self, data, definition):
        if (value := (self._read_registers(data, definition) if not "sensors" in definition else self._read_registers_custom(data, definition))) is None:
            return

        if "uint" in definition and value < 0:
            value = 0

        key = definition["name"]

        if "lookup" in definition:
            self.set_state(key, self.lookup_value(value, definition["lookup"]))
            self._result[key]["value"] = int(value)

            return

        if (validation := get_or_default(definition, "validation")) and not self.do_validate(key, value, validation):
            if not "default" in validation:
                return
            value = validation["default"]

        self.set_state(key, get_number(value, definition["digits"] if "digits" in definition else self._digits))

        if "attributes" in definition and "value" in definition["attributes"]:
            self._result[key]["value"] = int(value)

    def try_parse_signed(self, data, definition):
        if (value := (self._read_registers_signed(data, definition) if not "sensors" in definition else self._read_registers_custom(data, definition))) is None:
            return

        if "inverted" in definition and definition["inverted"]:
            value = -value

        key = definition["name"]

        if (validation := get_or_default(definition, "validation")) and not self.do_validate(key, value, validation):
            if not "default" in validation:
                return
            value = validation["default"]

        self.set_state(key, get_number(value, definition["digits"] if "digits" in definition else self._digits))

    def try_parse_ascii(self, data, definition):
        value = ""

        for r in definition["registers"]:
            if (temp := get_addr_value(data, r)) is None:
                return

            value += chr(temp >> 8) + chr(temp & 0xFF)

        self.set_state(definition["name"], value)

    def try_parse_bits(self, data, definition):
        value = []

        for r in definition["registers"]:
            if (temp := get_addr_value(data, r)) is None:
                return

            value.append(hex(temp))

        self.set_state(definition["name"], value)

    def try_parse_version(self, data, definition):
        value = ""

        for r in definition["registers"]:
            if (temp := get_addr_value(data, r)) is None:
                return

            value += str(temp >> 12) + "." + str(temp >> 8 & 0x0F) + "." + str(temp >> 4 & 0x0F) + "." + str(temp & 0x0F)

        if "remove" in definition:
            value = value.replace(definition["remove"], "")

        self.set_state(definition["name"], value)

    def try_parse_datetime(self, data, definition):
        value = ""

        registers_count = len(definition["registers"])

        for i, r in enumerate(definition["registers"]):
            if (temp := get_addr_value(data, r)) is None:
                return

            if registers_count == 3:
                if i == 0:
                    value += str(temp >> 8) + "/" + str(temp & 0xFF) + "/"
                elif i == 1:
                    value += str(temp >> 8) + " " + str(temp & 0xFF) + ":"
                elif i == 2:
                    value += str(temp >> 8) + ":" + str(temp & 0xFF)
                else:
                    value += str(temp >> 8) + str(temp & 0xFF)
            elif registers_count == 6:
                if i == 0 or i == 1:
                    value += str(temp) + "/"
                elif i == 2:
                    value += str(temp) + " "
                elif i == 3 or i == 4:
                    value += str(temp) + ":"
                else:
                    value += str(temp)

        if value.endswith(":"):
            value = value[:-1]

        try:
            if not "platform" in definition:
                value = datetime.strptime(value, DATETIME_FORMAT)
            self.set_state(definition["name"], value)
        except Exception as e:
            _LOGGER.debug(f"ParameterParser.try_parse_datetime: data: {data}, definition: {definition} [{format_exception(e)}]")

    def try_parse_time(self, data, definition):
        value = ""

        registers_count = len(definition["registers"])

        for i, r in enumerate(definition["registers"]):
            if (temp := get_addr_value(data, r)) is None:
                return

            if registers_count == 1:
                value = str("{:02d}".format(int(temp / 100))) + ":" + str("{:02d}".format(int(temp % 100)))
            else:
                value += str("{:02d}".format(int(temp)))
                if i == 0 or (i == 1 and registers_count > 2):
                    value += ":"

        self.set_state(definition["name"], value)

    def try_parse_raw(self, data, definition):
        value = []

        for r in definition["registers"]:
            if (temp := get_addr_value(data, r)) is None:
                return

            value.append(temp)

        self.set_state(definition["name"], value)
