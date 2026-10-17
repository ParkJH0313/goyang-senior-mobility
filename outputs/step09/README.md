# Step 9 취약 원인 진단

군집별 보행·대기·차내·추가 탑승 준비시간을 집계한다. 도달 경로의 조건부 평균과 전체 인구·시각의 미도달 비중을 함께 제시한다.

## 코드 구성

- steps/step09_diagnosis.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/path_diagnosis.py: 경로 시간 성분 재구성. src/figures.py: 군집 단위 진단 그래프.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| diagnosis.gpkg / cluster_diagnosis | 3 | 군집별 시간 성분과 미도달 비율. |
| diagnosis.gpkg / reached_facilities | 2,487 | 군집의 도달 기회에 기여하는 기관. |
| diagnosis.gpkg / diagnostic_routes | 11 | 표본 경로의 승하차 정류장 설명선. 실제 차량 궤적이 아니다. |

## 결과 파일

- figures/cluster_diagnosis.png: 전체 결과 지도·그래프.
- tables/cluster_diagnosis.csv: 수치 표. UTF-8 BOM.
- tables/extended_arrival_bands.csv: 수치 표. UTF-8 BOM.
- tables/facility_contribution.csv: 수치 표. UTF-8 BOM.
- travel_components.parquet: 정밀도·자료형을 유지한 계산표.

## 결과 요약

- diagnostic_origins: 328
- travel_rows: 167608
- clusters: 3

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)다. 미도달 0과 자료가 불완전한 NaN은 구분한다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함된다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아니다.
