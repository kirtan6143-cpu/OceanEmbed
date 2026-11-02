"""Fast NumPy-only checks. Uses explicit in-memory NetCDF doubles for RAMA.
This does NOT replace pytest, real NetCDF tests, PyTorch checks or browser QA.
Run from the repository root: python scripts/check_core.py
"""
import ast
import csv
import glob
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from oceanembed.validation_contract import (qc_text, to_celsius, scalar_text,
    scheme_fingerprint, validate_matchup_payload, OBSERVATION_SCHEMA_VERSION)
from oceanembed.science import diagnostics, score, conformal

DEPTHS = np.array([0,5,10,20,30,50,75,100,125,150,200,300,500,700,1000])

class Variable:
    def __init__(self, values, dims=(), name="", attrs=None):
        self.values=np.asarray(values);self.dims=dims;self.name=name;self.attrs=attrs or {}
        self.size=self.values.size;self.sizes=dict(zip(dims,self.values.shape))
    def __getitem__(self,key): return self.values[key]
    def isel(self,selection,drop=False):
        index=tuple(selection.get(d,slice(None)) for d in self.dims)
        dims=tuple(d for d in self.dims if d not in selection)
        return Variable(self.values[index],dims,self.name,self.attrs)

class Dataset(dict):
    def __init__(self,*args,attrs=None,**kwargs):
        super().__init__(*args,**kwargs);self.attrs=attrs or {}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def __getattr__(self,key):return self[key]
    def load(self):return self

def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_json(path,obj):Path(path).write_text(json.dumps(obj,default=lambda x:x.item()))

class Checks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.registry={}
        path=ROOT/"src/oceanembed/rama.py"
        nodes=[n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)]
        self.ns={"np":np,"csv":csv,"glob":glob,"hashlib":hashlib,"Path":Path,
            "DEPTHS":DEPTHS,"HELD_OUT_SHARE":.5,"OBSERVATION_SCHEMA_VERSION":OBSERVATION_SCHEMA_VERSION,
            "scalar_text":scalar_text,"qc_text":qc_text,"to_celsius":to_celsius,"score":score,
            "sha256":file_hash,"dump":write_json,
            "xr":SimpleNamespace(open_dataset=lambda p:self.registry[str(p)])}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),"exec"),self.ns)
        self.input=self.root/"input.nc";self.input.write_bytes(b"explicit test double")
        self.ds=Dataset({
            "time":Variable(np.array(["2024-01-01","2024-01-02"],dtype="datetime64[ns]"),("time",)),
            "T":Variable([28.,29.],("time",),"T",{"units":"degC"}),
            "Q":Variable([1,1],("time",),"Q"),
            "lat":Variable(5.),"lon":Variable(90.)},attrs={"station":"RAMA-1"})
        self.registry[str(self.input)]=self.ds
        self.cfg={"reviewed":True,"path":str(self.input),"mooring_id_attr":"station",
            "lat_var":"lat","lon_var":"lon","depth_variable":{20:"T"},"qc_variable":{20:"Q"},"accepted_qc":[1]}
        self.out=self.root/"out.csv"
    def ingest(self):
        self.ns["rama_to_csv"](self.cfg,self.out)
        with self.out.open() as f:return list(csv.DictReader(f))
    def test_canonical_profile(self):
        z=np.arange(101.);r=diagnostics(z,30-.1*z)
        np.testing.assert_allclose([r["d26_m"],r["tchp_kj_cm2"],r["mld_t_m"]],[40,32.718,12])
    def test_conformal_rank(self):
        self.assertEqual(conformal(np.arange(1,20)[:,None])["q_degC"],18)
    def test_qc_types(self):
        for q in [b"1",np.bytes_("1"),"1",1,1.0]:self.assertEqual(qc_text(q),"1")
    def test_units(self):
        np.testing.assert_allclose(to_celsius([300.15],"K"),[27.])
        with self.assertRaises(ValueError):to_celsius([28.],None)
    def test_split_fingerprint(self):
        self.assertNotEqual(scheme_fingerprint(2,.2,.2),scheme_fingerprint(2,.1,.3))
        with self.assertRaises(ValueError):scheme_fingerprint(2,float("nan"),.2)
    def test_payload_rejects_old_schema(self):
        with self.assertRaises(ValueError):validate_matchup_payload({"source":"RAMA"},"RAMA")
    def test_byte_qc_in_adapter(self):
        self.ds["Q"]=Variable([b"1",b"4"],("time",),"Q")
        rows=self.ingest();self.assertEqual(len(rows),1);self.assertEqual(rows[0]["temperature"],"28.0")
    def test_kelvin_in_adapter(self):
        self.ds["T"]=Variable([300.15,301.15],("time",),"T",{"units":"kelvin"})
        self.assertAlmostEqual(float(self.ingest()[0]["temperature"]),27)
    def test_missing_units_rejected(self):
        self.ds["T"].attrs={}
        with self.assertRaises(ValueError):self.ingest()
    def test_missing_site_rejected(self):
        self.ds.attrs={}
        with self.assertRaisesRegex(ValueError,"stable mooring ID"):self.ingest()
    def test_missing_qc_rejected(self):
        del self.cfg["qc_variable"]
        with self.assertRaisesRegex(ValueError,"QC"):self.ingest()
    def test_extra_sensor_rejected(self):
        self.ds["T"]=Variable(np.ones((2,2)),("time","sensor"),"T",{"units":"degC"})
        with self.assertRaisesRegex(ValueError,"instrument"):self.ingest()
    def test_duplicate_subdaily_aggregation(self):
        self.ds["time"]=Variable(np.array(["2024-01-01T01:00","2024-01-01T13:00"],dtype="datetime64[ns]"),("time",))
        with self.assertRaisesRegex(ValueError,"Subdaily"):self.ingest()
        other=self.root/"second.nc";other.write_bytes(b"duplicate file");self.registry[str(other)]=self.ds
        self.cfg.update(path=str(self.root/"*.nc"),daily_reduction="mean")
        rows=self.ingest()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]["n_samples"],"2");self.assertEqual(rows[0]["temperature"],"28.5")
    def run_fixture(self, partition):
        run=self.root/"run.nc";run.write_bytes(b"model run double")
        self.registry[str(run)]=Dataset({
            "time":self.ds["time"],"lat":Variable([5.]),"lon":Variable([90.]),
            "temperature":Variable(np.ones((2,15,1,1))*28),
            "prior":Variable(np.ones((2,15,1,1))*27)},attrs={"source_mode":"research_blended","partition":partition})
        return run
    def test_matchup_contract(self):
        self.ingest();g=self.ns["mooring_group"]("RAMA-1")
        run=self.run_fixture("test" if g=="held_out" else "validation")
        result=self.ns["match"](run,self.out,self.root/"match.json",g)
        validate_matchup_payload(result,"RAMA")
        self.assertEqual(result["matchups"][0]["observed"],28.)
        self.assertEqual(result["matchups"][0]["predicted"],28.)
    def test_wrong_run_partition(self):
        self.ingest();run=self.run_fixture("train")
        with self.assertRaisesRegex(ValueError,"requires"):
            self.ns["match"](run,self.out,self.root/"match.json","held_out")

if __name__=="__main__":
    unittest.main(verbosity=2)

