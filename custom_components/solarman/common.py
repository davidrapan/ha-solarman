from __future__ import annotations

import os
import ast
import time
import yaml
import logging
import asyncio
import aiofiles

import voluptuous as vol

from typing import Any
from functools import wraps

from homeassistant.util import slugify
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac

from .const import *

_LOGGER = logging.getLogger(__name__)

def retry(ignore: tuple = ()):
    def decorator(f):
        @wraps(f)
        async def wrapper(*args, **kwargs):
            try:
                return await f(*args, **kwargs)
            except ignore:
                raise
            except Exception:
                return await f(*args, **kwargs)
        return wrapper
    return decorator

def throttle(delay: float = 1):
    def decorator(f):
        l = [0]
        @wraps(f)
        async def wrapper(*args, **kwargs):
            if (d := delay - (time.time() - l[0])) > 0:
                await asyncio.sleep(d)
            l[0] = time.time()
            return await f(*args, **kwargs)
        return wrapper
    return decorator

async def async_execute(x):
    return await asyncio.get_running_loop().run_in_executor(None, x)

def create_task(coro, *, name=None, context=None):
    return asyncio.get_running_loop().create_task(coro, name = name, context = context)

def protected(value, error):
    if value is None:
        raise vol.Invalid(error)
    return value

def get_current_file_name(value):
    return result[-1] if len(result := value.rsplit('.', 1)) > 0 else ""

async def async_listdir(path, prefix = ""):
    return sorted([prefix + f for f in await async_execute(lambda: os.listdir(path)) if os.path.isfile(path + f)]) if os.path.exists(path) else []

def to_dict(*keys: list):
    return {k: k for k in keys}

def filter_by_keys(source: dict, keys: dict | list) -> dict:
    return {k: source[k] for k in source.keys() if k in keys}

def bulk_inherit(target: dict, source: dict, *keys: list):
    for k in source.keys() if len(keys) == 0 else source.keys() & keys:
        if not k in target and (v := source.get(k)) is not None:
            target[k] = v
    return target

def bulk_migrate(target: dict, source: dict, redirect: dict):
    for k in redirect:
        if not k in target and (v := source.get(redirect[k])) is not None:
            target[k] = v
    return target

def bulk_delete(target: dict[Any, Any], *keys: list[Any]):
    for k in target.keys() & keys:
        del target[k]

def bulk_safe_delete(target: dict[Any, Any], redirect: dict):
    for k in target.keys() & redirect.keys():
        if redirect[k] in target:
            del target[redirect[k]]

def ensure_list(value):
    return value if isinstance(value, list) else [value]

def ensure_list_safe_len(value: list):
    return ensure_list(value), len(value) if isinstance(value, list) else (1 if isinstance(value, dict) and value else 0)

def create_request(code, start, end):
    return { REQUEST_CODE: code, REQUEST_START: start, REQUEST_END: end, REQUEST_COUNT: end - start + 1 }

async def lookup_profile(request, parameters):
    if (response := await request("?", create_request(*AUTODETECTION_REQUEST_DEYE))) and (device_type := get_addr_value(response, *AUTODETECTION_DEVICE_DEYE)):
        f, m, c = next(iter([AUTODETECTION_DEYE[i] for i in AUTODETECTION_DEYE if device_type in i]))
        if (t := get_addr_value(response, *AUTODETECTION_TYPE_DEYE)) and device_type in AUTODETECTION_DEYE_P1[0]:
            parameters[PARAM_[CONF_PHASE]] = min(1 if t <= 2 or t == 8 else 3, parameters[PARAM_[CONF_PHASE]])
        if (v := get_addr_value(response, AUTODETECTION_CODE_DEYE, c)) and (t := (v & 0x0F00) // 0x100) and (p := v & 0x000F) and (t := 2 if t > 12 else t) and (p := 3 if p > 3 else p):
            parameters[PARAM_[CONF_MOD]], parameters[PARAM_[CONF_MPPT]], parameters[PARAM_[CONF_PHASE]] = max(m, parameters[PARAM_[CONF_MOD]]), min(t, parameters[PARAM_[CONF_MPPT]]), min(p, parameters[PARAM_[CONF_PHASE]])
        if device_type in (*AUTODETECTION_DEYE_4P3[0], *AUTODETECTION_DEYE_1P3[0]) and (response := await request("?", create_request(*AUTODETECTION_BATTERY_REQUEST_DEYE))) and (p := get_addr_value(response, *AUTODETECTION_BATTERY_NUMBER_DEYE)) is not None:
            parameters[PARAM_[CONF_PACK]] = p if parameters[PARAM_[CONF_PACK]] == DEFAULT_[CONF_PACK] else min(p, parameters[PARAM_[CONF_PACK]])
        return f
    raise Exception("Unable to read Device Type at address 0x0000")

def process_profile(filename, parameters):
    if filename in PROFILE_REDIRECT and (r := PROFILE_REDIRECT[filename]):
        if ':' not in r:
            return r
        if (s := r.split(':')):
            for a in s[1].split('&'):
                if (p := a.split('=')) and len(p) == 2:
                    parameters[p[0]] = ast.literal_eval(p[1])
            return s[0]
    return filename

async def yaml_open(file):
    async with aiofiles.open(file) as f:
        return yaml.safe_load(await f.read())

def build_device_info(entry_id, serial, mac, host, info, name):
    device_info = DeviceInfo()
    manufacturer = "Solarman"
    model = "Stick Logger"

    if info:
        if "model" in info:
            if "manufacturer" in info:
                manufacturer = info["manufacturer"]
            model = info["model"]
        elif (filename := info.get("filename")) is not None and '_' in filename and (dev_man := filename.replace(".yaml", "").split('_')):
            manufacturer = dev_man[0].capitalize()
            model = dev_man[1].upper()

    device_info["identifiers"] = ({(DOMAIN, entry_id)} if entry_id else set()) | ({(DOMAIN, serial)} if serial else set())
    device_info["connections"] = {(CONNECTION_NETWORK_MAC, format_mac(mac))} if mac else set()
    device_info["configuration_url"] = f"http://{host}/config_hide.html" if host else None
    device_info["serial_number"] = serial if serial else None
    device_info["manufacturer"] = manufacturer
    device_info["model"] = model
    device_info["name"] = name

    return device_info

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

def format(value):
    return value if not isinstance(value, (bytes, bytearray)) else value.hex(" ")

def strepr(value):
    return s if (s := str(value)) else repr(value)

def unwrap(source: dict, key: Any, mod: int = 0):
    if (c := source.get(key)) is not None and isinstance(c, list):
        source[key] = c[mod] if mod < len(c) else c[-1]
    return source

def entity_key(object: dict):
    return slugify('_'.join(filter(None, (object["name"], object["platform"]))))

def preprocess_descriptions(item, group, table, code, parameters):
    def modify(source: dict):
        for i in dict(source):
            if i in ("scale", "min", "max"):
                unwrap(source, i, parameters[CONF_MOD])
            if i == "registers" and source[i] and (isinstance(source[i], list) and isinstance(source[i][0], list)):
                unwrap(source, i, parameters[CONF_MOD])
                if not source[i]:
                    source["disabled"] = True
            elif isinstance(source[i], dict):
                modify(source[i])

    if not "platform" in item:
        item["platform"] = "sensor" if not "configurable" in item else "number"

    item["key"] = entity_key(item)

    modify(item)

    if (sensors := item.get("sensors")) and (registers := item.setdefault("registers", [])) is not None:
        registers.clear()
        for s in sensors:
            modify(s)
            if r := s.get("registers"):
                registers.extend(r)
                if m := s.get("multiply"):
                    modify(m)
                    if m_r := m.get("registers"):
                        registers.extend(m_r)

    g = dict(group)
    g.pop("items")
    bulk_inherit(item, g, *() if "registers" in item else REQUEST_UPDATE_INTERVAL)

    if not REQUEST_CODE in item and (r := item.get("registers")) and (addr := min(r)) is not None:
        item[REQUEST_CODE] = table.get(addr, code)

    if sensors := item.get("sensors"):
        for s in sensors:
            bulk_inherit(s, item, REQUEST_CODE, "scale")
            if m := s.get("multiply"):
                bulk_inherit(m, s, REQUEST_CODE, "scale")

    return item

def postprocess_descriptions(coordinator, platform):
    def not_enabled(description):
        return (l := description.get("enabled_lookup")) is not None and (k := list(l)[0]) is not None and (v := coordinator.data.get(k)) is not None and not get_tuple(v) in l[k]

    descriptions = coordinator.device.profile.parser.get_entity_descriptions(platform)

    _LOGGER.debug(f"postprocess_descriptions for {platform} platform: {descriptions}")

    for description in descriptions:
        if not_enabled(description):
            continue
        
        if (nlookup := description.get("name_lookup")) is not None and (prefix := coordinator.data.get(nlookup)) is not None:
            description["name"] = replace_first(description["name"], get_tuple(prefix))
            description["key"] = entity_key(description)

        if (sensors := description.get("sensors")) is not None:
            for sensor in list(sensors):
                if not_enabled(sensor):
                    sensors.remove(sensor)

        yield description

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

def replace_first(object: str, newvalue, separator: str = ' '):
    return separator.join(filter(None, (newvalue, str(parts[1] if (parts := object.split(separator, 1)) and len(parts) > 1 else ''))))

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

        if o.get("mode") == "single" and value & key == key:
            key = value
    
        if "default" in o or key == "default":
            default = o["value"]

        if key == value if not isinstance(key, list) else value in key:
            return o["value"]

    return default

def get_number(value, digits: int = -1):
    return int(value) if isinstance(value, int) or (isinstance(value, float) and value.is_integer()) else ((n if (n := round(value, digits)) and not n.is_integer() else int(n)) if digits > -1 else float(value))

def get_request_code(request):
    return request[REQUEST_CODE] if REQUEST_CODE in request else request[REQUEST_CODE_ALT]

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
