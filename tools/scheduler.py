#
# Command: py scheduler.py {path} {span} {runtime}
# Example: py scheduler.py "..\custom_components\solarman\inverter_definitions\deye_sg04lp3.yaml" 25 0
# span:    Min span between registers to assume single request
# runtime: Runtime mod update_interval
#

import os
import sys
import yaml
import bisect

from typing import Any

def bulk_inherit(target: dict, source: dict, *keys: list):
    for k in source.keys() if len(keys) == 0 else source.keys() & keys:
        if not k in target and (v := source.get(k)) is not None:
            target[k] = v
    return target

def unwrap(source: dict, key: Any, mod: int = 0):
    if (c := source.get(key)) is not None and isinstance(c, list):
        source[key] = c[mod] if mod < len(c) else c[-1]
    return source

def entity_key(object: dict):
    return '_'.join(filter(None, (object["name"], object["platform"]))).lower().replace(' ', '_')

def enforce_parameters(source: dict, parameters: dict):
    return len((keys := source.keys() & parameters.keys())) == 0 or all(source[k] <= parameters[k] for k in keys)

def preprocess_descriptions(item, group, table, code, parameters):
    def modify(source: dict):
        for i in dict(source):
            if i in ("scale", "min", "max"):
                unwrap(source, i, parameters["mod"])
            if i == "registers" and source[i] and (isinstance(source[i], list) and isinstance(source[i][0], list)):
                unwrap(source, i, parameters["mod"])
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
                if enforce_parameters(s, parameters):
                    registers.extend(r)
                    if m := s.get("multiply"):
                        modify(m)
                        if m_r := m.get("registers"):
                            registers.extend(m_r)
                else:
                    s["registers"] = []

    g = dict(group)
    g.pop("items")
    bulk_inherit(item, g, *() if "registers" in item else "update_interval")

    if not "code" in item and (r := item.get("registers")) and (addr := min(r)) is not None:
        item["code"] = table.get(addr, code)

    if sensors := item.get("sensors"):
        for s in sensors:
            if s.get("registers"):
                bulk_inherit(s, item, "code", "scale")
                if m := s.get("multiply"):
                    bulk_inherit(m, s, "code", "scale")

    return item

def get_request_code(request):
    return request["code"] if "code" in request else request["mb_functioncode"]

def get_code(item, type, default = None):
    if "code" in item and (code := item["code"]):
        if isinstance(code, int):
            if type == "read":
                return code
        elif type in code:
            return code[type]
    return default

def all_same(values):
    return all(i == values[0] for i in values)

def group_when(iterable, predicate):
    i, x, size = 0, 0, len(iterable)
    while i < size - 1:
        #print(f"{iterable[i]} and {iterable[i + 1]} = {predicate(iterable[i], iterable[i + 1], iterable[x])}")
        if predicate(iterable[i], iterable[i + 1], iterable[x]):
            yield iterable[x:i + 1]
            x = i + 1
        i += 1
    yield iterable[x:size]

if __name__ == '__main__':

    if len(sys.argv) < 2:
        print("File not provided!")
        sys.exit()

    file = sys.argv[1]

    if not os.path.isfile(file):
        print("File does not exist!")
        sys.exit()

    span = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].lstrip('-').isnumeric() else 25

    runtime = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isnumeric() else 0

    with open(file) as f:
        profile = yaml.safe_load(f)

    _update_interval = 60
    _code = 0x00
    _max_size = 0
    if "default" in profile:
        default = profile["default"]
        _update_interval = default["update_interval"] if "update_interval" in default else 60
        _code = default["code"] if "code" in default else 0x03
        _max_size = default["max_size"] if "max_size" in default else 125

    table = {r: get_request_code(pr) for pr in profile["requests"] for r in range(pr["start"], pr["end"] + 1)} if "requests" in profile else {}

    parameters = {"mod": 0, "mppt": 2, "l": 3, "pack": 1}

    items = [i for i in sorted([preprocess_descriptions(item, group, table, _code, parameters) for group in profile["parameters"] for item in group["items"]], key = lambda x: (get_code(x, "read", _code), max(x["registers"])) if x.get("registers") else (-1, -1)) if enforce_parameters(i, parameters)]

    _is_single_code = False
    if (items_codes := [get_code(i, "read", _code) for i in items if "registers" in i]) and (is_single_code := all_same(items_codes)):
        _is_single_code = is_single_code
        _code = items_codes[0]

    registers = []

    for i in items:
        if "name" in i and "rule" in i and not "disabled" in i and i["rule"] > 0:
            if "realtime" in i or (runtime % (i["update_interval"] if "update_interval" in i else _update_interval) == 0):
                if "registers" in i:
                    print(f"{i["name"]}: {i["registers"]}")
                    if "sensors" in i:
                        print(i["sensors"])
                    for r in sorted(i["registers"]):
                        if (register := (get_code(i, "read"), r)) and not register in registers:
                            bisect.insort(registers, register)

    l = (lambda x, y: y - x > span) if span > -1 else (lambda x, y: False)

    _lambda = lambda x, y, z: l(x[1], y[1]) or y[1] - z[1] >= _max_size
    _lambda_code_aware = lambda x, y, z: x[0] != y[0] or _lambda(x, y, z)

    groups = group_when(registers, _lambda if _is_single_code or all_same([r[0] for r in registers]) else _lambda_code_aware)

    msg = ''

    for r in groups:
        if len(r) > 0:
            start = r[0][1]
            end = r[-1][1]
            dict = { "code": _code if _is_single_code else r[0][0], "start": start, "end": end, "len": end - start + 1 }
            msg += f'{dict}\n'

    print("")

    print(msg)
