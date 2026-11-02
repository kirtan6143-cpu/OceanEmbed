import numpy as np
import pytest
from oceanembed.validation_contract import qc_text, to_celsius, scheme_fingerprint, validate_matchup_payload

@pytest.mark.parametrize('flag', [b'1',np.bytes_('1'),'1',1,1.0])
def test_qc_decodes_consistently(flag):
    assert qc_text(flag)=='1'

def test_kelvin_and_missing_units():
    np.testing.assert_allclose(to_celsius([300.15], 'kelvin'), [27.])
    with pytest.raises(ValueError): to_celsius([300], None)

def test_split_fingerprint_includes_actual_shares():
    assert scheme_fingerprint(2,.2,.2)!=scheme_fingerprint(2,.1,.3)
    with pytest.raises(ValueError): scheme_fingerprint(2,float('nan'),.2)
    with pytest.raises(ValueError): scheme_fingerprint(2,.2,.2,0)

def test_legacy_matchups_rejected():
    with pytest.raises(ValueError,match='schema'):
        validate_matchup_payload({'source':'RAMA','matchups':[]}, 'RAMA')
    obj={'source':'RAMA','observation_schema_version':2,'matchups':[{'depth':20.,'observed':27.,'predicted':27.4}]}
    assert validate_matchup_payload(obj,'RAMA') is obj
