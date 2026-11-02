#!/usr/bin/env python3
"""One-command local launcher. First run: python start.py --setup
Subsequent runs: python start.py. Existing OCEAN_RUN is respected.
"""
import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup',action='store_true',help='Create .venv and install locked frontend / Python dependencies')
    args=parser.parse_args()
    os.chdir(ROOT)
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm: raise SystemExit('Node.js/npm is required. Install Node 22 and retry.')
    python=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if args.setup:
        if not python.exists():subprocess.run([sys.executable,'-m','venv',str(ROOT/'.venv')],check=True)
        subprocess.run([str(python),'-m','pip','install','-e','.[dev]'],check=True)
        subprocess.run([npm,'ci'],cwd=ROOT/'frontend',check=True)
    if not python.exists() or not (ROOT/'frontend/node_modules').exists():
        raise SystemExit('First-time setup required: python start.py --setup')
    for port in (8000,5173):
        with socket.socket() as sock:
            try: sock.bind(('127.0.0.1',port))
            except OSError:raise SystemExit(f'Port {port} is busy. Stop the other local server and retry.')
    env=os.environ.copy()
    if not env.get('OCEAN_RUN'):
        demo=ROOT/'demo/runs/visual-demo.nc'
        if not demo.exists():subprocess.run([str(python),'scripts/create_visual_demo.py','--out',str(demo)],check=True)
        env['OCEAN_RUN']=str(demo)
    elif not Path(env['OCEAN_RUN']).exists():raise SystemExit('OCEAN_RUN does not point to an existing file.')
    children=[]
    try:
        children.append(subprocess.Popen([str(python),'-m','uvicorn','oceanembed.api:app','--host','127.0.0.1','--port','8000'],env=env,start_new_session=(os.name!="nt")))
        ready=False
        for _ in range(150):
            if children[0].poll() is not None:raise RuntimeError('API exited before becoming ready.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=.5) as r:
                    ready=r.status==200
                if ready:break
            except OSError:time.sleep(.2)
        if not ready:raise RuntimeError('API did not become ready within 30 seconds.')
        children.append(subprocess.Popen([npm,'run','dev','--','--port','5173','--strictPort'],cwd=ROOT/'frontend',env=env,start_new_session=(os.name!="nt")))
        print('\nOceanEmbed: http://127.0.0.1:5173  |  Ctrl+C stops both services.\n',flush=True)
        while all(c.poll() is None for c in children):time.sleep(.3)
        raise RuntimeError('A service stopped. See its error above.')
    except KeyboardInterrupt:print('\nStopping OceanEmbed…')
    finally:
        for c in reversed(children):
            if c.poll() is None:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(c.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:os.killpg(c.pid,signal.SIGTERM)
        for c in children:
            try:c.wait(timeout=5)
            except subprocess.TimeoutExpired:c.kill();c.wait()

if __name__=='__main__':main()
