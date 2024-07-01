from __future__ import annotations

import yaml
import struct
import logging

from itertools import groupby
from operator import itemgetter

from .const import COORDINATOR_QUERY_INTERVAL_DEFAULT, FLOAT_ROUND_TO
from .common import *

_LOGGER = logging.getLogger(__name__)

class ParameterParser:
    def __init__(self, parameter_definition):
        self._lookups = yaml.safe_load(parameter_definition)
        self.result = {}

    def lookup(self):
        return self._lookups["parameters"]

    def is_valid(self, parameters):
        return "name" in parameters and "rule" in parameters

    def is_enabled(self, parameters):
        return not "disabled" in parameters

    def is_sensor(self, parameters):
        return self.is_valid(parameters) and not "attribute" in parameters

    def is_requestable(self, parameters):
        return self.is_valid(parameters) and self.is_enabled(parameters) and parameters["rule"] > 0

    def is_scheduled(self, parameters, runtime):
        return "realtime" in parameters or (runtime % (parameters["update_interval"] if "update_interval" in parameters else COORDINATOR_QUERY_INTERVAL_DEFAULT) == 0)

    def get_sensors(self):
        result = [{"name": "Connection Status", "artificial": ""}]
        for i in self.lookup():
            for j in i["items"]:
                if self.is_sensor(j):
                    result.append(j)
        return result

    def get_requests(self, runtime = 0):
        if "requests" in self._lookups:
            return self._lookups["requests"]

        registers = []

        for i in self.lookup():
            for j in i["items"]:
                if self.is_requestable(j) and self.is_scheduled(j, runtime):
                    self.result[j["name"]] = ""
                    for r in j["registers"]:
                        registers.append(r)

        registers.sort()

        groups = group_when(registers, lambda x, y: y - x > 25)
        
        return [{ "start": r[0], "end": r[-1], "mb_functioncode": 0x03 } for r in groups]

    def parse(self, rawData, start, length):
        for i in self.lookup():
            for j in i["items"]:
                if self.is_valid(j) and self.is_enabled(j):
                    self.try_parse(rawData, j, start, length)
        return

    def get_result(self):
        return self.result

    def in_range(self, value, definition):
        if "range" in definition:
            range = definition["range"]
            if "min" in range and "max" in range:
                if value < range["min"] or value > range["max"]:
                    return False
        return True

    def lookup_value(self, value, definition):
        for o in definition["lookup"]:
            if (o["key"] == value):
                return o["value"]
        return value if not "lookup_default" in definition else f"{definition["lookup_default"]} [{value}]"

    def do_validate(self, title, value, rule):
        if "min" in rule:
            if rule["min"] > value:
                if "invalidate_all" in rule:
                    raise ValueError(f"Invalidate complete dataset ({title} ~ {value})")
                return False

        if "max" in rule:
            if rule["max"] < value:
                if "invalidate_all" in rule:
                    raise ValueError(f"Invalidate complete dataset ({title} ~ {value})")
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
        rule = definition["rule"]
        
        match rule:
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
                self.try_parse_raw(rawData,definition, start, length)
        return

    def try_parse_unsigned(self, rawData, definition, start, length):
        title = definition["name"]
        scale = definition["scale"]
        value = 0
        found = True
        shift = 0

        for r in definition["registers"]:
            index = r - start # get the decimal value of the register
            if (index >= 0) and (index < length):
                value += (rawData[index] & 0xFFFF) << shift
                shift += 16
            else:
                found = False

        if found:
            if not self.in_range(value, definition):
                return

            if "mask" in definition:
                mask = definition["mask"]
                value &= mask

            if "lookup" in definition:
                self.result[title] = self.lookup_value(value, definition)
                self.result[title + " enum"] = int(value)
            else:
                if "offset" in definition:
                    value = value - definition["offset"]

                value = value * scale

                if "validation" in definition:
                    if not self.do_validate(title, value, definition["validation"]):
                        return

                self.num_to_result(title, value)
        return

    def try_parse_signed(self, rawData, definition, start, length):
        title = definition["name"]
        scale = definition["scale"]
        value = 0
        found = True
        shift = 0
        maxint = 0

        for r in definition["registers"]:
            index = r - start # get the decimal value of the register
            if (index >= 0) and (index < length):
                maxint <<= 16
                maxint |= 0xFFFF
                value += (rawData[index] & 0xFFFF) << shift
                shift += 16
            else:
                found = False

        if found:
            if not self.in_range(value, definition):
                return

            if "offset" in definition:
                value = value - definition["offset"]

            if value > maxint / 2:
                value = (value - maxint) * scale
            else:
                value = value * scale

            if "validation" in definition:
                if not self.do_validate(title, value, definition["validation"]):
                    return

            self.num_to_result(title, value)
        return

    def try_parse_ascii(self, rawData, definition, start, length):
        title = definition["name"]         
        found = True
        value = ""
        for r in definition["registers"]:
            index = r - start # get the decimal value of the register
            if (index >= 0) and (index < length):
                temp = rawData[index]
                value = value + chr(temp >> 8) + chr(temp & 0xFF)
            else:
                found = False

        if found:
            self.result[title] = value
        return  
    
    def try_parse_bits(self, rawData, definition, start, length):
        title = definition["name"]         
        found = True
        value = []
        for r in definition["registers"]:
            index = r - start # get the decimal value of the register
            if (index >= 0) and (index < length):
                temp = rawData[index]
                value.append(hex(temp))
            else:
                found = False

        if found:
            self.result[title] = value
        return 
    
    def try_parse_version(self, rawData, definition, start, length):
        title = definition["name"]
        found = True
        value = ""
        for r in definition["registers"]:
            index = r - start # get the decimal value of the register
            if (index >= 0) and (index < length):
                temp = rawData[index]
                value = value + str(temp >> 12) + "." +  str(temp >> 8 & 0x0F) + "." + str(temp >> 4 & 0x0F) + "." + str(temp & 0x0F)
            else:
                found = False

        if found:
            self.result[title] = value
        return

    def try_parse_datetime(self, rawData, definition, start, length):
        title = definition["name"]         
        found = True
        value = ""
        print("start: ", start)
        for i,r in enumerate(definition["registers"]):
            index = r - start # get the decimal value of the register
            print ("index: ",index)
            if (index >= 0) and (index < length):
                temp = rawData[index]
                if(i==0):
                    value = value + str(temp >> 8)  + "/" + str(temp & 0xFF) + "/"
                elif (i==1):
                    value = value + str(temp >> 8)  + " " + str(temp & 0xFF) + ":"
                elif(i==2):
                    value = value + str(temp >> 8)  + ":" + str(temp & 0xFF)
                else:
                    value = value + str(temp >> 8)  + str(temp & 0xFF)
            else:
                found = False

        if found:
            self.result[title] = value
        return

    def try_parse_time(self, rawData, definition, start, length):
        title = definition["name"]         
        found = True
        value = ""
        for r in definition["registers"]:
            index = r - start # get the decimal value of the register
            if (index >= 0) and (index < length):
                temp = rawData[index]
                value = str("{:02d}".format(int(temp / 100))) + ":" + str("{:02d}".format(int(temp % 100)))
            else:
                found = False

        if found:
            self.result[title] = value
        return

    def try_parse_raw(self, rawData, definition, start, length):
        title = definition['name']
        found = True
        value = []
        for r in definition['registers']:
            index = r - start
            if (index >= 0) and (index < length):
                temp = rawData[index]
                value.append((temp))
            else:
                found = False

        if found:
            self.result[title] = value
        return

    def num_to_result(self, title, value):
        if self.is_integer_num(value):
            self.result[title] = int(value)
        else:   
            self.result[title] = round(value, FLOAT_ROUND_TO)

    def is_integer_num(self, n):
        if isinstance(n, int):
            return True
        if isinstance(n, float):
            return n.is_integer()
        return False
