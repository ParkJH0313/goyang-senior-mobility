# Step 1 인구와 가중치

원래 250m·500m 격자와 공개·마스킹·빈값 상태를 유지하고 고령인구 및 부모·자식 가중치를 구성합니다.

## 코드 구성

- steps/step01_population.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/analysis_io.py: 입력 검증과 원자적 저장.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| population.gpkg / population_250m | 4,533 | 원래 250m 격자와 추정 고령인구·자료 상태. |
| population.gpkg / population_500m | 1,206 | 250m 자식 인구를 합친 원래 500m 격자. |

## 결과 파일

- figures/population_500m.png: 전체 결과 지도·그래프.
- tables/parent_child_weights.csv: 수치 표. UTF-8 BOM.
- tables/population_qa.csv: 수치 표. UTF-8 BOM.

## 결과 요약

- population: 217395.3
- positive_origins: 2587
- included_origins: 2586
- excluded_population: 3.0

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)입니다. 미도달 0과 자료가 불완전한 NaN은 구분합니다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함됩니다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아닙니다.
