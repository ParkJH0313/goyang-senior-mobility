# -*- coding: utf-8 -*-
"""경계 원자료 7세트로 5개 경계 레이어를 생성하고 검증한다.
실행: python "preprocess/01_boundaries.py"
다른 폴더의 가공파일, 기존 GeoJSON, 네트워크/API를 입력으로 사용하지 않는다.
산출물: data/processed/boundaries.gpkg. 처리 건수와 검증 결과는 표준출력으로 반환한다.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.preprocessing_common import (ROOT, initialize, internal, data_path, save_report,
    building_constants, validate_buildings, building_application_log, walk_constants, validate_walk)
initialize()
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4
import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import MultiPolygon

CRS = "EPSG:5179"
DATE = "20250630"
TOL = 0.01  # m², 연산 오차 판정용. 스냅/단순화 허용거리가 아니다.
GOYANG = {"31101": "고양시 덕양구", "31103": "고양시 일산동구", "31104": "고양시 일산서구"}
NEIGHBORS = {
    "11010": "종로구", "11080": "성북구", "11090": "강북구", "11100": "도봉구",
    "11120": "은평구", "11130": "서대문구", "11140": "마포구", "11160": "강서구",
    "31030": "의정부시", "31200": "파주시", "31230": "김포시", "31260": "양주시",
}
DONG_COUNTS = {"31101": 21, "31103": 12, "31104": 11}
LAYERS = {
    "goyang_boundary": ("고양시 전체", 1),
    "goyang_sigungu": ("고양시 3개 구", 3),
    "goyang_dong": ("고양시 행정동", 44),
    "surrounding_sigungu": ("주변 12개 지역", 12),
    "study_area": ("고양시와 주변 12개 지역의 합집합", 1),
}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def manifest(paths, data):
    result = {}
    for path in paths:
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            p = path.with_suffix(suffix)
            require(p.is_file(), f"필수 구성파일 누락: {p}")
            result[p.relative_to(data).as_posix()] = sha256(p)
    return dict(sorted(result.items()))

def find_one(root, name):
    matches = sorted(root.rglob(name))
    require(len(matches) == 1, f"{name}: 원본이 정확히 1개여야 함. 현재 {len(matches)}개")
    return matches[0]

def as_polygon(geom):
    require(geom is not None and not geom.is_empty, "빈 도형은 자동 삭제하지 않음")
    result = shapely.make_valid(geom) if not geom.is_valid else geom
    require(result.geom_type in ("Polygon", "MultiPolygon"), "비면적 요소가 생긴 도형은 별도 확인 필요")
    require(result.is_valid and not result.is_empty and result.area > 0, "유효한 면적 도형이 아님")
    if result.geom_type == "Polygon":
        result = MultiPolygon([result])
    return shapely.normalize(result)

def read_source(path, data):
    raw = gpd.read_file(path, engine="pyogrio")  # CPG 인코딩 자동 인식
    require(raw.crs is not None, f"좌표계 누락: {path.name}")
    require(set(raw.BASE_DATE.astype(str)) == {DATE}, f"기준일 불일치: {path.name}")
    require(not raw.geometry.isna().any() and not raw.geometry.is_empty.any(), "빈/누락 도형 존재")
    out = raw.to_crs(CRS).copy()
    out["_source_row"] = range(len(out))  # 원본 SHP의 0-based 행 번호
    out["_repaired"] = (~out.is_valid).astype(int)
    info = {"file": path.relative_to(data).as_posix(), "count": len(raw),
            "epsg": raw.crs.to_epsg(), "invalid": int((~raw.is_valid).sum())}
    return out, info

def add_area(frame):
    frame["area_m2"] = frame.geometry.area
    frame["area_km2"] = frame.area_m2 / 1e6
    return frame

def standardize(frame, code_col, name_col, source, level, parent=None):
    frame = frame.copy()
    codes = frame[code_col].astype(str).str.strip()
    require(not codes.duplicated().any() and codes.str.fullmatch(r"\d+").all(), "행정코드 중복/오류")
    out = gpd.GeoDataFrame({
        "boundary_id": codes.tolist(), "sgis_code": codes.tolist(),
        "name_ko": frame[name_col].astype(str).str.strip().tolist(),
        "level": level, "parent_code": [parent or c[:2] for c in codes],
        "sido_name": ["서울특별시" if c.startswith("11") else "경기도" for c in codes],
        "is_goyang": [int(c[:5] in GOYANG) for c in codes],
        "base_date": DATE, "source_file": source,
        "source_row": frame._source_row.astype(int).tolist(),
        "geometry_repaired": frame._repaired.astype(int).tolist(),
    }, geometry=[as_polygon(x) for x in frame.geometry], crs=CRS)
    return add_area(out).sort_values("boundary_id").reset_index(drop=True)

def combine(frames):
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS).sort_values(
        "boundary_id").reset_index(drop=True)

def dissolve(frame, ident, name):
    # 섬/구멍 보존. 버퍼, 스냅, 단순화, convex hull 미사용.
    out = gpd.GeoDataFrame([{
        "boundary_id": ident, "sgis_code": "", "name_ko": name, "level": "dissolved",
        "parent_code": "", "sido_name": "경기도" if ident == "GOYANG" else "경기도·서울특별시",
        "is_goyang": int(ident == "GOYANG"), "base_date": DATE,
        "source_file": ";".join(sorted(set(frame.source_file))), "source_row": -1,
        "geometry_repaired": int(frame.geometry_repaired.max()),
        "geometry": as_polygon(shapely.union_all(frame.geometry.values)),
    }], crs=CRS)
    return add_area(out)

def area_check(checks, label, value):
    value = abs(float(value))
    require(value <= TOL, f"{label}: {value:.9f} m² > {TOL} m²")
    checks.append((label, f"{value:.9f} m²", "통과"))

def validate(name, frame):
    require(len(frame) == LAYERS[name][1], f"{name}: 예상 건수 불일치")
    require(frame.crs.to_epsg() == 5179, f"{name}: 좌표계 불일치")
    require(frame.is_valid.all() and not frame.is_empty.any(), f"{name}: 도형 오류")
    require(not frame.boundary_id.duplicated().any(), f"{name}: ID 중복")
    require(set(frame.geom_type) == {"MultiPolygon"} and (frame.area_m2 > 0).all(), f"{name}: 도형 유형/면적 오류")

def content_hash(frame):
    """속성+정규화 WKB 해시. GPKG 저장시각과 무관하게 내용 재현성 비교."""
    h = hashlib.sha256()
    for _, row in frame.sort_values("boundary_id").iterrows():
        attrs = {k: (v.item() if hasattr(v, "item") else v)
                 for k, v in row.items() if k != "geometry"}
        h.update(json.dumps(attrs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        h.update(shapely.normalize(row.geometry).wkb)
    return h.hexdigest()

def save_verify(layers, path, checks):
    for name, frame in layers.items():
        validate(name, frame)
        pyogrio.write_dataframe(frame, path, layer=name, driver="GPKG",
                                geometry_type="MultiPolygon", layer_options={"SPATIAL_INDEX": "YES"})
    require(set(pyogrio.list_layers(path)[:, 0]) == set(layers), "저장 레이어 목록 불일치")
    hashes = {}
    for name, frame in layers.items():
        actual = gpd.read_file(path, layer=name, engine="pyogrio")
        validate(name, actual)
        require(set(actual.columns) == set(frame.columns), f"{name}: 저장 필드 불일치")
        require(content_hash(actual) == content_hash(frame), f"{name}: 저장 후 내용 불일치")
        hashes[name] = content_hash(actual)
        checks.append((f"{name} 저장 재읽기", f"{len(actual)}건 / 속성·도형 일치", "통과"))
    with closing(sqlite3.connect(path)) as conn:
        require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "GPKG 무결성 오류")
    checks.append(("GeoPackage 무결성", "SQLite integrity_check = ok", "통과"))
    return hashes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT/'data')
    data = data_path(parser.parse_args().data_dir)
    raw, output = data / "raw" / "경계", data / "processed"
    require(raw.is_dir(), f"원자료 폴더 없음: {raw}")
    paths = [find_one(raw, f"bnd_sigungu_{c}_2025_2Q.shp") for c in GOYANG]
    paths += [find_one(raw, f"bnd_dong_{c}_2025_2Q.shp") for c in GOYANG]
    paths += [find_one(raw, "bnd_sigungu_00_2025_2Q.shp")]
    before, frames, infos = manifest(paths, data), {}, []
    for path in paths:
        frame, info = read_source(path, data)
        frames[path.stem] = (frame, info["file"])
        infos.append(info)
    checks, districts, dongs = [], [], []
    for code, name in GOYANG.items():
        f, src = frames[f"bnd_sigungu_{code}_2025_2Q"]
        require(len(f) == 1 and f.SIGUNGU_CD.iloc[0] == code and f.SIGUNGU_NM.iloc[0] == name,
                f"구 코드/명칭/개수 오류: {code}")
        districts.append(standardize(f, "SIGUNGU_CD", "SIGUNGU_NM", src, "sigungu"))
        f, src = frames[f"bnd_dong_{code}_2025_2Q"]
        require(len(f) == DONG_COUNTS[code] and f.ADM_CD.str.startswith(code).all(), f"행정동 소속/개수 오류: {code}")
        dongs.append(standardize(f, "ADM_CD", "ADM_NM", src, "dong", code))
    districts, dongs = combine(districts), combine(dongs)
    national, src = frames["bnd_sigungu_00_2025_2Q"]
    targets = {**GOYANG, **NEIGHBORS}
    chosen = national.loc[national.SIGUNGU_CD.isin(targets)].copy()
    require(len(chosen) == 15 and set(chosen.SIGUNGU_CD) == set(targets), "15개 대상 구역 누락/중복")
    require(all(targets[x.SIGUNGU_CD] == x.SIGUNGU_NM for _, x in chosen.iterrows()), "지역 코드/명칭 불일치")
    neighbors = standardize(chosen[chosen.SIGUNGU_CD.isin(NEIGHBORS)], "SIGUNGU_CD", "SIGUNGU_NM", src, "sigungu")
    checks.append(("지역 선정", "고양시 3개 구 + 경기 4개 시 + 서울 8개 구, 부산 강서구 제외", "통과"))
    for code in GOYANG:
        local = districts.loc[districts.sgis_code == code].geometry.iloc[0]
        official = as_polygon(chosen.loc[chosen.SIGUNGU_CD == code].geometry.iloc[0])
        subset = dongs.loc[dongs.parent_code == code]
        union = shapely.union_all(subset.geometry.values)
        area_check(checks, f"{code} 전국/개별 구 경계 대칭차", local.symmetric_difference(official).area)
        area_check(checks, f"{code} 구/행정동 합집합 대칭차", local.symmetric_difference(union).area)
        area_check(checks, f"{code} 행정동 중첩 면적", subset.area_m2.sum() - union.area)
    city = dissolve(districts, "GOYANG", "고양시")
    all_regions = combine([districts, neighbors])
    study = dissolve(all_regions, "STUDY_AREA", "고양시 및 주변 12개 지역")
    area_check(checks, "고양시 구 간 중첩 면적", districts.area_m2.sum() - city.geometry.iloc[0].area)
    area_check(checks, "15개 구역 간 중첩 면적", all_regions.area_m2.sum() - study.geometry.iloc[0].area)
    area_check(checks, "통합 경계 밖 고양시 면적", city.geometry.iloc[0].difference(study.geometry.iloc[0]).area)
    layers = dict(zip(LAYERS, [city, districts, dongs, neighbors, study]))
    output.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    gpkg_tmp = output / f".boundaries_{token}.gpkg"
    try:
        hashes = save_verify(layers, gpkg_tmp, checks)
        require(manifest(paths, data) == before, "실행 중 원본 변경 감지")
        checks.append(("원본 보존", "필수 구성파일 35개 SHA-256 실행 전후 일치", "통과"))
        checks.append(("출력 개수·도형·좌표계", "5개 레이어, 1·3·44·12·1건, 유효 MultiPolygon, EPSG:5179", "통과"))
        gpkg_tmp.replace(output / "boundaries.gpkg")
    finally:
        # 이 실행이 생성한 임시 파일만 삭제. 디렉터리 삭제 없음.
        if gpkg_tmp.is_file():
            gpkg_tmp.unlink()
    report = {"layers": {n: {"count": len(f), "area_km2": float(f.area_km2.sum()),
                                    "sha256": hashes[n]} for n, f in layers.items()},
                      "sources": infos, "checks_passed": len(checks),
                      "checks": [{"item": item, "result": result, "status": status}
                                 for item, result, status in checks],
                      "output": (output / "boundaries.gpkg").relative_to(ROOT).as_posix()}
    save_report("boundaries", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

