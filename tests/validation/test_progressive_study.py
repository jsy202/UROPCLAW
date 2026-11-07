import importlib.util
from pathlib import Path

PATH=Path(__file__).resolve().parents[2]/'validation/carla_e2e/progressive_filter_study/analyze_progressive.py'


def load():
    spec=importlib.util.spec_from_file_location('progressive_study',str(PATH))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_progressive_matrix_and_schedule():
    m=load();configs=m.configurations()
    assert len(configs)==28 and len({c['name'] for c in configs})==28
    assert len(m.expected_cells())==30
    rows={c['name']:c for c in configs}
    assert not rows['factor_000']['hsv'] and not rows['factor_000']['dedup']
    assert rows['factor_100']['hsv'] and not rows['factor_100']['dedup']
    assert rows['factor_101']['hsv'] and rows['factor_101']['dedup'] and not rows['factor_101']['temporal']
    assert rows['factor_111']['temporal']
    assert all(not rows[name]['temporal'] for name in ['no_temporal_early_hsv','no_temporal_late_hsv'])


def test_temporal_decision_uses_frozen_selection_not_only_n3():
    m=load()
    rows={'factor_101':dict(requests='100'),'n2_dedup':dict(requests='90',confirm_p95_s='.3'),
          'n3_dedup':dict(requests='80',confirm_p95_s='.7')}
    cis={'n2_dedup':dict(recall_diff_ci_low='-.01'),'n3_dedup':dict(recall_diff_ci_low='-.05')}
    assert m.temporal_validated(rows,cis,'n2_dedup') is True
    assert m.temporal_validated(rows,cis,'n3_dedup') is False
    assert m.temporal_validated(rows,cis,'n1_dedup') is False
    assert m.temporal_validated(rows,cis,None) is False


def test_thirty_recording_schedule_accepts_only_the_approved_map(tmp_path):
    import json
    import itertools
    import pytest
    m=load()
    cells=itertools.product(('Town10HD_Opt',),('clear','low_sun','rain'),(30,70),(101,102,201,202,203))
    for town,weather,vehicles,seed in cells:
        directory=tmp_path/'runs'/('%s_%s_v%d_s%d'%(town,weather,vehicles,seed))
        directory.mkdir(parents=True)
        manifest=dict(map=town,weather=weather,vehicles=vehicles,seed=seed,status='COMPLETE',
                      frames=6000,duration_s=600,dt_s=.1,split='dev' if seed<200 else 'test')
        (directory/'manifest.json').write_text(json.dumps(manifest))
    assert len(m.validate_schedule(tmp_path))==30
    extra=tmp_path/'runs/extra'
    extra.mkdir()
    manifest.update(map='Town03_Opt',seed=101,split='dev')
    (extra/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='missing or duplicate'):
        m.validate_schedule(tmp_path)
