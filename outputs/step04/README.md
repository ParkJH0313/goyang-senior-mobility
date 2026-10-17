# Step 4 정류장·철도·환승망

정류장·철도 출입구·지상 보행망을 연결한다. 접속거리와 역 내부 이동시간을 합산하고 방향 및 연속보행 한도를 적용한다.

## 코드 구성

- steps/step04_network.py: 입력 읽기 → 계산 → 표·공간자료 저장.
- src/spatial_network.py · src/stop_access.py · src/walking.py: 접속 도형, 방향성 거리망, 연속보행.
- src/reporting.py: 결과 설명과 보고서 구성.
- src/figures.py 및 src/input_figures.py: 전체 결과 지도·그래프.

## 공간 레이어

| 파일 / 레이어 | 객체 수 | 의미 |
|---|---:|---|
| network.gpkg / stop_access | 29,532 | 정류장·출입구의 접속선과 고정 내부 이동시간. |
| network.gpkg / stops | 56,911 | 시간표 정류장과 접속 상태. |
| network.gpkg / network_corrections | 79 | 원본 노드·구간 사이의 공용 보행 연결. |

## 결과 파일

- connections.parquet: 정밀도·자료형을 유지한 계산표.
- facility_index.parquet: 정밀도·자료형을 유지한 계산표.
- figures/network_overview.png: 전체 결과 지도·그래프.
- graph_nodes.parquet: 정밀도·자료형을 유지한 계산표.
- network_qa.json: 계산 구조 명세.
- origin_index.parquet: 정밀도·자료형을 유지한 계산표.
- stops.parquet: 정밀도·자료형을 유지한 계산표.
- tables/eligible_routes.csv: 수치 표. UTF-8 BOM.
- tables/service_profile.csv: 수치 표. UTF-8 BOM.
- walk_graph.npz: 압축 배열.
- walk_links.parquet: 정밀도·자료형을 유지한 계산표.

## 결과 요약

- stops: 56911
- access_points: 29532
- graph_arcs: 832629
- walk_links: 332830

## 해석

좌표계 EPSG:5179, 거리 m, 계산시간 초, 점수는 기관 수(곳)다. 미도달 0과 자료가 불완전한 NaN은 구분한다.
도착 위치와 보행 접속에는 자료 기반 대리점·근사가 포함된다. 056번 중간 정차시각은 추정값이며 진료 가능 여부까지 나타내는 지표는 아니다.
