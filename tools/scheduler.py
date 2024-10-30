#
# Command: py scheduler.py {path} {span} {runtime}
# Example: py scheduler.py "..\custom_components\solarman\inverter_definitions\deye_sg04lp3.yaml" 25 0
# span:    Min span between registers to assume single request
# runtime: Runtime mod update_interval
#

import os
import sys
import yaml

def get_request_code(request):
    return request["code"] if "code" in request else request["mb_functioncode"]

def inherit_descriptions(item, group):
    if not "update_interval" in item and "update_interval" in group:
        item["update_interval"] = group["update_interval"]
    if not "code" in item and "code" in group:
        item["code"] = group["code"]
    return item

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
        #print(f"{iterable[i]} and {iterable[i + 1]} = {predicate(iterable[i], iterable[i + 1], iterable[x])} or {iterable[i + 1] - iterable[x]}")
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
    
    items = [inherit_descriptions(item, group) for group in profile["parameters"] for item in group["items"]]

    _update_interval = 60
    _code = 0x00
    if "default" in profile:
        default = profile["default"]
        _update_interval = default["update_interval"] if "update_interval" in default else 60
        _code = default["code"] if "code" in default else 0x03

    requests_table = {}

    if "requests" in profile:
        for pr in profile["requests"]:
            for r in range(pr["start"], pr["end"] + 1):
                requests_table[r] = get_request_code(pr)

    registers = []
    registers_table = {}

    for i in items:
        if "registers" in i:
            for r in i["registers"]:
                if "name" in i and "rule" in i and not "disabled" in i and i["rule"] > 0:
                    if "realtime" in i or (runtime % (i["update_interval"] if "update_interval" in i else _update_interval) == 0):
                        registers.append(r)
                registers_table[r] = get_code(i, "read", requests_table[r] if r in requests_table else _code)

    registers.sort()

    _is_single_code = False
    if (registers_table_values := registers_table.values()) and (is_single_code := all_same(list(registers_table_values))):
        _is_single_code = is_single_code
        _code = next(iter(registers_table_values))

    l = (lambda x, y: y - x > span) if span > -1 else (lambda x, y: False)

    _lambda = lambda x, y, z: l(x, y) or y - z >= 125
    _lambda_code_aware = lambda x, y, z: registers_table[x] != registers_table[y] or _lambda(x, y, z)

    groups = group_when(registers, _lambda if _is_single_code or all_same([registers_table[r] for r in registers]) else _lambda_code_aware)

    msg = ''

    for r in groups:
        if len(r) > 0:
            dict = { "start": r[0], "end": r[-1], "code": _code if _is_single_code else registers_table[r[0]] }
            msg += f'{dict}\n'

    print(msg)