import numpy as np
import xarray as xr

with xr.open_dataset("demo/runs/demo.nc") as f:
    ds = f.load()

date = "2023-01-05"
depth = 75.0
t = ds.time.values.astype("datetime64[D]")
idx = int(np.flatnonzero(t == np.datetime64(date))[0])
day = ds.isel(time=idx)

bathymetry = day.bathymetry.values
support_75 = day.support.sel(depth=depth).values.astype(bool)

ocean = bathymetry > 0
print("min bathymetry among supported cells:", float(bathymetry[support_75].min()) if support_75.any() else None)
print("max bathymetry among supported cells:", float(bathymetry[support_75].max()) if support_75.any() else None)
print("min bathymetry among ocean cells overall:", float(bathymetry[ocean].min()))
print("max bathymetry among ocean cells overall:", float(bathymetry[ocean].max()))
print()

for thresh in [75, 100, 125, 150, 200, 300, 500, 700, 902.3, 1000, 1200, 1500, 2000]:
    would_be_supported = ocean & (bathymetry >= thresh)
    print(f"cells with bathymetry >= {thresh}: {int(would_be_supported.sum())} (actual support count: {int(support_75.sum())})")

print()
print("is support constant across ALL 15 depths (i.e. truly a single static 2D mask, not per-depth)?")
all_depth_support = day.support.values.astype(bool)
same_every_depth = np.all(all_depth_support == all_depth_support[0], axis=0)
print("fraction of grid where support is identical at every depth:", float(np.mean(same_every_depth)))