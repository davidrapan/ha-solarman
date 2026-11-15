import asyncio

from solarman.parser import ParameterParser

PROFILE = """
default:
  update_interval: 10
  code: 0x04
  min_span: -1
  max_size: 100

parameters:
  - group: Test
    items:
      - name: "Alpha"
        rule: 1
        registers: [100]
      - name: "Beta"
        rule: 1
        registers: [200]
        attributes: ["Gamma"]
      - name: "Gamma"
        rule: 1
        registers: [300]
      - name: "Delta"
        rule: 1
        registers: [400]
      - name: "Battery Power"
        rule: 1
        registers: [500]
"""

PARAMETERS = {"mod": 0, "mppt": 4, "l": 3, "pack": -1}

def make(tmp_path):
    (tmp_path / "t.yaml").write_text(PROFILE)
    return asyncio.run(ParameterParser().init(str(tmp_path) + "/", "t.yaml", dict(PARAMETERS)))

def registers(p, runtime = 0):
    return sorted(r["start"] for r in p.schedule_requests(runtime))

def test_everything_is_requested_by_default(tmp_path):
    assert registers(make(tmp_path)) == [100, 200, 300, 400, 500]

def test_disabled_entities_are_not_requested(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("alpha_sensor", "delta_sensor"))
    assert registers(p) == [200, 300, 500]
    assert p.skipped == ["alpha_sensor", "delta_sensor"]

def test_disabled_entity_used_as_attribute_of_enabled_one_is_still_requested(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("gamma_sensor", "delta_sensor"))
    assert registers(p) == [100, 200, 300, 500]

def test_dependency_is_released_when_its_parent_is_disabled_too(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("beta_sensor", "gamma_sensor"))
    assert registers(p) == [100, 400, 500]

def test_entities_used_by_computed_sensors_are_kept(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key == "battery_power_sensor")
    assert 500 in registers(p)

def test_reenabling_requests_again(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key == "alpha_sensor")
    p.set_disabled(lambda key: False)
    assert registers(p) == [100, 200, 300, 400, 500]

def test_all_disabled_requests_nothing(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("alpha_sensor", "beta_sensor", "gamma_sensor", "delta_sensor"))
    assert registers(p) == [500]
