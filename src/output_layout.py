"""One-time checked relocation and presentation-only refresh of completed results."""
import shutil,importlib
from pathlib import Path
import pandas as pd
from src.analysis_io import ROOT,inside,sha,read_json,atomic_json,parquet,csv,log

CORE=['src/router.py','src/timetable.py','src/scope_check.py','src/walking.py',
      'src/aggregation.py','src/path_diagnosis.py','src/spatial_network.py',
      'src/stop_access.py','src/preprocessing_common.py']
STEPS=['population','origins','facilities','network','routing','accessibility','clusters','sensitivity','diagnosis']

def move_local(source,target):
    source=inside(source);target=inside(target)
    assert source!=target and not target.is_relative_to(source)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():raise FileExistsError(target)
    shutil.move(str(source),str(target))

def migrate_legacy_layout():
    root=inside('outputs');pending=inside('.cache/analysis/layout_migration.json')
    if pending.exists() and read_json(pending).get('status')=='pending':return True
    if (root/'run_manifest.json').exists():return False
    candidates=list(root.glob('v7_*/run_manifest.json'))
    if not candidates:return False
    if len(candidates)!=1:raise RuntimeError('Select one completed output before migrating the layout.')
    manifest=candidates[0];old=manifest.parent;state=read_json(manifest)
    assert state['status']=='complete'
    for p in CORE:assert sha(p)==state['code_sha256'][p], 'Calculation code changed: '+p
    for p,h in state['inputs'].items():assert sha(p)==h, 'Research input changed: '+p
    for stage in state['stages'].values():
        for p,h in stage['outputs'].items():assert sha(old/p)==h, 'Output changed: '+p
    backup=inside('.cache/analysis/layout_backup')
    backup.mkdir(parents=True,exist_ok=True)
    atomic_json(backup/'source_run_manifest.json',state)
    # Keep one private copy of each detailed OD array; these are reproducible caches.
    catalog=read_json(old/'derived_manifest.json')['files']
    for cp in list(old.glob('step05/*checkpoint.parquet'))+list(old.glob('step08/*checkpoint.parquet')):
        frame=pd.read_parquet(cp);paths=[]
        for rel in frame.path:
            src=inside(rel);dst=inside('.cache/analysis')/src.parent.name/src.name
            expected=catalog[src.relative_to(old).as_posix()]
            assert sha(src)==expected
            if not dst.exists():
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
            assert sha(dst)==expected
            paths.append(dst.relative_to(ROOT).as_posix())
        frame['path']=paths;parquet(frame,cp)
        side=cp.parent/'tables'/cp.with_suffix('.csv').name
        if side.exists():csv(frame,side)
    atomic_json(pending,{'status':'pending','run_id':state['run_id'],'source_inputs':state['inputs']})
    for child in list(old.iterdir()):
        if child.name in ['derived','derived_manifest.json']:
            move_local(child,backup/child.name)
        else:move_local(child,root/child.name)
    assert old.resolve().is_relative_to(root.resolve())
    old.rmdir();log('Completed results relocated to outputs/step01 ... step09; OD arrays retained in .cache.')
    return True

def check_presentation_inputs(ctx,migration=False):
    state=ctx.state
    assert len(state.get('stages',{}))==9 and all(s.get('status')=='complete' for s in state['stages'].values()), 'Complete the numerical stages first.'
    assert state['inputs']==ctx.inputs, 'Inputs changed; run processed mode.'
    protected=CORE if migration else CORE+[f'steps/step{i:02d}_{s}.py' for i,s in enumerate(STEPS,1)]+['run.py','src/routing_runner.py','src/cluster_diagnostics.py','src/cluster_labels.py']
    for p in protected:assert sha(p)==state['code_sha256'][p], 'Calculation code changed; run processed mode: '+p
    if not migration:
        for st in state['stages'].values():
            for p,h in st['outputs'].items():
                if '/figures/' in p or p.endswith('README.md'):continue
                assert sha(ctx.output/p)==h,'Saved data changed: '+p

def refresh_completions(ctx,rebind=False):
    for n,name in enumerate(STEPS,1):
        stage=ctx.state['stages'][str(n)]
        if rebind:
            module=importlib.import_module(f'steps.step{n:02d}_{name}')
            stage['signature']=ctx.signature(n,module.DEPENDENCIES,module.SETTINGS)
        stage['outputs']={p.relative_to(ctx.output).as_posix():sha(p) for p in ctx.step(n).rglob('*') if p.is_file() and p.name!='completion.json' and not p.name.endswith('.tmp')}
        stage['parent_signatures']={str(k):ctx.state['stages'][str(k)]['signature'] for k in range(1,n)}
        atomic_json(ctx.step(n)/'completion.json',stage)
    ctx.state['output_layout']='flat_steps';ctx.save()
    if rebind:atomic_json(ctx.cache/'layout_migration.json',{'status':'complete','run_id':ctx.run_id})

def remove_retired_products(ctx):
    """Remove obsolete products, including their spatial layers, not just HTML links."""
    import pyogrio
    from src.analysis_io import gpkg
    names={'review_required.csv','review_candidates.csv','override_application_log.csv',
           'decision_continuity.csv','origin_diagnosis.csv','first_walk_eligibility.csv',
           'cluster_internal_maps.png','06_extended_time_maps.png','extended_arrival_bands.csv','cluster_diagnosis.png'}
    for p in ctx.output.rglob('*'):
        if p.is_file() and p.name in names:
            assert p.resolve().is_relative_to(ctx.output.resolve());p.unlink()
    retired_preview=inside('assets/results/time_budget_comparison.png')
    if retired_preview.exists():retired_preview.unlink()
    file=ctx.step(9)/'diagnosis.gpkg'
    layers=[name for name,_ in pyogrio.list_layers(file)]
    if set(layers)&{'origin_diagnosis','review_required'}:
        gpkg(file,{name:pyogrio.read_dataframe(file,layer=name) for name in layers if name not in {'origin_diagnosis','review_required'}})
    # Execution checks remain private; the report is for reading research results.
    report=ctx.output/'validation_report.json'
    if report.exists():
        atomic_json(ctx.cache/'validation_report.json',read_json(report));report.unlink()
