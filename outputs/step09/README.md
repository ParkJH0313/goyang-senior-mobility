# Step 9 취약 원인 진단

군집별 보행·대기·차내·추가 탑승 준비시간을 집계합니다. 도달 경로의 조건부 평균과 전체 인구·시각의 미도달 비중을 제시하고, 출발시각에 따른 평균 대기시간을 비교합니다.

## 코드 구성

- steps/step09_diagnosis.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/path_diagnosis.py: 경로 성분 재구성. src/cluster_diagnostics.py: 도달 상태·조건부 평균 및 버스정류장 최단보행 계산. src/diagnostic_figures.py: 군집별 막대그래프·보행시간과 고령인구 지도, 출발시각별 대기시간 집계표와 히트맵.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| diagnosis.gpkg / cluster_diagnosis | 3 | 군집별 시간 성분과 미도달 비율. |
| diagnosis.gpkg / reached_facilities | 2,519 | 군집의 도달 기회에 기여하는 기관. |
| diagnosis.gpkg / diagnostic_routes | 15 | 표본 경로의 승하차 정류장 설명선. 실제 차량 궤적이 아니다. |
| diagnosis.gpkg / stop_walk_250m | 317 | 기준 상위 군집의 250m 출발 격자. 평일 승차 가능한 버스정류장까지 방향성 보행망 최단시간이며 10분 상한을 적용하지 않은 진단값. |
| diagnosis.gpkg / diagnostic_population_500m | 116 | 같은 군집의 원래 500m 격자와 고령인구. 250m 보행시간 위에 인구를 표시하는 기준 도형. |
| diagnosis.gpkg / nearest_boarding_stops | 117 | 각 출발점에서 보행시간이 가장 짧은 평일 버스 승차 정류장. 군집별 중복은 유지한다. |

## 결과 파일

- figures/arrival_diagnosis_C001.png: 전체 결과 지도·그래프.
- figures/arrival_diagnosis_C002.png: 전체 결과 지도·그래프.
- figures/arrival_diagnosis_C003.png: 전체 결과 지도·그래프.
- figures/bus_walk_population_C001.png: 전체 결과 지도·그래프.
- figures/bus_walk_population_C002.png: 전체 결과 지도·그래프.
- figures/bus_walk_population_C003.png: 전체 결과 지도·그래프.
- figures/waiting_time_by_departure.png: 전체 결과 지도·그래프.
- tables/arrival_status.csv: 수치 표. UTF-8 BOM.
- tables/arrival_time_components.csv: 수치 표. UTF-8 BOM.
- tables/bus_walk_population.csv: 수치 표. UTF-8 BOM.
- tables/cluster_diagnosis.csv: 수치 표. UTF-8 BOM.
- tables/facility_contribution.csv: 수치 표. UTF-8 BOM.
- tables/nearest_bus_walk.csv: 수치 표. UTF-8 BOM.
- tables/waiting_time_by_departure.csv: 수치 표. UTF-8 BOM.
- travel_components.parquet: 정밀도·자료형을 유지한 계산표.

## 결과 요약

- diagnostic_origins: 317
- travel_rows: 161987
- clusters: 3

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)입니다. 미도달 0과 자료가 불완전한 NaN은 구분합니다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함됩니다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아닙니다.

기본 보행속도는 0.8m/s이고 시간예산은 30분입니다.

arrival_status.csv는 상호 배타적인 도달 상태의 인구·출발시각 가중 비율입니다. 첫 보행 불가는 첫 정류장과 의료기관 직접 보행이 모두 10분 이내에 불가능한 경우입니다. 80분 내 미도달은 첫 보행은 가능하지만 탐색 한도 안에 도달하지 못한 경우입니다. 자료 미해결은 별도 분류합니다.
arrival_time_components.csv는 30분 이내 도달 및 30분 초과~80분 도달 그룹별 시간 성분 평균입니다. 전체 비율은 고유 인원 비율이 아니며, 두 그룹의 차이는 정책의 인과효과가 아닙니다.
nearest_bus_walk.csv와 bus_walk_population.csv는 보행시간 상한 없이 가장 가까운 평일 버스 승차 정류장을 찾은 결과 및 구간별 인구 집계입니다. 신호·휴식·배차 대기는 제외합니다. 지도는 보행 부담 진단이고 본 접근성 계산의 연속보행 10분 조건을 변경하지 않습니다. 500m 인구는 원래 격자값이며 구간별 인구는 250m 배분값으로 합산합니다.

figures/waiting_time_by_departure.png는 travel_components.parquet에서 80분 내 의료기관에 도달한 출발 격자·시각의 경로를 대상으로 첫 탑승 대기와 환승 대기의 합계를 30분 구간별로 비교합니다. 보행속도 0.8m/s와 연속보행 10분 조건을 유지합니다. 시각별 도달 경로 구성은 달라질 수 있으며 미도달·자료 미해결을 대기 0분으로 넣지 않습니다. 환승 준비시간과 신호 대기는 포함하지 않습니다.
tables/waiting_time_by_departure.csv의 mean_wait_min은 고령인구 가중 평균 대기시간(분)입니다. period=30min은 해당 출발시각 구간, overall은 전체 08:30~17:00의 도달 경로를 직접 가중한 값입니다. 전체 평균은 구간별 평균의 단순평균이 아닙니다. departure_start_s와 departure_end_s는 자정부터 센 초이며 시작은 포함하고 끝은 end_inclusive=True일 때만 포함합니다. 마지막 16:30 구간은 17:00를 포함합니다. 도달 경로가 없는 구간의 평균은 빈값이며 그림에서는 —로 표시합니다.
src/diagnostic_figures.py의 waiting_time_figure가 집계표와 그림을 함께 생성합니다. python run.py processed는 분석 후 전체 결과를 생성하고, python run.py report는 저장된 경로 자료로 그림·집계표·보고서를 재생성합니다.
