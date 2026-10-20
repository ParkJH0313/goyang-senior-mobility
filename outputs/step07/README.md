# Step 7 저접근 군집

유효 500m 점수의 하위 30%에 경계 동점을 포함한다. Queen 인접 군집을 구성하고 고령인구 합계로 상위 3개를 선정한다.

## 코드 구성

- steps/step07_clusters.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/aggregation.py: 경계 동점·Queen 군집·인구 순위. src/cluster_labels.py: 표·지도·보고서의 지역명 통일. src/figures.py의 overview: 전체 하위 30% 격자와 상위 3개 군집 지도.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| clusters.gpkg / low_access_500m | 263 | 하위 30% 격자와 군집 소속. |
| clusters.gpkg / cluster_summary | 51 | 군집 합집합 도형, 인구·점수·순위. |

## 결과 파일

- cluster_qa.json: 계산 구조 명세.
- figures/accessibility_clusters.png: 전체 결과 지도·그래프.
- tables/baseline_top3_membership.csv: 수치 표. UTF-8 BOM.
- tables/cluster_membership.csv: 수치 표. UTF-8 BOM.
- tables/cluster_summary.csv: 수치 표. UTF-8 BOM.

## 결과 요약

- clusters: 51
- top_clusters: 3
- valid_grids: 874
- cutoff: 0.3
- order_statistic: 263
- threshold: 2.0084299262381458
- tied_at_boundary: 1
- selected_grids: 263
- selected_fraction: 0.3009153318077803
- queen_tolerance_m: 1e-05

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)다. 미도달 0과 자료가 불완전한 NaN은 구분한다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함된다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아니다.

기본 보행속도는 0.8m/s이고 시간예산은 30분이다.

figures/accessibility_clusters.png는 clusters.gpkg의 low_access_500m에 저장된 하위 30% 격자 전체를 한 지도에 표시한다. baseline_top3_membership.csv에 속하는 상위 3개 군집은 고령인구 순위별 색과 윤곽으로, 그 외 저접근 격자는 회색 단색으로 표시한다. 연한 배경 격자는 나머지 고령인구 격자다. 군집별 인구·평균 접근성·순위와 경계 동점을 포함한 저접근 경계를 함께 표기한다.
python run.py processed는 분석 후 그림을 생성하고, python run.py report는 저장된 격자·군집 자료로 그림과 HTML을 재생성한다. README의 assets/results/accessibility_clusters.png에도 같은 지도가 저장된다.
