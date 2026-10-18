"""Project-local, atomic research outputs and content-addressed checkpoints."""
from __future__ import annotations
import os, sys, json, hashlib, sqlite3, importlib.metadata, traceback
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]

def inside(path):
    p=Path(path); p=(p if p.is_absolute() else ROOT/p).resolve()
    if not p.is_relative_to(ROOT): raise ValueError('Project-external research path: '+str(p))
    return p

def initialize():
    for key,rel in {'TEMP':'.tmp','TMP':'.tmp','TMPDIR':'.tmp','MPLCONFIGDIR':'.cache/matplotlib','NUMBA_CACHE_DIR':'.cache/numba','XDG_CACHE_HOME':'.cache','PIP_CACHE_DIR':'.cache/pip'}.items():
        p=inside(rel);p.mkdir(parents=True,exist_ok=True);os.environ[key]=str(p)
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')

def now():return datetime.now(timezone.utc).isoformat()
def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(path):
    with inside(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read_json(path):return json.loads(inside(path).read_text(encoding='utf-8'))
def atomic_json(path,obj):
    p=inside(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');os.replace(tmp,p)
def atomic_npz(path,**data):
    import numpy as np
    p=inside(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    with tmp.open('wb') as f:np.savez_compressed(f,**data)
    os.replace(tmp,p)
def parquet(frame,path):
    p=inside(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.stem+'.tmp.parquet')
    frame.to_parquet(tmp,index=False);os.replace(tmp,p)
def csv(frame,path):
    p=inside(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    frame.to_csv(tmp,index=False,encoding='utf-8-sig');os.replace(tmp,p)
def ro(path):return sqlite3.connect(inside(path).as_uri()+'?mode=ro',uri=True)
def gpkg(path,layers):
    import pyogrio
    p=inside(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.stem+'.tmp.gpkg')
    if tmp.exists():tmp.unlink()
    for name,frame in layers.items():
        if not len(frame):continue
        pyogrio.write_dataframe(frame,tmp,layer=name,driver='GPKG')
    if tmp.exists():os.replace(tmp,p)
def log(message):print('['+datetime.now().strftime('%H:%M:%S')+'] '+message,flush=True)

def preflight():
    from overrides.validate_overrides import validate
    metadata=read_json('data/manifest.json');files={}
    for d in metadata['datasets']:
        if d['kind'] not in {'processed','override_input'}:continue
        for f in d['files']:files[f['path']]=f
    # Preprocessing reports are audit records, not analysis inputs.
    for f in metadata['overrides']:files[f['path']]=f
    verified={}
    for name,f in files.items():
        if name.startswith('data/raw/'):raise AssertionError('raw dependency in processed mode')
        actual=sha(name)
        if actual!=f['sha256']:raise ValueError('Input changed since manifest: '+name)
        verified[name]=actual
    package=validate()
    return verified,package

class Context:
    def __init__(self,config,mode):
        initialize();self.config=config;self.mode=mode
        self.inputs,self.package=preflight()
        self.input_id=digest(self.inputs);self.run_id='v7_'+digest({'inputs':self.inputs,'settings':config})[:12]
        self.output=inside('outputs');self.output.mkdir(parents=True,exist_ok=True)
        self.cache=inside('.cache/analysis');self.cache.mkdir(parents=True,exist_ok=True)
        self.state={'schema_version':'1.0','methodology_version':'v7','run_id':self.run_id,'mode':mode,'settings':config,'inputs':self.inputs,'started_at':now(),'status':'running','stages':{},'packages':{x:importlib.metadata.version(x) for x in ['numpy','pandas','geopandas','shapely','scipy','pyogrio','numba','matplotlib','pyarrow']}}
        old=self.output/'run_manifest.json'
        if old.exists():
            prior=read_json(old)
            if prior.get('run_id')==self.run_id:
                self.state.update(prior)
                self.state['mode']=mode
        self.save()
    def save(self):atomic_json(self.output/'run_manifest.json',self.state)
    def step(self,n):
        p=self.output/f'step{n:02d}';p.mkdir(parents=True,exist_ok=True);return p
    def signature(self,n,modules,config_keys):
        return digest({'inputs':self.input_id,'code':{p:sha(p) for p in modules},'settings':{k:self.config[k] for k in config_keys},'parents':{str(k):self.state['stages'].get(str(k),{}).get('signature') for k in range(1,n)}})
    def execute(self,n,module):
        key=str(n);sig=self.signature(n,module.DEPENDENCIES,module.SETTINGS)
        marker=self.step(n)/'completion.json';previous=read_json(marker) if marker.exists() else {}
        if previous.get('signature')==sig and all(inside(self.output/p).exists() and sha(self.output/p)==h for p,h in previous.get('outputs',{}).items()):
            self.state['stages'][key]=previous;self.save();log(f'Step {n}: verified completed outputs, reused');return
        self.state['stages'][key]={'signature':sig,'status':'running','started_at':now()};self.save()
        try:
            log(f'Step {n}: starting');summary=module.run(self)
            outputs={p.relative_to(self.output).as_posix():sha(p) for p in self.step(n).rglob('*') if p.is_file() and p.name!='completion.json' and not p.name.endswith('.tmp')}
            done={'signature':sig,'status':'complete','completed_at':now(),'summary':summary,'outputs':outputs}
            atomic_json(marker,done);self.state['stages'][key]=done;self.save();log(f'Step {n}: complete {summary}')
        except BaseException as e:
            self.state['stages'][key].update(status='interrupted' if isinstance(e,KeyboardInterrupt) else 'failed',error=str(e),updated_at=now())
            self.state['status']='incomplete';self.save();raise

def describe(ctx,n,text):
    (ctx.step(n)/'README.md').write_text(text,encoding='utf-8')
