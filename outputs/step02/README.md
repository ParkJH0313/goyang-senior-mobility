# Step 2 주거 대표점과 보행 접속

격자 내부 주거 합집합의 면적 중심을 출발점으로 산정합니다. 주거 도형이 없으면 잠정 격자 중심을 사용하고 접속거리 전체를 보행비용에 포함합니다.

## 코드 구성

- steps/step02_origins.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/spatial_network.py: 최근접 접속과 통행 조건.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| origins.gpkg / origins_250m | 2,586 | 주거 면적 중심 또는 잠정 격자 중심점. |
| origins.gpkg / origin_connectors | 2,586 | 출발점 전용 접속선. 전체 길이를 시간으로 환산한다. |
| origins.gpkg / network_corrections | 79 | 원본 노드·구간 사이의 공용 보행 연결. |

## 결과 파일

- figures/origins_overview.png: 전체 결과 지도·그래프.
- tables/origin_building_sources.csv: 수치 표. UTF-8 BOM.
- tables/origin_status.csv: 수치 표. UTF-8 BOM.

## 결과 요약

- origins: 2586
- connected: 2586
- unresolved: 0
- provisional_centroids: 105

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)입니다. 미도달 0과 자료가 불완전한 NaN은 구분합니다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함됩니다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아닙니다.
