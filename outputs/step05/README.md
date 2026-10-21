# Step 5 511개 출발시각 경로

08:30~17:00의 511개 출발시각에서 지정된 보행·탑승 조건에 따른 가장 빠른 의료기관 도착시간을 계산합니다.

## 코드 구성

- steps/step05_routing.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/router.py · src/timetable.py · src/routing_runner.py: 시간표 경로 탐색과 중단 재개.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|

비공간 경로 단계입니다. 출발점과 기관은 Step2·3의 원본 ID로 연결합니다.

## 결과 파일

- routing_checkpoint.parquet: 완료된 출발점과 상세 경로 배열 위치. 배열은 .cache/analysis에 보관합니다.
- tables/departure_index.csv: 수치 표. UTF-8 BOM.
- tables/routing_checkpoint.csv: 완료된 출발점과 상세 경로 배열 위치. 배열은 .cache/analysis에 보관합니다.

## 결과 요약

- origins_complete: 2586
- departures_each: 511

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)입니다. 미도달 0과 자료가 불완전한 NaN은 구분합니다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함됩니다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아닙니다.

기본 보행속도는 0.8m/s이고 시간예산은 30분입니다.
