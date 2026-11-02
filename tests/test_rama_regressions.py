import csv
import numpy as np
import pytest
import xarray as xr
from oceanembed.rama import rama_to_csv
from oceanembed.contracts import save_nc

def fixture(tmp_path, units='degC', flags=None, times=None, stable_id=True):
    if times is None: times=np.array(['2024-01-01','2024-01-02'],dtype='datetime64[ns]')
    ds=xr.Dataset({'T':(('time',),[28.,29.],{'units':units}), 'Q':(('time',),[1,1] if flags is None else flags),
                   'lat':((),5.),'lon':((),90.)}, coords={'time':times}, attrs={'station':'fixed-site'} if stable_id else {})
    p=tmp_path/'input.nc';save_nc(ds,p)
    cfg={'reviewed':True,'path':str(p),'mooring_id_attr':'station','lat_var':'lat','lon_var':'lon',
         'depth_variable':{20:'T'},'qc_variable':{20:'Q'},'accepted_qc':[1]}
    return ds,p,cfg

def test_byte_qc_and_celsius_records(tmp_path):
    ds,p,cfg=fixture(tmp_path,flags=np.array([b'1',b'4'],dtype='S1'))
    out=tmp_path/'result.csv';assert rama_to_csv(cfg,out)==1
    r=list(csv.DictReader(out.open()))[0]
    assert float(r['temperature'])==28 and r['units']=='degC'

def test_kelvin_conversion_and_unit_rejection(tmp_path):
    ds,p,cfg=fixture(tmp_path,units='K');ds['T'].values[:]=[300.15,301.15];save_nc(ds,p)
    out=tmp_path/'result.csv';rama_to_csv(cfg,out)
    assert float(list(csv.DictReader(out.open()))[0]['temperature'])==pytest.approx(27)
    ds['T'].attrs.clear();save_nc(ds,p)
    with pytest.raises(ValueError,match='units'):rama_to_csv(cfg,out)

def test_missing_station_id_fails(tmp_path):
    ds,p,cfg=fixture(tmp_path,stable_id=False)
    with pytest.raises(ValueError,match='stable mooring ID'):rama_to_csv(cfg,tmp_path/'out.csv')

def test_subdaily_policy_and_duplicate_file_deduplication(tmp_path):
    times=np.array(['2024-01-01T01:00','2024-01-01T13:00'],dtype='datetime64[ns]')
    ds,p,cfg=fixture(tmp_path,times=times)
    with pytest.raises(ValueError,match='Subdaily'):rama_to_csv(cfg,tmp_path/'out.csv')
    save_nc(ds,tmp_path/'second.nc');cfg.update(path=str(tmp_path/'*.nc'),daily_reduction='mean')
    assert rama_to_csv(cfg,tmp_path/'out.csv')==1
    row=list(csv.DictReader((tmp_path/'out.csv').open()))[0]
    assert float(row['temperature'])==28.5 and int(row['n_samples'])==2

def test_missing_qc_and_extra_sensor_dimension_fail(tmp_path):
    ds,p,cfg=fixture(tmp_path);cfg.pop('qc_variable')
    with pytest.raises(ValueError,match='QC'):rama_to_csv(cfg,tmp_path/'out.csv')
    cfg['qc_variable']={20:'Q'}
    ds=ds.drop_vars('T');ds['T']=(('time','sensor'),np.ones((2,2)),{'units':'degC'});save_nc(ds,p)
    with pytest.raises(ValueError,match='instrument'):rama_to_csv(cfg,tmp_path/'out.csv')
