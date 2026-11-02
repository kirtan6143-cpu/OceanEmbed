"""Unit-aware, QC-reviewed daily RAMA ingestion and mooring holdouts."""
import csv
import glob
import hashlib
from pathlib import Path
import numpy as np
import xarray as xr
from .contracts import DEPTHS, dump, sha256
from .science import score
from .validation_contract import OBSERVATION_SCHEMA_VERSION, scalar_text, qc_text, to_celsius

HELD_OUT_SHARE = .5


def mooring_group(mooring_id, held_out_share=HELD_OUT_SHARE, buckets=1000):
    if not isinstance(buckets, int) or buckets <= 0:
        raise ValueError('buckets must be a positive integer')
    if not np.isfinite(held_out_share) or not 0 < held_out_share < 1:
        raise ValueError('held_out_share must lie between zero and one')
    mid = scalar_text(mooring_id)
    if not mid or mid.lower() in {'none', 'nan', 'null'}:
        raise ValueError('Stable mooring ID required')
    b = int(hashlib.sha256(mid.encode()).hexdigest()[:8], 16) % buckets
    return 'held_out' if b < int(buckets * held_out_share) else 'development'


def _series(da, time_name, size):
    for dim in list(da.dims):
        if dim != time_name:
            if da.sizes[dim] != 1:
                raise ValueError(f'{da.name}: select instrument explicitly; extra dimension {dim}')
            da = da.isel({dim: 0}, drop=True)
    if da.dims != (time_name,) or da.size != size:
        raise ValueError(f'{da.name}: expected one-dimensional time series')
    return da.values


def _coordinate(da, name):
    a = np.asarray(da.values, float).ravel()
    if not len(a) or not np.isfinite(a).all() or not np.allclose(a, a[0], atol=1e-5, rtol=0):
        raise ValueError(f'{name}: expected finite fixed mooring coordinates')
    return float(a[0])


def rama_to_csv(spec, out):
    if not spec.get('reviewed'):
        raise ValueError('STOP 2: review RAMA mapping, units, stable IDs, timestamps and QC')
    depths = {float(z): var for z, var in spec['depth_variable'].items()}
    if not depths or not set(depths).issubset(set(DEPTHS)):
        raise ValueError('Use actual instrument depths matching contract depths; do not relabel nearby depths')
    time_name = spec.get('time_variable', 'time')
    daily = spec.get('daily_reduction', 'reject_subdaily')
    if daily not in {'mean', 'reject_subdaily'}:
        raise ValueError('daily_reduction must be mean or reject_subdaily')
    qc_map = {float(z): var for z, var in spec.get('qc_variable', {}).items()}
    accepted = {qc_text(q) for q in spec.get('accepted_qc', [])}
    note = str(spec.get('qc_review_note', '')).strip()
    if not qc_map and (not note or 'REPLACE' in note.upper()):
        raise ValueError('Explicit QC mapping or product-specific QC review note required')
    if qc_map and (set(qc_map) != set(depths) or not accepted):
        raise ValueError('QC mapping required for every depth with nonempty accepted_qc')
    paths = sorted(glob.glob(spec['path'], recursive=True))
    if not paths:
        raise FileNotFoundError(spec['path'])
    records, positions, sources = {}, {}, []
    duplicates = 0
    for path in paths:
        with xr.open_dataset(path) as ds:
            if bool(spec.get('mooring_id_attr')) == bool(spec.get('mooring_id_variable')):
                raise ValueError('Specify exactly one stable mooring_id_attr or mooring_id_variable')
            if spec.get('mooring_id_attr'):
                raw_id = ds.attrs.get(spec['mooring_id_attr'])
            else:
                var = spec['mooring_id_variable']
                raw_id = ds[var].values.item() if var in ds and ds[var].size == 1 else None
            mid = scalar_text(raw_id) if raw_id is not None else ''
            if not mid or mid.lower() in {'none', 'nan', 'null'} or 'REPLACE' in mid.upper():
                raise ValueError(f'{path}: missing stable mooring ID; filenames are not station IDs')
            lat = _coordinate(ds[spec['lat_var']], 'latitude')
            lon = (_coordinate(ds[spec['lon_var']], 'longitude') + 180) % 360 - 180
            if not -90 <= lat <= 90:
                raise ValueError('Latitude outside [-90, 90]')
            if mid in positions and not np.allclose(positions[mid], [lat, lon], atol=1e-4, rtol=0):
                raise ValueError(f'{mid}: inconsistent site coordinates across files')
            positions[mid] = [lat, lon]
            raw_times = ds[time_name].values
            if raw_times.ndim != 1 or not np.issubdtype(raw_times.dtype, np.datetime64):
                raise ValueError('Decoded one-dimensional datetime coordinate required')
            times = raw_times.astype('datetime64[ns]')
            if np.isnat(times).any():
                raise ValueError('NaT in RAMA timestamps')
            source_units = {}
            for depth, var in depths.items():
                if var not in ds:
                    raise ValueError(f'Declared temperature variable missing: {var}')
                units = ds[var].attrs.get('units')
                values = _series(ds[var], time_name, len(times)).astype(float)
                if qc_map:
                    qvar = qc_map[depth]
                    if qvar not in ds:
                        raise ValueError(f'Declared QC variable missing: {qvar}')
                    flags = _series(ds[qvar], time_name, len(times))
                    valid = np.array([qc_text(q) in accepted for q in flags])
                else:
                    valid = np.ones(len(times), dtype=bool)
                to_celsius([], units)  # check units even if every record fails QC
                values = to_celsius(np.where(valid, values, np.nan), units)
                source_units[var] = str(units)
                for timestamp, value in zip(times, values):
                    if not np.isfinite(value):
                        continue
                    key = (mid, str(timestamp), depth)
                    if key in records:
                        if not np.isclose(records[key], value, atol=1e-6, rtol=0):
                            raise ValueError(f'Conflicting duplicate RAMA observation: {key}')
                        duplicates += 1
                    records[key] = float(value)
            sources.append({'path': str(path), 'sha256': sha256(path), 'temperature_units': source_units})
    daily_records = {}
    for (mid, timestamp, depth), value in records.items():
        daily_records.setdefault((mid, timestamp[:10], depth), []).append(value)
    rows = []
    for (mid, day, depth), values in sorted(daily_records.items()):
        if len(values) > 1 and daily != 'mean':
            raise ValueError('Subdaily measurements found; explicitly review daily_reduction: mean')
        lat, lon = positions[mid]
        rows.append({'mooring_id': mid, 'date': day, 'lat': lat, 'lon': lon, 'depth': depth,
                     'temperature': float(np.mean(values)), 'units': 'degC', 'n_samples': len(values)})
    if not rows:
        raise ValueError('No QC-approved RAMA records found')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    dump(Path(out).with_suffix('.sources.json'), {'observation_schema_version': OBSERVATION_SCHEMA_VERSION,
         'spec': spec, 'files': sources, 'duplicate_records_removed': duplicates, 'daily_records': len(rows)})
    return len(rows)


def match(run_path, csv_path, out, group, max_km=30, max_days=0):
    if group not in ('development', 'held_out'):
        raise ValueError('Use development or held_out')
    with xr.open_dataset(run_path) as f:
        ds = f.load()
    if ds.attrs.get('source_mode') == 'synthetic':
        raise ValueError('Real observations cannot validate synthetic runs')
    expected = 'test' if group == 'held_out' else 'validation'
    if ds.attrs.get('partition') != expected:
        raise ValueError(f'{group} RAMA requires a {expected} run')
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    matches, seen = [], set()
    times = ds.time.values.astype('datetime64[D]')
    for row in rows:
        if row.get('units') != 'degC':
            raise ValueError('Regenerate RAMA CSV with declared Celsius units')
        mid = row['mooring_id'].strip()
        if mooring_group(mid) != group:
            continue
        lat, lon, z, observed = [float(row[k]) for k in ['lat', 'lon', 'depth', 'temperature']]
        if not np.isfinite([lat, lon, z, observed]).all():
            raise ValueError('Nonfinite RAMA observation')
        key = (mid, row['date'], z)
        if key in seen:
            raise ValueError('Duplicate station/date/depth in RAMA CSV; regenerate daily records')
        seen.add(key)
        date = np.datetime64(row['date'], 'D')
        if np.isnat(date):
            raise ValueError('Invalid RAMA date')
        ti = int(np.argmin(abs(times-date)))
        if abs((times[ti]-date).astype(int)) > max_days:
            continue
        lon = (lon+180)%360-180
        yi = int(np.argmin(abs(ds.lat.values-lat))); xi = int(np.argmin(abs(ds.lon.values-lon)))
        a,b = np.deg2rad([lat,float(ds.lat[yi])]); dl = np.deg2rad(float(ds.lon[xi])-lon)
        h = np.sin((b-a)/2)**2 + np.cos(a)*np.cos(b)*np.sin(dl/2)**2
        km = float(6371*2*np.arcsin(np.sqrt(np.clip(h,0,1))))
        if km > max_km:
            continue
        zi = np.flatnonzero(DEPTHS==z)
        if not len(zi):
            raise ValueError('Unsupported observation depth')
        prediction = float(ds.temperature.values[ti,zi[0],yi,xi])
        if np.isfinite(prediction):
            prior = float(ds.prior.values[ti,zi[0],yi,xi]) if 'prior' in ds else None
            matches.append({**row, 'depth': z, 'observed': observed, 'predicted': prediction,
                            'prior': prior, 'distance_km': km, 'matched_date': str(times[ti])})
    if not matches:
        raise ValueError('No supported RAMA matchups; check bounds, dates and group')
    metrics = []
    for z in sorted({r['depth'] for r in matches}):
        m = [r for r in matches if r['depth']==z]
        metrics.append({'depth': z, 'model': score([r['observed'] for r in m],[r['predicted'] for r in m]),
                        'climatology': score([r['observed'] for r in m],[r['prior'] for r in m])})
    result = {'source': 'RAMA', 'group': group, 'partition': ds.attrs['partition'],
              'observation_schema_version': OBSERVATION_SCHEMA_VERSION, 'metrics': metrics, 'matchups': matches,
              'mooring_ids': sorted({r['mooring_id'] for r in matches}), 'run_sha256': sha256(run_path),
              'observations_sha256': sha256(csv_path), 'units': 'degC',
              'note': 'Daily QC-approved RAMA matchups at fixed sites; temporal context, not spatial coverage or interval calibration.'}
    dump(out, result)
    return result
