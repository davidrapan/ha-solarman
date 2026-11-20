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

def test_declared_dependency_of_an_enabled_entity_is_kept(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("battery_power_sensor", "delta_sensor"), {"alpha_sensor": ("battery_power_sensor",)})
    assert registers(p) == [100, 200, 300, 500]

def test_declared_dependency_is_released_when_its_consumer_is_disabled(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("alpha_sensor", "battery_power_sensor"), {"alpha_sensor": ("battery_power_sensor",)})
    assert registers(p) == [200, 300, 400]

def test_reenabling_requests_again(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key == "alpha_sensor")
    p.set_disabled(lambda key: False)
    assert registers(p) == [100, 200, 300, 400, 500]

def test_all_disabled_requests_nothing(tmp_path):
    p = make(tmp_path)
    p.set_disabled(lambda key: key in ("alpha_sensor", "beta_sensor", "gamma_sensor", "delta_sensor"))
    assert registers(p) == [500]

def test_fine_control_profile_is_not_filtered(tmp_path):
    fine = PROFILE.replace("parameters:", """
requests_fine_control:
requests:
  - start: 100
    end: 500

parameters:""", 1)
    (tmp_path / "f.yaml").write_text(fine)
    p = asyncio.run(ParameterParser().init(str(tmp_path) + "/", "f.yaml", dict(PARAMETERS)))
    p.set_disabled(lambda key: True)
    assert p.skipped == []
    assert registers(p) == [100]
