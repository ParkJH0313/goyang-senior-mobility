import numpy as np,pandas as pd
from src.analysis_io import csv,parquet,describe
from src.routing_runner import calculate
DEPENDENCIES=['steps/step05_routing.py','src/router.py','src/routing_runner.py','src/timetable.py','src/scope_check.py','src/analysis_io.py']
SETTINGS=['baseline_speed_mps','baseline_budget_min','departure_start_s','departure_end_s','departure_interval_s','max_boardings','transfer_preparation_s','max_continuous_walk_s']

def run(ctx):
    origins=pd.read_parquet(ctx.step(4)/'origin_index.parquet')
    checkpoints=calculate(ctx,list(origins.index),ctx.config['baseline_speed_mps'],ctx.config['baseline_budget_min'])
    parquet(checkpoints,ctx.step(5)/'routing_checkpoint.parquet');csv(checkpoints,ctx.step(5)/'tables/routing_checkpoint.csv')
    times=np.arange(ctx.config['departure_start_s'],ctx.config['departure_end_s']+1,ctx.config['departure_interval_s'])
    csv(pd.DataFrame({'departure_index':np.arange(len(times)),'departure_s':times,'time':[f'{s//3600:02d}:{s%3600//60:02d}' for s in times]}),ctx.step(5)/'tables/departure_index.csv')
    describe(ctx,5,'# Step 5 매분 시간표 경로\n\n`steps/step05_routing.py`는 출발점별 511개 시각을 계산한다. `src/router.py`는 최대 3회 탑승 라운드마다 실제 승차 가능한 모든 운행편을 검사한다. 느린 선행 차량만 선택하지 않으며 추월 차량·노선 대안도 포함한다. 연속보행은 정류장 방문이나 대기로 초기화하지 않고 전체 보행 연결에 600초를 적용한다. `src/routing_runner.py`는 64시각 묶음과 출발점 완료 NPZ를 원자적으로 저장한다. routing_checkpoint의 프로젝트 상대경로에서 기관별 최소 소요시간(od), 가장 빠른 기관과 시간 성분, 최대 3개 탑승 구간을 복원할 수 있다. 511개 완료 전에는 최종 점수를 만들지 않는다.\n')
    return {'origins_complete':len(checkpoints),'departures_each':len(times)}
