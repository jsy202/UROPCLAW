"""No-temporal structure comparisons reuse existing recordings without VLM."""
import importlib.util
import sys
from pathlib import Path

PATH=Path(__file__).resolve().parents[2]/'validation/carla_e2e/temporal_filter_study/compare_no_temporal.py'


def load(monkeypatch):
    assert PATH.exists(),'no-temporal comparison is missing'
    monkeypatch.syspath_prepend(str(PATH.parent))
    spec=importlib.util.spec_from_file_location('no_temporal_structure',str(PATH))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_structure_matrix_covers_presence_and_valid_order_alternatives(monkeypatch):
    m=load(monkeypatch);configs=m.configurations()
    assert len(configs)==6 and len({c['name'] for c in configs})==6
    assert all(c['temporal'] is False for c in configs)
    assert {(c['hsv'],c['dedup']) for c in configs if c['family']=='presence'}=={(False,False),(False,True),(True,False),(True,True)}
    assert {c['architecture'] for c in configs}=={'current','early_hsv','late_hsv'}


def test_all_structure_variants_emit_first_observation_without_temporal(monkeypatch):
    m=load(monkeypatch)
    def forbidden(*args):raise AssertionError('temporal update is not allowed')
    monkeypatch.setattr(m.study.Confirm,'update',forbidden)
    for config in m.configurations():
        b=m.study.Branch(config)
        events=b.process([dict(bbox=[10,10,70,50],class_id=2,confidence=.9,color='blue')],0.)
        assert any(e['kind']=='request' for e in events)
