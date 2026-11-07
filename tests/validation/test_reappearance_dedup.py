"""Conservative dedup must not share cooldowns between fresh tracks or revisits."""
import importlib.util
from pathlib import Path

PATH=Path(__file__).resolve().parents[2]/'validation/carla_e2e/single_set_filter_study/policies.py'


def gate(reset=True):
    assert PATH.exists(),'single-set comparison policy is missing'
    spec=importlib.util.spec_from_file_location('reappearance_policy',str(PATH))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m.ReappearanceDeduplicator(reset_on_gap=reset)


def test_nearby_new_track_always_gets_its_first_request():
    d=gate();box=[0,0,60,40]
    assert d.should_verify_target('cam',1,'blue',box,0.)[0]
    assert not d.should_verify_target('cam',1,'blue',box,.1)[0]
    assert d.should_verify_target('cam',2,'blue',box,.2)[0]


def test_gap_is_since_last_observation_not_last_request():
    d=gate();box=[0,0,60,40]
    assert d.should_verify_target('cam',1,'blue',box,0.)[0]
    for t in (.5,1.,1.5):assert not d.should_verify_target('cam',1,'blue',box,t)[0]
    assert d.should_verify_target('cam',1,'blue',box,2.51)==(True,'reappeared')


def test_track_only_control_keeps_legacy_cooldown():
    d=gate(False);box=[0,0,60,40]
    assert d.should_verify_target('cam',1,'blue',box,0.)[0]
    assert not d.should_verify_target('cam',1,'blue',box,2.)[0]
    assert d.should_verify_target('cam',1,'blue',box,30.1)[0]


def test_camera_and_changed_color_do_not_inherit_cooldown():
    d=gate();box=[0,0,60,40]
    assert d.should_verify_target('a',1,'blue',box,0.)[0]
    assert d.should_verify_target('b',1,'blue',box,.1)[0]
    assert d.should_verify_target('a',1,'red',box,.2)[0]


def test_zero_loss_comparison_uses_episode_identity_not_only_count():
    path=PATH.with_name('run.py')
    spec=importlib.util.spec_from_file_location('single_set_runner',str(path))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    scores=[dict(config='base',basis='detected',target=1,reached=1,actor=1,episode=0),
            dict(config='alternative',basis='detected',target=1,reached=1,actor=1,episode=1)]
    a=m.keys(scores,'base','detected');b=m.keys(scores,'alternative','detected')
    assert len(a)==len(b) and len(a-b)==1
    assert len(m.configurations())==31
