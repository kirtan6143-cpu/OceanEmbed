import json
import pytest
import yaml
from oceanembed.baseline import select, evaluate
from oceanembed.demo import create
from oceanembed.products import attach_intervals
from oceanembed.observations import PARTITION_SCHEME_VERSION

def test_frozen_baseline_rejects_changed_config_or_files(tmp_path):
    cube=tmp_path/'cube.nc';create(cube)
    cfg=yaml.safe_load(open('configs/smoke.yaml'));cfg['cube']=str(cube)
    ridge=tmp_path/'ridge';select(cfg,ridge)
    changed=dict(cfg);changed['max_age_hours']=120
    with pytest.raises(ValueError,match='config/data'):
        evaluate(changed,ridge,tmp_path/'report')
    with (ridge/'ridge.npz').open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='checksum'):
        evaluate(cfg,ridge,tmp_path/'report')

@pytest.mark.parametrize('key',['model_fingerprint','partition_fingerprint'])
def test_interval_fingerprint_mismatch_rejected_before_loading_run(tmp_path,key):
    common={'partition_scheme_version':PARTITION_SCHEME_VERSION,'model_fingerprint':'model-a','partition_fingerprint':'split-a'}
    cal=dict(common);test={**common,'source':'Argo','partition':'test'}
    test[key]='different'
    a=tmp_path/'cal.json';b=tmp_path/'test.json';a.write_text(json.dumps(cal));b.write_text(json.dumps(test))
    with pytest.raises(ValueError,match=key):
        attach_intervals(tmp_path/'not-opened.nc',a,b,tmp_path/'out.nc')
