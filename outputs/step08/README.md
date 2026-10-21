# Step 8 민감도 비교

기준 보행속도와 상위 3개 군집의 격자·인구를 고정해 시간예산을 비교합니다. 하위 비율 변경은 전체 유효 격자에서 다시 군집화합니다.

## 코드 구성

- steps/step08_sensitivity.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/aggregation.py · src/routing_runner.py: 시나리오 계산. src/figures.py: 저장된 OD의 500m 집계와 비교 지도.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| sensitivity.gpkg / cutoff_25_grids | 219 | 해당 하위 비율에서 다시 선정한 격자·군집. |
| sensitivity.gpkg / cutoff_25_clusters | 57 | 해당 하위 비율에서 다시 선정한 격자·군집. |
| sensitivity.gpkg / cutoff_30_grids | 263 | 해당 하위 비율에서 다시 선정한 격자·군집. |
| sensitivity.gpkg / cutoff_30_clusters | 51 | 해당 하위 비율에서 다시 선정한 격자·군집. |
| sensitivity.gpkg / cutoff_35_grids | 306 | 해당 하위 비율에서 다시 선정한 격자·군집. |
| sensitivity.gpkg / cutoff_35_clusters | 41 | 해당 하위 비율에서 다시 선정한 격자·군집. |
| sensitivity.gpkg / budget_30_grids | 116 | 기준 군집의 시간예산별 500m 점수. 군집·인구를 고정했다. |
| sensitivity.gpkg / budget_40_grids | 116 | 기준 군집의 시간예산별 500m 점수. 군집·인구를 고정했다. |
| sensitivity.gpkg / budget_50_grids | 116 | 기준 군집의 시간예산별 500m 점수. 군집·인구를 고정했다. |

## 결과 파일

- extended_checkpoint.parquet: 완료된 출발점과 상세 경로 배열 위치. 배열은 .cache/analysis에 보관합니다.
- figures/01_time_budget_top3.png: 전체 결과 지도·그래프.
- figures/02_time_budget_profiles.png: 전체 결과 지도·그래프.
- figures/04_cutoff_cluster_maps.png: 전체 결과 지도·그래프.
- figures/05_cutoff_top3_overlap.png: 전체 결과 지도·그래프.
- sensitivity_minute_profiles.parquet: 정밀도·자료형을 유지한 계산표.
- tables/cluster_crosswalk.csv: 수치 표. UTF-8 BOM.
- tables/cutoff_25_membership.csv: 수치 표. UTF-8 BOM.
- tables/cutoff_25_summary.csv: 수치 표. UTF-8 BOM.
- tables/cutoff_30_membership.csv: 수치 표. UTF-8 BOM.
- tables/cutoff_30_summary.csv: 수치 표. UTF-8 BOM.
- tables/cutoff_35_membership.csv: 수치 표. UTF-8 BOM.
- tables/cutoff_35_summary.csv: 수치 표. UTF-8 BOM.
- tables/scenario_manifest.csv: 수치 표. UTF-8 BOM.
- tables/sensitivity_cluster_metrics.csv: 수치 표. UTF-8 BOM.
- tables/sensitivity_grid_scores.csv: 수치 표. UTF-8 BOM.
- tables/top3_overlap.csv: 수치 표. UTF-8 BOM.

## 결과 요약

- top3_origins: 317
- scenarios: 6
- time_budget_monotonic: True

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)입니다. 미도달 0과 자료가 불완전한 NaN은 구분합니다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함됩니다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아닙니다.

기본 보행속도는 0.8m/s이고 시간예산은 30분입니다.

지도 경계는 기본 30분 점수의 하위 30% 경계로 고정합니다. 시간예산은 30·40·50분만 비교하며 기준 군집을 바꾸지 않습니다. 평균 0 / 0 초과~경계 / 경계 초과를 공통 색으로 표현합니다.
