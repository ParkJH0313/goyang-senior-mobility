# Step 3 의료기관과 도착점

대상 전문의 자격을 갖춘 의료기관을 기관 ID별로 구성하고 도착점과 보행망 사이의 접속선을 생성한다.

## 코드 구성

- steps/step03_facilities.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/spatial_network.py: 기관 도착점 접속.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| facilities.gpkg / facilities | 1,143 | 대상 전문의 자격을 충족하는 기관 ID별 위치. |
| facilities.gpkg / destination_connectors | 1,143 | 보행망에서 의료기관 도착점까지의 전용 접속선. |

## 결과 파일

- figures/facilities_overview.png: 전체 결과 지도·그래프.
- tables/facility_status.csv: 수치 표. UTF-8 BOM.

## 결과 요약

- facilities: 1143
- connected: 1143
- unresolved: 0

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)다. 미도달 0과 자료가 불완전한 NaN은 구분한다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함된다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아니다.
