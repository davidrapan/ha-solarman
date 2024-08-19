from __future__ import annotations

import re
import struct
import logging

from datetime import datetime

from .const import *
from .common import *

_LOGGER = logging.getLogger(__name__)

class ParameterParser:
    def __init__(self, profile):
        self._profile = profile
        self._update_interval = DEFAULT_REGISTERS_UPDATE_INTERVAL
        self._code = DEFAULT_REGISTERS_CODE
        self._min_span = DEFAULT_REGISTERS_MIN_SPAN
        self._digits = DEFAULT_DIGITS
        self._registers_table = {}
        self._result = {}

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

        for p in self.parameters():
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

    def flush_states(self):
        self._result = {}

    def parameters(self):
        return self._profile["parameters"]

    def is_valid(self, parameters):
        return "name" in parameters and "rule" in parameters  # and "registers" in parameters

    def is_enabled(self, parameters):
        return not "disabled" in parameters

    def is_sensor(self, parameters):
        return self.is_valid(parameters) and not "attribute" in parameters

    def is_requestable(self, parameters):
        return self.is_valid(parameters) and self.is_enabled(parameters) and parameters["rule"] > 0

    def is_scheduled(self, parameters, runtime, default):
        return "realtime" in parameters or (runtime % (parameters[REQUEST_UPDATE_INTERVAL] if REQUEST_UPDATE_INTERVAL in parameters else default) == 0)

    def default_from_unit_of_measurement(self, parameters):
        return None if (uom := parameters["uom"] if "uom" in parameters else (parameters["unit_of_measurement"] if "unit_of_measurement" in parameters else "")) and re.match(r"\S+", uom) else ""

    def set_state(self, key, value):
        self._result[key] = {}
        self._result[key]["state"] = value

    def get_sensors(self):
        result = [{"name": "Connection", "artificial": "state", "platform": "binary_sensor"}, {"name": "Update Interval", "artificial": "interval"}]
        for i in self.parameters():
            for j in i["items"]:
                if self.is_sensor(j):
                    result.append(j)

        return result

    def get_requests(self, runtime = 0):
        self.flush_states()

        if "requests" in self._profile and "requests_fine_control" in self._profile:
            _LOGGER.debug("Fine control of request sets is enabled!")
            return self._profile["requests"]

        registers = []

        for p in self.parameters():
            for i in p["items"]:
                if self.is_requestable(i) and self.is_scheduled(i, runtime, self._update_interval if not REQUEST_UPDATE_INTERVAL in p else p[REQUEST_UPDATE_INTERVAL]):
                    self.set_state(i["name"], self.default_from_unit_of_measurement(i))
                    if "registers" in i:
                        for r in i["registers"]:
                            registers.append(r)

        if len(registers) == 0:
            return {}

        registers.sort()

        groups = group_when(registers, self._lambda if self._is_single_code or all_same([self._registers_table[r] for r in registers]) else self._lambda_code_aware)

        return [{ REQUEST_START: r[0], REQUEST_END: r[-1], REQUEST_CODE: self._code if self._is_single_code else self._registers_table[r[0]] } for r in groups]

    def parse(self, rawData, start, length):
        for param in self.parameters():
            for item in param["items"]:
                if not (self.is_valid(item) and self.is_enabled(item)):
                    continue

                # Check that the first register in the definition is within the register set in the raw data.
                # Try parsing if the register is present.
                registers = item.get("registers")
                if registers is None:
                    continue

                firstRegister = registers[0]
                if start <= firstRegister < start + length:
                    self.try_parse(rawData, item, start, length)

        return

    def get_result(self):
        return self._result

    def in_range(self, value, definition):
        if "range" in definition:
            range = definition["range"]
            if "min" in range and "max" in range:
                if value < range["min"] or value > range["max"]:
                    return False

        return True

    def lookup_value(self, value, keyvaluepairs):
        for o in keyvaluepairs:
            if o["key"] == value or o["key"] == "default":
                return o["value"]

        return keyvaluepairs[0]["value"]

    def do_validate(self, key, value, rule):
        if "min" in rule:
            if rule["min"] > value:
                if "invalidate_all" in rule:
                    raise ValueError(f"Invalidate complete dataset ({key} ~ {value})")
                return False

        if "max" in rule:
            if rule["max"] < value:
                if "invalidate_all" in rule:
                    raise ValueError(f"Invalidate complete dataset ({key} ~ {value})")
                return False

        return True

    def try_parse(self, rawData, definition, start, length):
        try:
            self.try_parse_field(rawData, definition, start, length)
        except Exception as e:
            _LOGGER.error(f"ParameterParser.try_parse: start: {start}, length: {length}, rawData: {rawData}, definition: {definition} [{format_exception(e)}]")
            raise

        return

    def try_parse_field(self, rawData, definition, start, length):
        match definition["rule"]:
            case 1:
                self.try_parse_unsigned(rawData, definition, start, length)
            case 2:
                self.try_parse_signed(rawData, definition, start, length)
            case 3:
                self.try_parse_unsigned(rawData, definition, start, length)
            case 4:
                self.try_parse_signed(rawData, definition, start, length)
            case 5:
                self.try_parse_ascii(rawData, definition, start, length)
            case 6:
                self.try_parse_bits(rawData, definition, start, length)
            case 7:
                self.try_parse_version(rawData, definition, start, length)
            case 8:
                self.try_parse_datetime(rawData, definition, start, length)
            case 9:
                self.try_parse_time(rawData, definition, start, length)
            case 10:
                self.try_parse_raw(rawData, definition, start, length)

        return

    def _read_registers(self, rawData, definition, start, length):
        scale = definition["scale"] if "scale" in definition else 1
        found = True
        value = 0
        shift = 0

        for r in definition["registers"]:
            index = r - start
            if index >= 0 and index < length:
                value += (rawData[index] & 0xFFFF) << shift
                shift += 16
            else:
                found = False

        if found:
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
                    value = value - definition["offset"]

                value = value * scale

                if "divide" in definition and (divide := definition["divide"]) and divide != 0:
                    value //= divide

        return value if found else None

    def _read_registers_signed(self, rawData, definition, start, length):
        magnitude = definition["magnitude"] if "magnitude" in definition else False
        scale = definition["scale"] if "scale" in definition else 1
        found = True
        maxint = 0
        value = 0
        shift = 0

        for r in definition["registers"]:
            index = r - start
            if index >= 0 and index < length:
                maxint <<= 16
                maxint |= 0xFFFF
                value += (rawData[index] & 0xFFFF) << shift
                shift += 16
            else:
                found = False

        if found:
            if not self.in_range(value, definition):
                return None

            if "offset" in definition:
                value = value - definition["offset"]

            if value > (maxint >> 1):
                value = (value - maxint) if not magnitude else -(value & (maxint >> 1))

            value = value * scale

            if "divide" in definition and (divide := definition["divide"]) and divide != 0:
                value //= divide

        return value if found else None

    def try_parse_unsigned(self, rawData, definition, start, length):
        key = definition["name"]
        value = 0
        found = True

        if "sensors" in definition:
            for s in definition["sensors"]:
                if (n := (self._read_registers(rawData, s, start, length) if not "signed" in s else self._read_registers_signed(rawData, s, start, length))) is not None:
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
                else:
                    found = False
        else:
            value = self._read_registers(rawData, definition, start, length)
            found = value is not None

        if found:
            if "uint" in definition and value < 0:
                value = 0

            if "lookup" in definition:
                self.set_state(key, self.lookup_value(value, definition["lookup"]))
                self._result[key]["value"] = int(value)
            else:
                if "validation" in definition:
                    if not self.do_validate(key, value, definition["validation"]):
                        return

                self.set_state(key, get_number(value, definition["digits"] if "digits" in definition else self._digits))

                if "attributes" in definition and "value" in definition["attributes"]:
                    self._result[key]["value"] = int(value)

        return

    def try_parse_signed(self, rawData, definition, start, length):
        key = definition["name"]
        value = self._read_registers_signed(rawData, definition, start, length)

        if value is not None:
            if "inverted" in definition and definition["inverted"]:
                value = -value

            if "validation" in definition:
                if not self.do_validate(key, value, definition["validation"]):
                    return

            self.set_state(key, get_number(value, definition["digits"] if "digits" in definition else self._digits))

        return

    def try_parse_ascii(self, rawData, definition, start, length):
        key = definition["name"]         
        found = True
        value = ""

        for r in definition["registers"]:
            index = r - start
            if index >= 0 and index < length:
                temp = rawData[index]
                value = value + chr(temp >> 8) + chr(temp & 0xFF)
            else:
                found = False

        if found:
            self.set_state(key, value)

        return  
    
    def try_parse_bits(self, rawData, definition, start, length):
        key = definition["name"]         
        found = True
        value = []

        for r in definition["registers"]:
            index = r - start
            if index >= 0 and index < length:
                value.append(hex(rawData[index]))
            else:
                found = False

        if found:
            self.set_state(key, value)

        return 
    
    def try_parse_version(self, rawData, definition, start, length):
        key = definition["name"]
        found = True
        value = ""

        for r in definition["registers"]:
            index = r - start
            if index >= 0 and index < length:
                temp = rawData[index]
                value = value + str(temp >> 12) + "." + str(temp >> 8 & 0x0F) + "." + str(temp >> 4 & 0x0F) + "." + str(temp & 0x0F)
            else:
                found = False

        if found:
            if "remove" in definition:
                value = value.replace(definition["remove"], "")

            self.set_state(key, value)

        return

    def try_parse_datetime(self, rawData, definition, start, length):
        key = definition["name"]         
        found = True
        value = ""

        registers_count = len(definition["registers"])

        for i, r in enumerate(definition["registers"]):
            index = r - start
            if index >= 0 and index < length:
                temp = rawData[index]
                if registers_count == 3:
                    if i == 0:
                        value = value + str(temp >> 8) + "/" + str(temp & 0xFF) + "/"
                    elif i == 1:
                        value = value + str(temp >> 8) + " " + str(temp & 0xFF) + ":"
                    elif i == 2:
                        value = value + str(temp >> 8) + ":" + str(temp & 0xFF)
                    else:
                        value = value + str(temp >> 8) + str(temp & 0xFF)
                elif registers_count == 6:
                    if i == 0 or i == 1:
                        value = value + str(temp) + "/"
                    elif i == 2:
                        value = value + str(temp) + " "
                    elif i == 3 or i == 4:
                        value = value + str(temp) + ":"
                    else:
                        value = value + str(temp)
            else:
                found = False

        if found:
            if value.endswith(":"):
                value = value[:-1]

            self.set_state(key, datetime.strptime(value, '%y/%m/%d %H:%M:%S'))

        return

    def try_parse_time(self, rawData, definition, start, length):
        key = definition["name"]
        found = True
        value = ""

        registers_count = len(definition["registers"])

        for i, r in enumerate(definition["registers"]):
            index = r - start
            if index >= 0 and index < length:
                temp = rawData[index]
                if registers_count == 1:
                    value = str("{:02d}".format(int(temp / 100))) + ":" + str("{:02d}".format(int(temp % 100)))
                else:
                    value = value + str("{:02d}".format(int(temp)))
                    if i == 0 or (i == 1 and registers_count > 2):
                        value = value + ":"
            else:
                found = False

        if found:
            self.set_state(key, value)

        return

    def try_parse_raw(self, rawData, definition, start, length):
        key = definition["name"]
        found = True
        value = []

        for r in definition["registers"]:
            index = r - start
            if index >= 0 and index < length:
                value.append(rawData[index])
            else:
                found = False

        if found:
            self.set_state(key, value)

        return