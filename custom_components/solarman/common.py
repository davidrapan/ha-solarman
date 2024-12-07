from __future__ import annotations

import os
import re
import yaml
import logging
import asyncio
import aiofiles

import voluptuous as vol

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac

from .const import *

_LOGGER = logging.getLogger(__name__)

def protected(value, error):
    if value is None or not value:
        raise vol.Invalid(error)
    return value

def get_current_file_name(value):
    return result[-1] if len(result := value.rsplit('.', 1)) > 0 else ""

async def async_execute(x):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, x)

async def async_listdir(path, prefix = ""):
    return sorted([prefix + f for f in await async_execute(lambda: os.listdir(path)) if os.path.isfile(path + f)]) if os.path.exists(path) else []

def execute_async(x):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(x)

def filter_by_keys(source: dict, keys: dict | list) -> dict:
    return {k: source[k] for k in source.keys() if k in keys}

def bulk_inherit(target: dict, source: dict, *keys: list):
    for k in source.keys() & keys:
        if not k in target and (v := source.get(k)) is not None:
            target[k] = v
    return target

def bulk_migrate(target: dict, source: dict, redirect: dict):
    for k in redirect:
        if not k in target and (v := source.get(redirect[k])) is not None:
            target[k] = v
    return target

def bulk_delete(source: dict[Any, Any], *keys: list[Any]):
    for k in source.keys() & keys:
        del source[k]

def ensure_list(value):
    return value if isinstance(value, list) else [value]

def set_request(code, start, end):
    return { REQUEST_CODE: code, REQUEST_START: start, REQUEST_END: end }

def lookup_profile(response, attr):
    if response and (device_type := get_addr_value(response, *AUTODETECTION_TYPE_DEYE)):
        f, m, c = next(iter([AUTODETECTION_TABLE_DEYE[i] for i in AUTODETECTION_TABLE_DEYE if device_type in i]))
        if (v := get_addr_value(response, AUTODETECTION_CODE_DEYE, c)) and (t := (v & 0x0F00) // 0x100) and (p := v & 0x000F):
            attr[ATTR_MOD], attr[ATTR_MPPT], attr[ATTR_PHASE] = m, min(t, attr[ATTR_MPPT]), min(p, attr[ATTR_PHASE])
        return f
    raise Exception("Unable to read Device Type at Modbus register address: 0x0000")

async def yaml_open(file):
    async with aiofiles.open(file) as f:
        return yaml.safe_load(await f.read())

def process_profile(filename):
    return filename if not filename in PROFILE_REDIRECT_TABLE else PROFILE_REDIRECT_TABLE[filename]

def build_device_info(serial, mac, name, info, filename):
    manufacturer = "Solarman"
    model = "Stick Logger"

    if info and "model" in info:
        if "manufacturer" in info:
            manufacturer = info["manufacturer"]
        model = info["model"]
    elif '_' in filename and (dev_man := filename.replace(".yaml", "").split('_')):
        manufacturer = dev_man[0].capitalize()
        model = dev_man[1].upper()

    return ({ "connections": {(CONNECTION_NETWORK_MAC, format_mac(mac))} } if mac else {}) | {
        "identifiers": {(DOMAIN, serial)},
        "serial_number": serial,
        "manufacturer": manufacturer,
        "model": model,
        "name": name
    }

def is_platform(description, value):
    return (description["platform"] if "platform" in description else "sensor") == value

def all_equals(values, value):
    return all(i == value for i in values)

def all_same(values):
    return all(i == values[0] for i in values)

def group_when(iterable, predicate):
    i, x, size = 0, 0, len(iterable)
    while i < size - 1:
        if predicate(iterable[i], iterable[i + 1], iterable[x]):
            yield iterable[x:i + 1]
            x = i + 1
        i += 1
    yield iterable[x:size]

def is_ethernet_frame(frame):
    if frame[3:5] == CONTROL_CODE.REQUEST and (frame_len := len(frame)):
        if frame_len > 9:
            return int.from_bytes(frame[5:6], byteorder = "big") == len(frame[6:]) and int.from_bytes(frame[8:9], byteorder = "big") == len(frame[9:])
        if frame_len > 6: # [0xa5, 0x17, 0x00, 0x10, 0x45, 0x03, 0x00, 0x98, 0x02]
            return int.from_bytes(frame[5:6], byteorder = "big") == len(frame[6:])
    return False

def format_exception(e):
    return re.sub(r"\s+", " ", f"{type(e).__name__}{f': {e}' if f'{e}' else ''}")

def unwrap(source: dict, key: Any, mod: int = 0):
    if (c := source.get(key)) is not None and isinstance(c, list):
        source[key] = c[mod]
    return source

def process_descriptions(item, group, table, code, mod):
    def modify(source: dict):
        for i in source:
            if i in ("scale", "min", "max"):
                unwrap(source, i, mod)
            elif isinstance(source[i], dict):
                modify(source[i])

    bulk_inherit(item, group, *(REQUEST_UPDATE_INTERVAL, REQUEST_CODE) if "registers" in item else REQUEST_UPDATE_INTERVAL)
    if not REQUEST_CODE in item and (r := item.get("registers")) is not None and (addr := min(r)) is not None:
        item[REQUEST_CODE] = table.get(addr, code)
    modify(item)
    if (sensors := item.get("sensors")) is not None:
        for s in sensors:
            modify(s)
            bulk_inherit(s, item, REQUEST_CODE, "scale")
            if (m := s.get("multiply")) is not None:
                modify(m)
                bulk_inherit(m, s, REQUEST_CODE, "scale")
    return item

def get_code(item, type, default = None):
    if REQUEST_CODE in item and (code := item[REQUEST_CODE]):
        if isinstance(code, int):
            if type == "read":
                return code
        elif type in code:
            return code[type]
    return default

def get_start_addr(data, code, addr):
    for d in data:
        if d[0] == code and d[1] <= addr < d[1] + len(data[d]):
            return d
    return None

def get_addr_value(data, code, addr):
    if (start := get_start_addr(data, code, addr)) is None:
        return None
    return data[start][addr - start[1]]

def ilen(object):
    return len(object) if not isinstance(object, int) else 1

def get_or_def(o, k, d):
    return o.get(k, d) or d

def from_bit_index(value):
    if isinstance(value, list):
        return sum(1 << i for i in value)
    return 1 << value

def lookup_value(value, dictionary):
    default = dictionary[0]["value"]

    for o in dictionary:
        key = from_bit_index(o["bit"]) if "bit" in o else o["key"]

        if "default" in o or key == "default":
            default = o["value"]

        if key == value if not isinstance(key, list) else value in key:
            return o["value"]

    return default

def get_number(value, digits: int = -1):
    return int(value) if isinstance(value, int) or (isinstance(value, float) and value.is_integer()) else ((n if (n := round(value, digits)) and not n.is_integer() else int(n)) if digits > -1 else float(value))

def get_request_code(request):
    return request[REQUEST_CODE] if REQUEST_CODE in request else request[REQUEST_CODE_ALT]

def get_request_start(request):
    return request[REQUEST_START]

def get_request_end(request):
    return request[REQUEST_END]

def get_tuple(tuple, index = 0):
    return tuple[index] if tuple else None

def get_battery_power_capacity(capacity, voltage):
    return capacity * voltage / 1000

def get_battery_cycles(charge, capacity, voltage):
    return charge / get_battery_power_capacity(capacity, voltage)

def split_p16b(value):
    while value:
        yield value & 0xFFFF
        value = value >> 16

def div_mod(dividend, divisor):
    return (dividend // divisor, dividend % divisor)

def concat_hex(value):
    return int(f"0x{value[0]:02}{value[1]:02}", 16)
