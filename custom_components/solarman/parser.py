from __future__ import annotations

import re
import bisect

from logging import getLogger
from datetime import datetime

from .const import *
from .common import *

_LOGGER = getLogger(__name__)

class ParameterParser:
    def __init__(self):
        self._update_interval = DEFAULT_[UPDATE_INTERVAL]
        self._is_single_code = DEFAULT_[IS_SINGLE_CODE]
        self._code = DEFAULT_[REGISTERS_CODE]
        self._min_span = DEFAULT_[REGISTERS_MIN_SPAN]
        self._max_size = DEFAULT_[REGISTERS_MAX_SIZE]
        self._digits = DEFAULT_[DIGITS]
        self._requests = None
        self._previous_result = {}
        self._result = {}

        self.info: dict[str, str] = {}

    async def init(self, path: str, filename: str, parameters: dict):
        profile = await yaml_open(path + filename)

        if "info" in profile:
            self.info = unwrap(profile["info"], "model", parameters[PARAM_[CONF_MOD]])
        
        self.info |= {"filename": filename}

        if "default" in profile and (default := profile["default"]):
            if REQUEST_UPDATE_INTERVAL in default:
                self._update_interval = default[REQUEST_UPDATE_INTERVAL]
            if REQUEST_CODE in default:
                self._code = default[REQUEST_CODE]
            if REQUEST_MIN_SPAN in default:
                self._min_span = default[REQUEST_MIN_SPAN]
            if REQUEST_MAX_SIZE in default:
                self._max_size = default[REQUEST_MAX_SIZE]
            if DIGITS in default:
                self._digits = default[DIGITS]

        if "requests" in profile and "requests_fine_control" in profile:
            _LOGGER.debug("Fine control of request sets is enabled!")
            self._requests = [create_request(get_request_code(r, self._code), r[REQUEST_START], r[REQUEST_END]) for r in profile["requests"]]

        _LOGGER.debug(f"{filename} w/ {'defaults' if 'default' in profile else 'stock values'} for update_interval: {self._update_interval}, code: {self._code}, min_span: {self._min_span}, max_size: {self._max_size}, digits: {self._digits}, parameters: {parameters}")

        table = {r: get_request_code(pr) for pr in profile["requests"] for r in range(pr[REQUEST_START], pr[REQUEST_END] + 1)} if "requests" in profile and not "requests_fine_control" in profile else {}

        self._items: list[dict] = [i for i in sorted([preprocess_descriptions(item, group, table, self._code, parameters) for group in profile["parameters"] for item in group["items"]], key = lambda x: (get_code(x, "read", self._code), max(x["registers"])) if x.get("registers") else (-1, -1)) if enforce_parameters(i, parameters)]

        if (items_codes := [get_code(i, "read", self._code) for i in self._items if "registers" in i]) and (is_single_code := all_same(items_codes)):
            self._is_single_code = is_single_code
            self._code = items_codes[0]

        l = (lambda x, y: y - x > self._min_span) if self._min_span > -1 else (lambda x, y: False)

        self._lambda = lambda x, y, z: l(x[1], y[1]) or y[1] - z[1] >= self._max_size
        self._lambda_code_aware = lambda x, y, z: x[0] != y[0] or self._lambda(x, y, z)

        return self

    def is_valid(self, parameters):
        return "name" in parameters and "rule" in parameters # and "registers" in parameters

    def is_enabled(self, parameters):
        return not "disabled" in parameters

    def is_requestable(self, parameters):
        return self.is_valid(parameters) and self.is_enabled(parameters) and parameters["rule"] > 0

    def is_scheduled(self, parameters, runtime):
        return "realtime" in parameters or (runtime % (parameters[REQUEST_UPDATE_INTERVAL] if REQUEST_UPDATE_INTERVAL in parameters else self._update_interval) == 0)

    def default_from_unit_of_measurement(self, parameters):
        return None if (uom := parameters["uom"] if "uom" in parameters else (parameters["unit_of_measurement"] if "unit_of_measurement" in parameters else "")) and re.match(r"\S+", uom) else ""

    def set_state(self, key, state, value = None):
        self._result[key] = (state, value)

    def get_entity_descriptions(self, platform: str | None = None):
        return [i for i in self._items if self.is_valid(i) and self.is_enabled(i) and not "attribute" in i and (i.get("platform") == platform or platform is None)]

    def schedule_requests(self, runtime):
        self._result = {}

        if self._requests:
            return self._requests

        registers = []

        for i in self._items:
            if self.is_requestable(i) and self.is_scheduled(i, runtime):
                self.set_state(i["key"], self.default_from_unit_of_measurement(i))
                if "registers" in i:
                    for r in sorted(i["registers"]):
                        if (register := (get_code(i, "read"), r)) and not register in registers:
                            bisect.insort(registers, register)

        if len(registers) == 0:
            return []

        groups = group_when(registers, self._lambda if self._is_single_code or all_same([r[0] for r in registers]) else self._lambda_code_aware)

        return [create_request(self._code if self._is_single_code else r[0][0], r[0][1], r[-1][1]) for r in groups]

    def reset(self):
        self._previous_result = {}

    def in_range(self, key, value, rule):
        if ((min := rule.get("min")) is not None and value < min) or ((max := rule.get("max")) is not None and value > max):
            _LOGGER.debug(f"{key}: {value} is outside of range: {rule}")
            return False

        return True

    def do_validate(self, key, value, rule):
        invalid = 0
        previous_value = None

        if ((min := rule.get("min")) is not None and min > value) or ((max := rule.get("max")) is not None and max < value):
            invalid = 1

        if dev := rule.get("dev"):
            if value and (previous_value := self._previous_result.get(key)) is not None and abs(value - previous_value) > dev:
                invalid |= 2
            elif not invalid:
                self._previous_result[key] = value

        if invalid > 0 and (message := f"{key} validation failed, triggered by state: {value}{'' if previous_value is None else f' ({previous_value})'} with conditions: {rule}"):
            if "invalidate_all" in rule and ((inv := rule.get("invalidate_all")) is None or invalid & inv):
                raise ValueError(f"Invalidate complete dataset - {message}")
            else:
                _LOGGER.debug(message)

        return invalid == 0

    def process(self, data):
        if data is not None:
            for i in self._items:
                if not (self.is_valid(i) and self.is_enabled(i)):
                    continue

                # Try parsing if the register is present.
                if (registers := i.get("registers")) is None:
                    continue

                # Check that the first register in the definition is within the register set in the raw data.
                if get_start_addr(data, get_code(i, "read"), registers[0]) is not None:
                    try:
                        match i["rule"]:
                            case 1 | 3:
                                self.try_parse_unsigned(data, i)
                            case 2 | 4:
                                self.try_parse_signed(data, i)
                            case 5:
                                self.try_parse_ascii(data, i)
                            case 6:
                                self.try_parse_bits(data, i)
                            case 7:
                                self.try_parse_version(data, i)
                            case 8:
                                self.try_parse_datetime(data, i)
                            case 9:
                                self.try_parse_time(data, i)
                            case 10:
                                self.try_parse_raw(data, i)
                    except Exception as e:
                        _LOGGER.error(f"ParameterParser.try_parse: data: {data}, definition: {i} [{strepr(e)}]")
                        raise

        return self._result

    def _read_registers(self, data, definition):
        code = get_code(definition, "read")
        value = 0
        shift = 0

        if not (registers := definition.get("registers")):
            return None

        for r in registers:
            if (temp := get_addr_value(data, code, r)) is None:
                return None

            value += (temp & 0xFFFF) << shift
            shift += 16

        if (range := definition.get("range")) and not self.in_range(definition["key"], value, range):
            return range.get("default")

        if (mask := definition.get("mask")) is not None:
            value &= mask

        if (bit := definition.get("bit")) is not None:
            value = (value >> bit) & 1

        if (bitmask := definition.get("bitmask")) is not None:
            value = int((value & bitmask) / bitmask)

        if "lookup" not in definition:
            if (offset := definition.get("offset")) is not None:
                value -= offset

            if (scale := definition.get("scale")) is not None:
                value *= scale

            if (divide := definition.get("divide")) is not None:
                value //= divide

        return value

    def _read_registers_signed(self, data, definition):
        code = get_code(definition, "read")
        magnitude = definition.get("magnitude", False)
        maxint = 0
        value = 0
        shift = 0

        if not (registers := definition.get("registers")):
            return None

        for r in registers:
            if (temp := get_addr_value(data, code, r)) is None:
                return None

            maxint <<= 16
            maxint |= 0xFFFF
            value += (temp & 0xFFFF) << shift
            shift += 16

        if value > (maxint >> 1):
            value = (value - maxint - 1) if not magnitude else -(value & (maxint >> 1))

        if (range := definition.get("range")) and not self.in_range(definition["key"], value, range):
            return range.get("default")

        if (offset := definition.get("offset")) is not None:
            value -= offset

        if (scale := definition.get("scale")) is not None:
            value *= scale

        if (divide := definition.get("divide")) is not None:
            value //= divide

        return value
    
    def _read_registers_custom(self, data, definition):
        value = 0

        for s in definition["sensors"]:
            if not (registers := s.get("registers")):
                continue

            if (n := self._read_registers(data, s) if not "signed" in s else self._read_registers_signed(data, s)) is None:
                return None

            if (m := s.get("multiply")) and (c := self._read_registers(data, m) if not "signed" in m else self._read_registers_signed(data, m)) is not None:
                n *= c

            if (validation := s.get("validation")) is not None and not self.do_validate(registers, n, validation):
                if (d := validation.get("default")) is None:
                    continue
                n = d

            if (o := s.get("operator")) is None:
                value += n
            else:
                match o:
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
        if (value := self._read_registers(data, definition) if not "sensors" in definition else self._read_registers_custom(data, definition)) is None:
            return

        if "uint" in definition and value < 0:
            value = 0

        key = definition["key"]

        if "lookup" in definition:
            self.set_state(key, lookup_value(value, definition["lookup"]), int(value) if len(definition["registers"]) == 1 else list(split_p16b(value)))
            return

        if (validation := definition.get("validation")) is not None and not self.do_validate(key, value, validation):
            if (d := validation.get("default")) is None:
                return
            value = d

        self.set_state(key, get_number(value, get_or_def(definition, DIGITS, self._digits)))

        if (a := definition.get("attributes")) is not None and "value" in a:
            self.set_state(key, self._result[key][0], int(value))

    def try_parse_signed(self, data, definition):
        if (value := self._read_registers_signed(data, definition) if not "sensors" in definition else self._read_registers_custom(data, definition)) is None:
            return

        if definition.get("inverted"):
            value = -value

        key = definition["key"]

        if (validation := definition.get("validation")) is not None and not self.do_validate(key, value, validation):
            if (d := validation.get("default")) is None:
                return
            value = d

        self.set_state(key, get_number(value, get_or_def(definition, DIGITS, self._digits)))

    def try_parse_ascii(self, data, definition):
        code = get_code(definition, "read")
        value = ""

        for r in definition["registers"]:
            if (temp := get_addr_value(data, code, r)) is None:
                return

            value += chr(temp >> 8) + chr(temp & 0xFF)

        self.set_state(definition["key"], value)

    def try_parse_bits(self, data, definition):
        code = get_code(definition, "read")
        value = []

        for r in definition["registers"]:
            if (temp := get_addr_value(data, code, r)) is None:
                return

            value.append(hex(temp))

        self.set_state(definition["key"], value)

    def try_parse_version(self, data, definition):
        code = get_code(definition, "read")
        f = "{:1x}" if "hex" in definition else "{:1d}"
        delimiter_digit, delimiter_register = (d, "-") if (d := definition.get("delimiter", '.')) is not None and isinstance(d, str) else (d.get("digit", "."), d.get("register", "-"))
        value = ""

        registers_count = len(definition["registers"])

        for r in definition["registers"]:
            if (temp := get_addr_value(data, code, r)) is None:
                return

            value += f.format(temp >> 12) + delimiter_digit + f.format(temp >> 8 & 0x0F) + delimiter_digit + f.format(temp >> 4 & 0x0F) + delimiter_digit + f.format(temp & 0x0F)

            if registers_count > 1:
                value += delimiter_register

        if value.endswith(delimiter_register):
            value = value[:-1]

        if (remove := definition.get("remove")) is not None:
            value = value.replace(remove, "")

        self.set_state(definition["key"], value.upper())

    def try_parse_datetime(self, data, definition):
        code = get_code(definition, "read")
        value = ""

        registers_count = len(definition["registers"])

        for i, r in enumerate(definition["registers"]):
            if (temp := get_addr_value(data, code, r)) is None:
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
            self.set_state(definition["key"], value)
        except Exception as e:
            _LOGGER.debug(f"ParameterParser.try_parse_datetime: data: {data}, definition: {definition} [{strepr(e)}]")

    def try_parse_time(self, data, definition):
        code = get_code(definition, "read")
        f, d = ("{:02d}", get_or_def(definition, "dec", 100)) if not "hex" in definition else ("{:02x}", get_or_def(definition, "hex", 0x100))
        offset = definition.get("offset")
        value = ""

        registers_count = len(definition["registers"])

        for i, r in enumerate(definition["registers"]):
            if (temp := get_addr_value(data, code, r)) is None:
                return

            if registers_count == 1:
                high, low = div_mod(temp, d)
                value = str(f.format(int(high))) + ":" + str(f.format(int(low)))
            else:
                if temp >= d:
                    f = "{:02d}"
                    if offset:
                        temp -= offset
                    high, low = div_mod(temp, d)
                    temp = f"{high}{low}"
                value += str(f.format(int(temp)))
                if i == 0 or (i == 1 and registers_count > 2):
                    value += ":"

        self.set_state(definition["key"], value)

    def try_parse_raw(self, data, definition):
        code = get_code(definition, "read")
        value = []

        for r in definition["registers"]:
            if (temp := get_addr_value(data, code, r)) is None:
                return

            value.append(temp)

        self.set_state(definition["key"], value)
