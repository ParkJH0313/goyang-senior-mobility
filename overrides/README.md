# 사전 판단·보정 입력 (overrides)

**2026-10-17 이전 완료.** 대화의 판단과 기존 전처리·Step 결과를 v7과 대조해 정리했습니다. 개별 판정 **698행**, 보정 도형 **278개**, 일반·취소·대체 판단 **44항목**입니다. 056번 네 입력은 별도로 보존합니다. 기존 연구 결과를 다시 계산한 작업은 아닙니다.

먼저 [판단 목록](decision_register.csv)에서 주제별로 확인하고, [v7 구현 인계](implementation_notes.md)에서 적용 기준과 폐기된 기준을 확인하면 됩니다. 개별 ID·좌표는 아래 CSV에 있습니다. [이전 점검 결과](migration_report.md)는 추출·검증 범위를 설명합니다.

## 파일 구성

| 파일 | 행 수 | 용도 |
|---|---:|---|
| building_decisions.csv | 383 | 건물 개별 판정 382개 + 군부대 건물군 1개(당시 구성원 22개) |
| walk_access_decisions.csv | 73 | 양방향 17·별도보도 48·출입불가 2·의료기관 출입점 근사 2·운정 지하차도 제외 2·서비스 POI 규칙 2 |
| origin_decisions.csv | 7 | 군부대 격자 제외 1 + 기존 출발점 장벽 근사 접속 6 |
| facility_decisions.csv | 66 | 큰 병원 주소 대리점 31 + 저장 지오코딩 35 |
| network_decisions.csv | 80 | 기존 연결 79(출발지 5·의료 3·정류장 71) + 군부대 자동 연결 금지 1 |
| transit_decisions.csv | 89 | 출입구 4·중앙정류장 가정 횡단 76·일반 담장 근사 9 |
| geometry_overrides.csv | 278 | 점·연결선 도형, 실제 구간/노드 참조, 적용 근거 |
| transit_056/ | 4개 CSV | 정류장 32·지선 3·공통구간 63정차·평일 출발 80편 |
| decision_register.csv | 44 | 분석 판단·일반 기준·취소/대체·작업 선호의 대조표. 실행 입력 아님 |
| evidence/ | 근거 | 대상 속성/원형상·상수 목록·출처 지문·남아 있는 사용자 원본 첨부 |
| validate_overrides.py | 코드 | 패키지 내부 ID·지문·도형·끝점·참조 검증 함수. 분석/적용기가 아님 |

같은 기관의 좌표 보완과 대리 출입점은 별도 작업이므로 행 수는 고유 장소 수가 아닙니다. geometry CSV의 override_id는 주 판정 CSV의 ID를 직접 참조하며(추가 관련 판정은 related_override_ids), 공통 필드는 연결된 판정의 근거를 상속한 것이며 278개의 추가 독립 승인을 뜻하지 않습니다.

## 공통 CSV 필드

CSV는 UTF-8 BOM, ID는 문자열입니다. 쉼표·따옴표가 있는 WKT와 JSON 셀은 표준 CSV 파서로 읽습니다.

| 필드 | 의미 |
|---|---|
| override_id | 내용 주제/대상에서 만든 안정적인 고유 보정 ID |
| dataset_id / target_id | 논리 자료 구분 / 원본 건물·OSM way/node·GTFS stop·격자 ID |
| action / field / new_value | 적용할 연산·필드·값. new_value는 JSON 문자열, 임의 실행 코드 아님 |
| expected_before / target_fingerprint | 적용 전 원본 속성·형상·연결점 기준과 정규화 JSON SHA-256 |
| reason | 판단 이유·허용 범위 |
| evidence_type / evidence_path | 직접 발언·이전 사용자 기록·가정 적용·코드 규칙·저장 API 결과 구분 / 이 폴더 기준 근거 상대경로 |
| source_url | 확인 당시 출처 URL. 이번 작업에서 재검색했다는 의미 아님 |
| decision_date / decision_source | 기존 기록상 날짜·출처. 확인 불가 날짜는 공란 |
| status | approved / superseded / pending / conflict. 현재 개별 입력은 approved |
| source_version / supersedes | 이전 스냅샷 버전 / 명시적 이전 보정 대체 ID. 새 적용이므로 supersedes는 공란 |

`dataset_id`는 address_buildings, osm_walk_network, origins_250m, medical_institutions, gtfs, override_geometry입니다. 실제 `data/manifest.json` 자료와 연결하는 로더는 후속 구현 대상입니다. 내부 component 번호, M/O 화면번호, 수치 stop_key를 실행 대상 키로 쓰지 않습니다. way 구간은 원본 way ID + 기존 전체 구간 WKT·양끝점·선상 위치로 검증합니다. 같은 way라도 분할이 바뀌면 옛 part 번호만 믿고 결합하지 않습니다.

`approved`는 모형 채택이 승인되었다는 뜻입니다. 현장 검증 여부는 별개이며 미확인 도형에 `provisional_not_field_verified` 등을 유지했습니다. 과거 기록에만 있는 개별 판단을 직접 대화에서 모두 확인했다고 표현하지 않았습니다.

## 도형 CSV

공통 필드 외 geometry_id, geometry_role, geometry_type, x, y, wkt, crs, from_ref, to_ref, direction, usage, assumption, source, geometry_sha256, metadata, cost_kind, from_position_m, to_position_m, related_override_ids가 있습니다.

- 표준 좌표계는 EPSG:5179. Point는 X/Y, LineString은 전체 꼭짓점의 WKT를 사용합니다. 좌표를 반올림하지 않았습니다.
- LineString 첫 꼭짓점은 from_ref, 마지막은 to_ref에 대응합니다. 양방향 링크라도 이 순서를 지킵니다. 원본 구간 중간 끝점의 선상 거리는 from_position_m/to_position_m에 보존했습니다.
- 0m 연결은 Point와 두 원본 구간 참조로 저장합니다. 0길이 LineString을 만들지 않습니다.
- cost_kind=`length_over_scenario_speed`는 현행 시나리오 속도로 비용을 계산합니다. `shared_node_no_distance`는 같은 위치 노드 결합입니다.
- cost_kind=`fixed_internal_walk_seconds`는 운정 내부 이동 180초를 뜻합니다. 해당 선은 설명용 도형이며 길이를 다시 비용에 더하지 않습니다.
- usage는 출발 전용·도착 전용·공용 보행·정류장 접근/승하차 등 사용 범위입니다. cost_kind와 함께 적용하여 보정선이 임의 통과 지름길로 쓰이지 않게 합니다.
- from_ref/to_ref의 osm_segment, osm_node, gtfs_stop는 evidence의 target 표와 연결합니다. user_entrance는 transit 판정의 입구점, hospital은 facility의 도착점, grid는 origin의 원래 출발점입니다.
- geometry_sha256는 EPSG:5179 좌표의 SRID 없는 little-endian WKB 지문입니다. 수치 변환 후 동일 지문인지 검증했습니다.

GPKG는 이 폴더의 필수 입력으로 만들지 않았습니다. 향후 분석 코드가 CSV를 검사하고 `outputs/<run_id>/derived/geometry_overrides.gpkg`로 생성합니다. 생성 결과를 수동 수정해 새 원본으로 쓰지 않습니다.

## 중복 적용·새 충돌

일반 생성 규칙보다 원본 ID가 지정된 제외·선택 접속을 먼저 반영합니다. 이미 보정된 processed에는 동일 도형/056 운행편을 다시 추가하지 않습니다. 값이 이미 일치하면 already_applied로 기록하고 지나갑니다. 달라진 원본은 멋대로 덮어쓰지 않고 실제 영향을 받는 건만 검토합니다. 자세한 우선순위와 최소 환승시간 처리의 v7 대체는 implementation_notes.md에 있습니다.

이전 제출용 경로가 실행 중 필요하지 않도록 필요한 보정값·근거를 안에 옮겼습니다. source_manifest의 legacy_submission 표기는 출처 이름일 뿐 파일을 열기 위한 경로가 아닙니다. 전체 기초자료와 v7 분석 코드는 이 보정 패키지와 별도로 준비합니다. 과거 군집·고정 선정 격자·접근성 점수·경로 캐시는 보정 입력에 포함하지 않았습니다.
