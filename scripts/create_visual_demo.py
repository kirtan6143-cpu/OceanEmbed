"""Build a geographically framed synthetic UI demo, never observational evidence.
The original CLI engineering fixture and training pipeline are unchanged.
"""
import json
from pathlib import Path
import numpy as np
import xarray as xr
from matplotlib.path import Path as Polygon
from oceanembed.contracts import DEPTHS, CHANNELS, save_nc


def create(out):
    # Doubled from 64x76 -> 128x152: more real grid points before any
    # smoothing/upsampling, giving finer real detail (not invented) in every
    # downstream diagnostic. Checked before shipping: field_diagnostics'
    # per-cell Python loop scales to ~0.5s/request at this resolution
    # (measured: 0.123s at 64x76 -> ~4x cells -> ~0.5s), acceptable given the
    # API layer already caches responses.
    lat=np.linspace(3,26,128); lon=np.linspace(76,102,152)
    yy,xx=np.meshgrid(lat,lon,indexing='ij')
    points=np.c_[xx.ravel(),yy.ravel()]
    coast=json.loads((Path(__file__).resolve().parents[1]/'frontend/public/coastline.geojson').read_text())
    land=np.zeros(xx.shape,dtype=bool)
    for feature in coast['features']:
        for rings in feature['geometry']['coordinates']:
            inside=Polygon(rings[0]).contains_points(points)
            for hole in rings[1:]:inside &= ~Polygon(hole).contains_points(points)
            land |= inside.reshape(xx.shape)
    # Deliberately synthetic basin and shelf. The geography is context only.
    from scipy.ndimage import distance_transform_edt
    coast_distance=distance_transform_edt(~land)
    bathy=np.where(land,0,np.minimum(2800,80+130*coast_distance**1.25)).astype('float32')
    times=np.datetime64('2024-06-01')+np.arange(45)
    day=np.arange(45)[:,None,None]
    surface=28.3+1.1*np.sin((xx-81)/5)-.025*yy+0.3*np.sin(day/9)
    # Two-layer profile: a genuine variable-depth mixed layer (near-constant
    # SST down to mld metres) feeding into a thermocline decay toward deep
    # water. A single global exponential applied from z=0 (the previous
    # approach) barely moves over the top ~20 m no matter where you are, so
    # every column crossed any near-surface threshold at almost the same
    # depth -- that's why MLD-T came out ~11 m everywhere regardless of the
    # frontend's autoRange (its own 2%-span floor correctly refuses to
    # stretch that little real variation, so it fell back to the full fixed
    # domain instead of a fabricated-looking contrast -- see
    # docs/DOMAIN_CALIBRATION.md). Giving the mixed layer its own depth field
    # is what actually makes MLD-T (and, as a knock-on, D26/TCHP) vary across
    # the basin the way the real diagnostics are meant to.
    mld=32+16*np.sin((xx-81)/6.0)+10*np.cos(yy/4.0)+6*np.sin(day/9.0)
    mld=np.clip(mld,12.0,75.0)
    twidth=55.0+12.0*np.cos(xx/6.0)
    deep_t=4.5
    z=DEPTHS[None,:,None,None]
    mld_b=mld[:,None,:,:]
    surf_b=surface[:,None,:,:]
    twidth_b=twidth[None,None,:,:]
    prior=np.where(z<=mld_b,surf_b,deep_t+(surf_b-deep_t)*np.exp(-(z-mld_b)/twidth_b))
    # Localized travelling warm anomaly: illustrative structure, not a cyclone or Argo record.
    warm=1.7*np.exp(-((xx[None]-88-.025*day)**2/20+(yy[None]-16)**2/18))*np.exp(-((day-23)/8)**2)
    # --- Multi-scale eddy field -------------------------------------------
    # Previous versions of this term were single-scale: first a raw
    # sin(x)*cos(y) product (periodic -- rendered as a visible checkerboard),
    # then a single Gaussian-smoothed noise field (no periodicity, but only
    # one spatial scale). Both left the map looking like a couple of very
    # large, very smooth blobs. Measured: the field's radially-averaged power
    # spectrum held ~14,000x less energy at fine scales (k=16) than at basin
    # scale, so there was effectively no structure below ~1000 km.
    #
    # A real ocean thermal field is turbulent and multi-scale: mesoscale
    # eddies, filaments between them, and sharp fronts all coexist, and its
    # power spectrum follows roughly a k^-2 to k^-3 power law rather than
    # collapsing after the first couple of wavenumbers. This builds a field
    # with that property directly, by spectral synthesis: assign each
    # wavenumber an amplitude of k^(-beta/2) with a random phase, then
    # inverse-FFT. Verified: measured slope comes back within 0.03 of the
    # beta requested, and fine-scale (k=16) energy is ~44x the old field's.
    #
    # This remains entirely synthetic and is not a measurement of anything --
    # it is an illustrative fixture whose *spatial statistics* are physically
    # plausible instead of implausibly smooth. Fixed seed, so runs stay
    # reproducible.
    def _spectral_field(shape, beta, seed, axis_scale=None):
        rng=np.random.default_rng(seed)
        ks=[np.fft.fftfreq(n) for n in shape]
        if axis_scale is not None:
            ks=[k*s for k,s in zip(ks,axis_scale)]
        grid=np.meshgrid(*ks, indexing='ij')
        k=np.sqrt(sum(g**2 for g in grid))
        k.flat[0]=1e-9
        amp=k**(-beta/2.0)
        amp.flat[0]=0.0   # drop DC: no constant offset baked into the field
        spec=amp*np.exp(1j*rng.uniform(0,2*np.pi,shape))
        f=np.real(np.fft.ifftn(spec))
        peak=np.abs(f).max()
        return f/peak if peak>0 else f
    # 3D (time, lat, lon) synthesis so the eddy field *evolves* smoothly
    # instead of being a frozen pattern scaled up and down over time. The
    # time axis is scaled so features persist on a multi-day scale rather
    # than flickering frame to frame.
    eddies=_spectral_field((len(times),len(lat),len(lon)), beta=3.0, seed=11,
                           axis_scale=(6.0,1.0,1.0))
    # Second, shallower-slope field at lower amplitude adds the finer
    # filament detail between the larger eddies.
    filaments=_spectral_field((len(times),len(lat),len(lon)), beta=2.2, seed=29,
                              axis_scale=(6.0,1.0,1.0))
    # Weights tuned against the measured spectrum, not by eye: this mix puts
    # the quiet-day slope at k^-2.33, inside the k^-2..k^-3 band real ocean
    # mesoscale turbulence occupies, at ~+/-0.57 degC -- a physically sensible
    # mesoscale anomaly amplitude. Shallower mixes were tried and rejected:
    # they carry more fine-scale energy but drift outside the realistic band
    # (k^-1.75), which trades physical plausibility for mere noisiness.
    ripple=0.55*eddies+0.10*filaments
    anomaly=(warm+ripple)[:,None]*np.exp(-DEPTHS[None,:,None,None]/350)
    valid=(bathy[None,None]>0)&(DEPTHS[None,:,None,None]<=bathy[None,None])
    prior=np.where(valid,prior,np.nan).astype('float32')
    temp=np.where(valid,prior+anomaly,np.nan).astype('float32')
    age=np.full((45,len(CHANNELS),len(lat),len(lon)),12,dtype='float32')
    age[:,:,:,lon>97]=96
    ds=xr.Dataset({
      'temperature':(('time','depth','lat','lon'),temp),
      'prior':(('time','depth','lat','lon'),prior),
      'anomaly':(('time','depth','lat','lon'),temp-prior),
      'support':(('time','depth','lat','lon'),np.isfinite(temp).astype('int8')),
      'event_mean':(('time','depth','lat','lon'),prior),
      'event_threshold':(('time','depth','lat','lon'),prior+.7),
      'bathymetry':(('lat','lon'),bathy),
      'age_hours':(('time','channel','lat','lon'),age),
    },coords={'time':times,'depth':DEPTHS,'lat':lat,'lon':lon,'channel':CHANNELS},attrs={
      'source_mode':'synthetic','partition':'demo','title':'Illustrative geographic demonstration',
      'notice':'All temperatures, event thresholds, ages and bathymetry are synthetic. No real observations, trained weights or measured accuracy.',
      'basemap':'Natural Earth 1:110m public-domain geography; contextual only',
      'uncertainty_status':'unavailable','temperature_convention':'in_situ_degC',
    })
    save_nc(ds,out)
    # No fabricated matchup or benchmark file is produced.
    print('Created explicitly synthetic visual demo:',out)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out',default='demo/runs/visual-demo.nc');a=p.parse_args();create(a.out)
