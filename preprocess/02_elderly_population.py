# -*- coding: utf-8 -*-
"""고령인구 250m·500m 원자료의 상태 분류, 공동 추정, 집계 가중치 생성.
실행: python "preprocess/02_elderly_population.py"
입력: data/raw/고령인구의 202504 SHP 두 세트. 다른 가공자료는 사용하지 않는다.
집계 기준: 부모 인구는 원자료에 존재하는 자식 격자들의 인구 합계로 해석한다.
출력: data/processed/elderly_population.gpkg 및 표준출력의 처리·검증 요약.
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
import math
import sqlite3
from contextlib import closing
from itertools import product
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import box

MONTH = "202504"
CRS = "EPSG:5179"
MASK_MIN, MASK_MAX = 1, 5  # 연구 가정. 이 두 입력 자료에만 적용한다.
EPS = 1e-8
AREA_EPS = 0.01  # m², 도형 중첩 판정용
AGGREGATION_RULE = "parent_total_equals_sum_of_existing_children"
MASKED = {"masked_zero", "masked_explicit"}
ERRORS = {"source_conflict", "parse_error"}
LAYERS = {250: "elderly_250m", 500: "elderly_500m"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest(paths, data):
    result = {}
    for path in paths:
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cst"):
            part = path.with_suffix(suffix)
            require(part.is_file(), f"필수 원본 구성파일 누락: {part}")
            result[part.relative_to(data).as_posix()] = sha256(part)
    return dict(sorted(result.items()))


def classify(label, value):
    """표시값과 숫자값을 함께 판정한다. 원본 두 열은 별도로 보존한다."""
    text = "" if pd.isna(label) else str(label).strip()
    numeric_null = pd.isna(value)
    if not text and numeric_null:
        return "blank_as_zero", 0.0, 0.0, 0.0
    explicit_mask = text.upper() in {"N/A", "NA"} or (bool(text) and set(text) == {"*"})
    if explicit_mask:
        if numeric_null or value == 0:
            status = "masked_zero" if not numeric_null else "masked_explicit"
            return status, np.nan, float(MASK_MIN), float(MASK_MAX)
        return "source_conflict", np.nan, np.nan, np.nan
    try:
        label_number = float(text) if text else None
        value_number = float(value) if not numeric_null else None
    except (ValueError, TypeError):
        return "parse_error", np.nan, np.nan, np.nan
    for number in (label_number, value_number):
        if number is not None and (not math.isfinite(number) or number < 0 or not number.is_integer()):
            return "parse_error", np.nan, np.nan, np.nan
    if value_number is None or (label_number is not None and label_number != value_number):
        return "source_conflict", np.nan, np.nan, np.nan
    if value_number == 0:
        return "masked_zero", np.nan, float(MASK_MIN), float(MASK_MAX)
    return "published", value_number, value_number, value_number


def read_grid(path, size, data):
    encoding = path.with_suffix(".cst").read_text(encoding="ascii").strip()
    require(encoding.upper().replace("-", "") == "UTF8", f"예상과 다른 인코딩: {encoding}")
    frame = gpd.read_file(path, engine="pyogrio", encoding=encoding)
    require(set(frame.columns) == {"gid", "lbl", "val", "geometry"}, f"원본 열 구성 변경: {path}")
    require(frame.crs is not None and frame.crs.to_epsg() == 5179, "원본 좌표계 확인 필요")
    require(not frame.gid.isna().any() and frame.gid.is_unique, "원본 ID 누락/중복")
    require(frame.gid.str.fullmatch(r"[가-힣]{2}[0-9ab]+").all(), "ID 인코딩/형식 오류")
    require(frame.geometry.notna().all() and frame.is_valid.all() and not frame.is_empty.any(),
            "원본 도형 오류: 자동 수정하지 않음")
    require(set(frame.geom_type) == {"Polygon"}, "예상과 다른 격자 도형 유형")
    bounds = frame.bounds
    require(np.allclose(bounds.maxx - bounds.minx, size, rtol=0, atol=EPS)
            and np.allclose(bounds.maxy - bounds.miny, size, rtol=0, atol=EPS),
            "격자 크기 불일치")
    require(all(g.equals(box(*g.bounds)) for g in frame.geometry), "직사각형 전체 격자가 아님")
    frame["source_row"] = range(len(frame))
    frame["source_file"] = path.relative_to(data).as_posix()
    frame["reference_month"] = MONTH
    frame["grid_size_m"] = size
    states = [classify(label, value) for label, value in zip(frame.lbl, frame.val)]
    for i, col in enumerate(("population_status", "population_known", "population_min", "population_max")):
        frame[col] = [row[i] for row in states]
    frame["population_estimated"] = frame.population_known
    frame["estimate_method"] = frame.population_status.map(
        {"published": "observed", "blank_as_zero": "blank_as_zero"}).fillna("unresolved")
    frame["range_basis"] = "source_rule"
    frame["joint_solution_count"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    frame["group_status"] = ""
    frame["needs_review"] = 0
    frame["review_reason"] = ""
    frame["aggregation_ready"] = 0
    return frame.sort_values("gid").reset_index(drop=True)


def population_options(row):
    if row.population_status in MASKED:
        return range(MASK_MIN, MASK_MAX + 1)
    require(pd.notna(row.population_known), "미확정 원자료 값을 정수 후보로 변환할 수 없음")
    return (int(row.population_known),)


def solve_joint(parent, children):
    """존재하는 자식들의 합계가 부모를 만족하는 정수 조합에 같은 비중을 준다."""
    child_count = len(children)
    require(1 <= child_count <= 4, "부모당 존재하는 자식이 1~4개여야 함")
    allowed_parent = set(population_options(parent))
    solutions = [values for values in product(*(population_options(row) for _, row in children.iterrows()))
                 if sum(values) in allowed_parent]
    return np.asarray(solutions, dtype=np.int64).reshape((-1, child_count))


def set_estimate(frame, index, values, count):
    frame.at[index, "population_estimated"] = float(np.mean(values))
    frame.at[index, "population_min"] = int(np.min(values))
    frame.at[index, "population_max"] = int(np.max(values))
    frame.at[index, "joint_solution_count"] = count
    frame.at[index, "range_basis"] = "joint_feasible"
    if frame.at[index, "population_status"] in MASKED:
        frame.at[index, "estimate_method"] = "joint_mean"


def connect_and_estimate(child, parent):
    # 사용자가 정한 집계 범위: 존재하는 자식만으로 부모 인구를 구성한다.
    # 경계 밖 칸을 추가하거나 별도의 인구를 부여하지 않는다. 원본 도형 유지.
    parent_key = parent[["gid", "geometry"]].rename(columns={"gid": "parent_gid"})
    joined = gpd.sjoin(child[["geometry"]], parent_key, how="left", predicate="within")
    require(joined.index.is_unique and joined.parent_gid.notna().all(),
            "250m 격자의 부모 없음/복수 연결: 자료 점검 필요")
    child["parent_gid"] = joined.parent_gid.reindex(child.index)
    child["aggregation_weight"] = np.nan
    child["origin_required"] = child.population_status.map(
        {"published": 1, "masked_zero": 1, "masked_explicit": 1, "blank_as_zero": 0}).fillna(-1).astype(int)
    parent["child_count"] = parent.gid.map(child.parent_gid.value_counts()).fillna(0).astype(int)
    parent["absent_child_count"] = 4 - parent.child_count
    require(parent.child_count.between(0, 4).all(), "부모당 자식 개수 오류")
    parent["available_child_population_sum"] = np.nan
    parent["balance_difference"] = np.nan
    parent["weight_sum"] = np.nan
    groups = child.groupby("parent_gid", sort=True).groups
    reviews = []
    for pi, pr in parent.iterrows():
        indices = list(groups.get(pr.gid, []))
        kids = child.loc[indices].sort_values("gid")
        indices = kids.index.tolist()
        if pr.population_status in ERRORS or kids.population_status.isin(ERRORS).any():
            status, reason = "source_error", "표시값과 숫자값의 충돌 또는 파싱 오류"
        elif len(kids) == 0:
            status, reason = "no_children", "연결된 자식 격자가 없어 인구 합계를 검증할 수 없음"
        else:
            union = shapely.union_all(kids.geometry.values)
            require(pr.geometry.covers(union), f"{pr.gid}: 부모 밖 자식 도형")
            require(abs(kids.geometry.area.sum() - union.area) <= AREA_EPS,
                    f"{pr.gid}: 자식 격자 도형 중복·중첩")
            if len(kids) == 4:
                require(pr.geometry.equals(union), f"{pr.gid}: 부모와 자식 합집합 도형 불일치")
            solutions = solve_joint(pr, kids)
            if not len(solutions):
                status, reason = "infeasible_total", "공개값·빈값·1~5명 마스킹 범위를 만족하는 공동 조합 없음"
                parent.at[pi, "joint_solution_count"] = 0
                child.loc[indices, "joint_solution_count"] = 0
            else:
                totals = solutions.sum(axis=1)
                set_estimate(parent, pi, totals, len(solutions))
                for ci, idx in enumerate(indices):
                    set_estimate(child, idx, solutions[:, ci], len(solutions))
                status = "resolved_positive" if totals.mean() > 0 else "resolved_zero"
                reason = ""
                if status == "resolved_positive":
                    weights = child.loc[indices, "population_estimated"] / parent.at[pi, "population_estimated"]
                    child.loc[indices, "aggregation_weight"] = weights
                    child.loc[indices, "aggregation_ready"] = 1
                    parent.at[pi, "aggregation_ready"] = 1
                    parent.at[pi, "weight_sum"] = weights.sum()
                parent.at[pi, "balance_difference"] = (
                    child.loc[indices, "population_estimated"].sum() - parent.at[pi, "population_estimated"])
        parent.at[pi, "group_status"] = status
        parent.at[pi, "review_reason"] = reason
        child.loc[indices, "group_status"] = status
        child.loc[indices, "review_reason"] = reason
        vals = child.loc[indices, "population_estimated"]
        if len(vals) and vals.notna().all():
            parent.at[pi, "available_child_population_sum"] = vals.sum()
        if reason:
            parent.at[pi, "needs_review"] = 1
            child.loc[indices, "needs_review"] = 1
            reviews.append({
                "parent_gid": pr.gid, "issue": status, "detail": reason,
                "child_count": len(kids), "absent_child_count": 4 - len(kids),
                "parent_status": pr.population_status, "parent_population_raw": pr.val,
                "parent_population_known": pr.population_known,
                "known_child_sum": float(kids.population_known.sum()),
                "masked_child_count": int(kids.population_status.isin(MASKED).sum()),
                "blank_child_count": int(kids.population_status.eq("blank_as_zero").sum()),
                "published_child_count": int(kids.population_status.eq("published").sum()),
                "child_gids": json.dumps(kids.gid.tolist(), ensure_ascii=False),
                "child_raw_values": json.dumps([None if pd.isna(v) else float(v) for v in kids.val], allow_nan=False),
            })
    for frame in (child, parent):
        frame["population_resolved"] = frame.population_estimated.notna().astype(int)
        frame["is_imputed"] = frame.estimate_method.eq("joint_mean").astype(int)
    review_columns = ["parent_gid", "issue", "detail", "child_count", "absent_child_count",
                      "parent_status", "parent_population_raw", "parent_population_known",
                      "known_child_sum", "masked_child_count", "blank_child_count",
                      "published_child_count", "child_gids", "child_raw_values"]
    review_frame = pd.DataFrame(reviews, columns=review_columns)
    # 검토 대상이 0개여도 동일한 형식의 빈 속성표를 저장한다.
    integer_columns = {"child_count", "absent_child_count", "masked_child_count",
                       "blank_child_count", "published_child_count"}
    float_columns = {"parent_population_raw", "parent_population_known", "known_child_sum"}
    for column in review_columns:
        dtype = "Int64" if column in integer_columns else "float64" if column in float_columns else "string"
        review_frame[column] = review_frame[column].astype(dtype)
    return child, parent, review_frame


def content_hash(frame, key):
    """DB 저장시각과 무관하게 속성과 원래 WKB를 비교한다."""
    h = hashlib.sha256()
    for _, row in frame.sort_values(key).iterrows():
        attrs = {}
        for name in sorted(set(frame.columns) - {"geometry"}):
            value = row[name]
            if pd.isna(value):
                attrs[name] = None
            elif isinstance(value, (int, float, np.number)):
                attrs[name] = float(value)  # NULL이 있는 정수 열의 재읽기 자료형 차이를 통일
            else:
                attrs[name] = str(value)
        h.update(json.dumps(attrs, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8"))
        if "geometry" in frame.columns:
            h.update(row.geometry.wkb)
    return h.hexdigest()


def validate_result(child, parent, reviews, originals):
    checks = []
    def check(name, ok):
        require(bool(ok), name)
        checks.append(name)
    for size, frame in ((250, child), (500, parent)):
        original = originals[size]
        check(f"{size}m 원본 ID·건수 유지", frame.gid.tolist() == original.gid.tolist())
        check(f"{size}m 원본 도형 그대로 유지",
              all(a.wkb == b.wkb for a, b in zip(frame.geometry, original.geometry)))
        check(f"{size}m 원본 표시값·숫자값 보존", frame[["gid", "lbl", "val"]].equals(original[["gid", "lbl", "val"]]))
        fixed = frame.population_known.notna()
        check(f"{size}m 공개값·확정 0 보존",
              np.allclose(frame.loc[fixed, "population_estimated"], frame.loc[fixed, "population_known"], rtol=0, atol=EPS))
        estimated = frame.population_estimated.notna()
        check(f"{size}m 추정값 허용범위 준수",
              (frame.loc[estimated, "population_estimated"] >= frame.loc[estimated, "population_min"] - EPS).all()
              and (frame.loc[estimated, "population_estimated"] <= frame.loc[estimated, "population_max"] + EPS).all())
        unresolved_mask = frame.population_status.isin(MASKED) & frame.needs_review.eq(1)
        check(f"{size}m 미해결 마스킹 임의 대입 없음", frame.loc[unresolved_mask, "population_estimated"].isna().all())
    ok = parent.group_status.isin(["resolved_positive", "resolved_zero"])
    actual_counts = parent.gid.map(child.groupby("parent_gid").size()).fillna(0)
    check("존재하는 자식 수 기록 일치", parent.child_count.eq(actual_counts).all()
          and parent.absent_child_count.eq(4 - actual_counts).all())
    child_sums = child.groupby("parent_gid").population_estimated.sum(min_count=1)
    actual_sums = parent.gid.map(child_sums)
    check("확정 부모·자식 인구 보존",
          np.allclose(actual_sums[ok], parent.loc[ok, "population_estimated"], rtol=0, atol=EPS)
          and np.allclose(parent.loc[ok, "balance_difference"], 0, rtol=0, atol=EPS))
    ready = parent.aggregation_ready.eq(1)
    check("자식 수와 무관한 집계 가능 판정",
          ready.eq(ok & parent.population_estimated.gt(0)).all())
    weights = child.groupby("parent_gid").aggregation_weight.sum(min_count=1)
    check("양의 인구 부모 가중치 합계 1",
          np.allclose(parent.loc[ready, "gid"].map(weights), 1, rtol=0, atol=EPS)
          and np.allclose(parent.loc[ready, "weight_sum"], 1, rtol=0, atol=EPS))
    child_ready = child.aggregation_ready.eq(1)
    denominators = child.parent_gid.map(parent.set_index("gid").population_estimated)
    check("자식 가중치와 인구 비율 일치",
          np.allclose(child.loc[child_ready, "aggregation_weight"],
                      child.loc[child_ready, "population_estimated"] / denominators[child_ready],
                      rtol=0, atol=EPS))
    check("0명·검토 부모의 가중치 보류", child.loc[child.aggregation_ready.eq(0), "aggregation_weight"].isna().all())
    check("모든 자식의 부모·집계 상태 일치",
          child.parent_gid.isin(parent.gid).all()
          and child.aggregation_ready.equals(child.parent_gid.map(parent.set_index("gid").aggregation_ready)))
    check("검토 목록에 모든 미해결 부모 포함",
          set(reviews.parent_gid) == set(parent.loc[parent.needs_review.eq(1), "gid"]))
    check("격자별 출발점 계산 대상 구분",
          child.origin_required.isin([-1, 0, 1]).all()
          and child.loc[child.population_status.eq("blank_as_zero"), "origin_required"].eq(0).all()
          and child.loc[child.population_status.isin(MASKED), "origin_required"].eq(1).all())
    return checks


def save_result(tables, path, checks):
    hashes = {}
    for name, frame in tables.items():
        kwargs = {"layer": name, "driver": "GPKG"}
        if isinstance(frame, gpd.GeoDataFrame):
            kwargs.update(geometry_type="Polygon", layer_options={"SPATIAL_INDEX": "YES"})
        pyogrio.write_dataframe(frame, path, **kwargs)
    require(set(pyogrio.list_layers(path)[:, 0]) == set(tables), "저장 레이어 목록 불일치")
    for name, frame in tables.items():
        actual = pyogrio.read_dataframe(path, layer=name)
        key = "gid" if "gid" in frame else "parent_gid"
        require(set(actual.columns) == set(frame.columns), f"{name}: 저장 필드 불일치")
        require(len(actual) == len(frame) and content_hash(actual, key) == content_hash(frame, key),
                f"{name}: 저장 후 속성·도형 불일치")
        if isinstance(frame, gpd.GeoDataFrame):
            require(actual.crs.to_epsg() == 5179 and actual.is_valid.all(), "저장 좌표계·도형 오류")
        hashes[name] = content_hash(actual, key)
        checks.append(f"{name} 저장 재읽기 일치")
    with closing(sqlite3.connect(path)) as conn:
        require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "GeoPackage 무결성 오류")
    checks.append("GeoPackage 무결성")
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT/'data')
    data = data_path(parser.parse_args().data_dir)
    raw = data / "raw" / "고령인구"
    paths = {}
    for size in LAYERS:
        matches = [p for p in raw.rglob("vl_blk.shp") if f"{size}M_" in p.parent.name and p.parent.name.endswith(MONTH)]
        require(len(matches) == 1, f"{size}m {MONTH} 원자료는 정확히 한 세트여야 함")
        paths[size] = matches[0]
    before = manifest(paths.values(), data)
    frames = {size: read_grid(path, size, data) for size, path in paths.items()}
    originals = {size: frame[["gid", "lbl", "val", "geometry"]].copy() for size, frame in frames.items()}
    child, parent, reviews = connect_and_estimate(frames[250], frames[500])
    checks = validate_result(child, parent, reviews, originals)
    tables = {LAYERS[250]: child, LAYERS[500]: parent, "review_cases": reviews}
    output = data / "processed"
    output.mkdir(parents=True, exist_ok=True)
    target = output / "elderly_population.gpkg"
    temporary = output / f".elderly_population_{uuid4().hex}.gpkg"
    try:
        hashes = save_result(tables, temporary, checks)
        require(manifest(paths.values(), data) == before, "실행 중 원본 변경")
        checks.append("원본 구성파일 10개 실행 전후 SHA-256 일치")
        temporary.replace(target)
    finally:
        if temporary.is_file():
            temporary.unlink()
    summary = {}
    for name, frame in ((LAYERS[250], child), (LAYERS[500], parent)):
        summary[name] = {
            "count": len(frame), "source_states": frame.population_status.value_counts().to_dict(),
            "group_states": frame.group_status.value_counts().to_dict(),
            "imputed": int(frame.is_imputed.sum()),
            "population_unresolved": int(frame.population_estimated.isna().sum()),
            "population_resolved_sum": float(frame.population_estimated.sum()),
            "ready_for_aggregation": int(frame.aggregation_ready.sum()),
        }
    report = {
        "output": target.relative_to(ROOT).as_posix(), "aggregation_rule": AGGREGATION_RULE, "layers": summary,
        "parent_child_counts": {str(k): int(v) for k, v in parent.child_count.value_counts().sort_index().items()},
        "review_parents": len(reviews), "origin_required": int(child.origin_required.eq(1).sum()),
        "resolved_positive_parent_population_sum": float(parent.loc[parent.aggregation_ready.eq(1), "population_estimated"].sum()),
        "checks_passed": len(checks), "checks": checks, "content_sha256": hashes, "source_sha256": before,
    }
    save_report("elderly_population", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))



if __name__ == "__main__":
    main()

