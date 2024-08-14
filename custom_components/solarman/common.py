import os
import yaml
import asyncio
import aiofiles

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

async def yaml_open(file):
    async with aiofiles.open(file) as f:
        return yaml.safe_load(await f.read())

def all_same(values):
    return all(i == values[0] for i in values)

def group_when(iterable, predicate):
    i, x, size = 0, 0, len(iterable)
    while i < size - 1:
        if predicate(iterable[i], iterable[i + 1]):
            yield iterable[x:i + 1]
            x = i + 1
        i += 1
    yield iterable[x:size]

def format_exception(e):
    return f"{type(e).__name__}{f': {e}' if f'{e}' else ''}"

def Raise(exception) -> None:
    raise exception

def get_number(value, digits: int = -1):
    return int(value) if isinstance(value, int) or (isinstance(value, float) and value.is_integer()) else ((n if (n := round(value, digits)) and not n.is_integer() else int(n)) if digits > -1 else float(value))

def get_request_code(request):
    return request[REQUEST_CODE] if REQUEST_CODE in request else request[REQUEST_CODE_ALT]

def get_request_start(request):
    return request[REQUEST_START]

def get_request_end(request):
    return request[REQUEST_END]

def get_battery_power_capacity(capacity, voltage):
    return capacity * voltage / 1000

def get_battery_cycles(charge, capacity, voltage):
    return charge / get_battery_power_capacity(capacity, voltage)
