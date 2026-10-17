"""Reusable static stages and repairable, integrity-checked exported checkpoints."""
import os,shutil,sys
from contextlib import contextmanager
import pandas as pd
from src.analysis_io import inside,read_json,atomic_json,sha,gpkg,log


@contextmanager
def run_lock(path='.cache/analysis/run.lock'):
    path=inside(path);path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b')
    try:
        handle.seek(0,os.SEEK_END)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:raise RuntimeError('Another analysis process is using this project; resume after it exits.') from exc
        yield
    finally:handle.close()


def bind_input_caches(ctx):
    """Invalidate auxiliary caches whose local key omits a cross-stage input."""
    marker=ctx.cache/'input_binding.json'
    current={'inputs':ctx.input_id,'stop_access_code':sha('src/stop_access.py')}
    previous=read_json(marker) if marker.exists() else {}
    # Scope rows depend on origin positions, facilities and GTFS transfer policy,
    # not just stop coordinates. A changed input set must rebuild this envelope.
    if previous.get('inputs')!=current['inputs']:
        for file in ctx.cache.glob('scope_*.parquet'):
            assert file.resolve().is_relative_to(ctx.cache.resolve());file.unlink()
    if previous.get('stop_access_code')!=current['stop_access_code']:
        for file in ctx.cache.glob('stop_access_*/complete.json'):
            assert file.resolve().is_relative_to(ctx.cache.resolve());file.unlink()
    atomic_json(marker,current)


def copy_local(source,target):
    source=inside(source);target=inside(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():return
    try:os.link(source,target)
    except OSError:shutil.copy2(source,target)


def reuse_static(ctx,n,module):
    # Each step now has one stable location; Context.execute validates reuse.
    return False


def repair_derived(ctx):
    """Validate private route checkpoints; missing caches invalidate their stage."""
    catalog_path=ctx.cache/('checkpoints_'+ctx.run_id+'.json')
    catalog=read_json(catalog_path).get('files',{}) if catalog_path.exists() else {}
    for n in [5,8]:
        for checkpoint in ctx.step(n).glob('*checkpoint.parquet'):
            failed=False
            for rel in pd.read_parquet(checkpoint)['path']:
                path=inside(rel);expected=catalog.get(rel)
                if path.exists() and (expected is None or sha(path)==expected):continue
                assert path.is_relative_to(ctx.cache)
                if path.exists():path.unlink()
                failed=True
            if failed:
                marker=ctx.step(n)/'completion.json'
                if marker.exists():marker.unlink()


def finalize_artifacts(ctx):
    files={}
    for n in [5,8]:
        for checkpoint in ctx.step(n).glob('*checkpoint.parquet'):
            for rel in pd.read_parquet(checkpoint)['path']:
                files[rel]=sha(rel)
    atomic_json(ctx.cache/('checkpoints_'+ctx.run_id+'.json'),{'files':files,'source_inputs':ctx.input_id})
    ctx.state['python_version']=sys.version.split()[0]
    ctx.state['code_sha256']={p.relative_to(inside('.')).as_posix():sha(p) for pattern in ['run.py','src/*.py','steps/*.py','tests/*.py'] for p in inside('.').glob(pattern)}
    ctx.save()
