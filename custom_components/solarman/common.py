import os
import yaml
import struct
import asyncio
import aiofiles

from datetime import datetime, time

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac

from .const import *

def get_current_file_name(value):
    result = value.rsplit('.', 1)
    if len(result) > 0:
        return result[-1]
    return ""

async def async_execute(x):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, x)

async def async_listdir(path, prefix = ""):
    return sorted([prefix + f for f in await async_execute(lambda: os.listdir(path)) if os.path.isfile(path + f)]) if os.path.exists(path) else []

def execute_async(x):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(x)

def ensure_list(value):
    return value if isinstance(value, list) else [value]

def get_or_default(dict, key, default = None):
    return dict[key] if dict and key in dict else default

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

def all_same(values):
    return all(i == values[0] for i in values)

def group_when(iterable, predicate, max_size = REQUEST_MAX_SIZE):
    i, x, size = 0, 0, len(iterable)
    while i < size - 1:
        if predicate(iterable[i], iterable[i + 1]) or iterable[i + 1] - iterable[x] >= max_size:
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
    return f"{type(e).__name__}{f': {e}' if f'{e}' else ''}"

def Raise(exception) -> None:
    raise exception

def inherit_descriptions(item, group):
    if not REQUEST_UPDATE_INTERVAL in item and REQUEST_UPDATE_INTERVAL in group:
        item[REQUEST_UPDATE_INTERVAL] = group[REQUEST_UPDATE_INTERVAL]
    return item

def get_start_addr(data, register):
    for d in data:
        if d <= register < d + data[d][0]:
            return d
    return None

def get_addr_value(data, register):
    if (start := get_start_addr(data, register)) is None:
        return None

    return data[start][1][register - start]

def get_number(value, digits: int = -1):
    return int(value) if isinstance(value, int) or (isinstance(value, float) and value.is_integer()) else ((n if (n := round(value, digits)) and not n.is_integer() else int(n)) if digits > -1 else float(value))

def get_request_code(request):
    return request[REQUEST_CODE] if REQUEST_CODE in request else request[REQUEST_CODE_ALT]

def get_request_start(request):
    return request[REQUEST_START]

def get_request_end(request):
    return request[REQUEST_END]

def get_attr(dict, key, default = None):
    return value if key in dict and (value := dict[key]) else default

def get_battery_power_capacity(capacity, voltage):
    return capacity * voltage / 1000

def get_battery_cycles(charge, capacity, voltage):
    return charge / get_battery_power_capacity(capacity, voltage)

def get_dt_as_list_int(dt: datetime, long):
    return [(dt.year - 2000 << 8) + dt.month, (dt.day << 8) + dt.hour, (dt.minute << 8) + dt.second] if not long else [dt.year - 2000, dt.month, dt.day, dt.hour, dt.minute, dt.second]

def get_t_as_list_int(t: time, long):
    return [t.hour * 100 + t.minute,] if not long else [t.hour, t.minute]