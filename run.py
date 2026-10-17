"""Run the v7 study; the same command resumes validated checkpoints."""
from pathlib import Path
import sys,importlib,time
from src.analysis_io import initialize,Context,now,log
initialize()

CONFIG={
 'methodology':'v7','crs':'EPSG:5179','departure_start_s':30600,'departure_end_s':61200,'departure_interval_s':60,
 'baseline_speed_mps':0.8,'max_continuous_walk_s':600,
 'max_boardings':3,'transfer_preparation_s':60,'rail_entrance_s':180,'rail_transfer_s':240,'same_platform_s':120,
 'baseline_budget_min':30,'sensitivity_budgets_min':[30,40,50],'diagnostic_budgets_min':[45,60,80],
 'baseline_cutoff':0.30,'cutoffs':[0.25,0.30,0.35],'top_clusters':3,
 'excluded_modes':['high_speed_rail','intercity_bus','airport_bus','gtx','air','ferry'],
 'connector_search_m':2000.0,'rail_entrance_search_m':500.0,'spatial_tolerance_m':1e-5,'dpi':300,
 'median_crossing_search_m':720.0,'station_group_radius_m':800.0,'station_second_gap_m':50.0,'station_second_ratio':1.5,
 'stop_ground_fallback_m':50.0,'stop_poi_search_m':40.0,'stop_road_evidence_m':20.0,
 'service_profile_id':'KTDB_2025_03_weekday_with_056_2025_supplement','signal_wait_s':0,
}
STEPS=['population','origins','facilities','network','routing','accessibility','clusters','sensitivity','diagnosis']

def execute_resumable(ctx,n,module):
    """Resume durable OD checkpoints if Windows briefly locks the progress file."""
    for attempt in range(21):
        try:
            return ctx.execute(n,module)
        except PermissionError as exc:
            path=Path(exc.filename or '').resolve()
            progress_lock=(n in {5,8} and getattr(exc,'winerror',None) in {5,32,33}
                and path.is_relative_to(ctx.cache.resolve()) and path.name in {'progress.json','progress.json.tmp'})
            if not progress_lock or attempt==20:raise
            log(f'Step {n}: progress file temporarily locked; resuming saved origins ({attempt+1}/20)')
            time.sleep(min(attempt+1,5))
            ctx.state['status']='running';ctx.save()

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'raw','processed','report'}:raise SystemExit('Usage: python run.py {raw|processed|report}')
    from src.artifact_cache import run_lock
    with run_lock():execute(sys.argv[1])

def execute(mode):
    from src.output_layout import migrate_legacy_layout,check_presentation_inputs,refresh_completions
    migrated=migrate_legacy_layout()
    if mode=='raw':
        from preprocess.__main__ import preprocess_all
        preprocess_all()
    ctx=Context(CONFIG,mode)
    from src.artifact_cache import repair_derived,reuse_static,finalize_artifacts,bind_input_caches
    from src.reporting import progress,finish
    if mode=='report' or (migrated and mode!='raw'):
        check_presentation_inputs(ctx,migration=migrated)
        log('Rendering saved results; no route searches will run')
        finish(ctx)
        refresh_completions(ctx,rebind=migrated)
        finalize_artifacts(ctx)
        ctx.state.update(status='complete');ctx.save();progress(ctx)
        log('Presentation complete: outputs/결과_보기.html')
        return
    bind_input_caches(ctx);repair_derived(ctx)
    progress(ctx)
    log('Run '+ctx.run_id+'; output '+str(ctx.output.relative_to(Path(__file__).resolve().parent)))
    for n,name in enumerate(STEPS,1):
        module=importlib.import_module(f'steps.step{n:02d}_{name}')
        reuse_static(ctx,n,module);execute_resumable(ctx,n,module)
        progress(ctx)
    try:
        repair_derived(ctx);finish(ctx);refresh_completions(ctx);finalize_artifacts(ctx)
    except BaseException as exc:
        ctx.state.update(status='incomplete',postprocessing_error=str(exc));ctx.save();progress(ctx);raise
    ctx.state.update(status='complete',completed_at=now());ctx.save();log('All v7 stages complete')
    progress(ctx)

if __name__=='__main__':main()
