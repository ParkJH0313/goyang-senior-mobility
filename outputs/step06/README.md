# Step 6 접근성 집계

시각별 도달 의료기관 수를 평균하고 원래 고령인구를 가중치로 사용해 250m에서 500m로 집계한다.

## 코드 구성

- steps/step06_accessibility.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/aggregation.py: 시각 평균과 인구 가중 집계.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| accessibility.gpkg / accessibility_250m | 4,533 | 511시각 평균 도달 기관 수와 점수 유효성. |
| accessibility.gpkg / accessibility_500m | 1,206 | 고령인구 가중 500m 접근성 점수. |

## 결과 파일

- minute_profiles.npz: 압축 배열.
- tables/accessibility_250m.csv: 수치 표. UTF-8 BOM.
- tables/accessibility_500m.csv: 수치 표. UTF-8 BOM.
- tables/coverage_summary.csv: 수치 표. UTF-8 BOM.
- tables/time_band_summary.csv: 수치 표. UTF-8 BOM.

## 결과 요약

- valid_250m: 2586
- valid_500m: 874
- excluded_or_unresolved_500m: 1

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)다. 미도달 0과 자료가 불완전한 NaN은 구분한다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함된다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아니다.
