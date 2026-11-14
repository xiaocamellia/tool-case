"""坐标系账本单元测试（设计文档 12.2 用例 T1–T13）。"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from radar_tool.coord_core import (
    Ledger,
    SCHEMA_VERSION,
    make_sample_document,
)
from radar_tool.coord_core import codegen as codegen_module
from radar_tool.coord_core import conventions as conv
from radar_tool.coord_core import report as report_module
from radar_tool.coord_core.compare import compare_transform_records
from radar_tool.coord_core.graph import TransformGraph
from radar_tool.coord_core.schema import LedgerDocument, TransformRecord
from radar_tool.coord_core.transforms import (
    Attitude,
    invert_transform,
    make_transform,
)
from radar_tool.errors import ValidationError

ARCSEC_PER_RAD = 180.0 * 3600.0 / math.pi


def _identity_record(record_id="T_ab_id", from_frame="a", to_frame="b", **overrides):
    payload = {
        "id": record_id,
        "from": from_frame,
        "to": to_frame,
        "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "translation": [0, 0, 0],
        "sigma": {"t": 0.0, "r_arcsec": 0.0},
        "status": "design",
    }
    payload.update(overrides)
    return TransformRecord.from_dict(payload)


def _two_frame_ledger(record_payloads, limits=None):
    payload = {
        "schema": "coordinate_ledger",
        "schema_version": SCHEMA_VERSION,
        "ledger": {"name": "t", "version": "1.0"},
        "frames": [
            {"id": "a", "axis": "Z_UP"},
            {"id": "b", "axis": "Z_UP"},
            {"id": "c", "axis": "Z_UP"},
        ],
        "transforms": record_payloads,
        "limits": limits or [],
    }
    return Ledger.from_dict(payload)


# ---------------------------------------------------------------------------
# T1 矩阵求逆闭合
# ---------------------------------------------------------------------------


def test_t1_inverse_closure():
    attitude = Attitude.from_euler([12.5, -33.0, 71.2], "ZYX", "intrinsic", "deg")
    transform = make_transform(attitude, [0.3, -1.2, 4.5])
    product = transform @ invert_transform(transform)
    assert np.max(np.abs(product - np.eye(4))) < 1e-12


# ---------------------------------------------------------------------------
# T2 姿态互转往返（12 顺序 × 内/外旋）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "order",
    ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX", "XYX", "XZX", "YXY", "YZY", "ZXZ", "ZYZ"],
)
@pytest.mark.parametrize("rotation_type", ["intrinsic", "extrinsic"])
def test_t2_attitude_roundtrip(order, rotation_type):
    angles = (15.0, -25.0, 35.0)
    attitude = Attitude.from_euler(angles, order, rotation_type, "deg")
    recovered = attitude.euler(order, rotation_type, "deg")
    # 先转回矩阵比较，避免奇异处角度等价类差异
    original_matrix = Attitude.from_euler(angles, order, rotation_type, "deg").matrix()
    recovered_matrix = Attitude.from_euler(recovered, order, rotation_type, "deg").matrix()
    assert np.max(np.abs(original_matrix - recovered_matrix)) < 1e-10

    quat = attitude.quaternion_wxyz()
    from_quat = Attitude.from_quaternion(quat, "wxyz")
    assert np.max(np.abs(from_quat.matrix() - attitude.matrix())) < 1e-12

    rotvec = attitude.rotvec("rad")
    from_vec = Attitude.from_rotvec(rotvec, "rad")
    assert np.max(np.abs(from_vec.matrix() - attitude.matrix())) < 1e-12


# ---------------------------------------------------------------------------
# T3 scipy 序列映射（手算 3 例）
# ---------------------------------------------------------------------------


def test_t3_scipy_mapping_zyx_intrinsic():
    # value = [α, β, γ] = [绕X, 绕Y, 绕Z]；ZYX intrinsic → scipy 'zyx'
    assert conv.to_scipy_seq("ZYX", "intrinsic") == "zyx"
    assert conv.to_scipy_seq("ZYX", "extrinsic") == "ZYX"

    case_z = Attitude.from_euler([0, 0, 90], "ZYX", "intrinsic", "deg").matrix()
    expected_z = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    assert np.allclose(case_z, expected_z, atol=1e-12)

    case_y = Attitude.from_euler([0, 90, 0], "ZYX", "intrinsic", "deg").matrix()
    expected_y = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float)
    assert np.allclose(case_y, expected_y, atol=1e-12)

    case_x = Attitude.from_euler([90, 0, 0], "ZYX", "intrinsic", "deg").matrix()
    expected_x = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
    assert np.allclose(case_x, expected_x, atol=1e-12)

    # 与四元数 [0.7071, 0, 0, 0.7071]（wxyz，绕 Z 90°）一致
    quat_case = Attitude.from_quaternion([math.cos(math.pi / 4), 0, 0, math.sin(math.pi / 4)], "wxyz")
    assert np.allclose(quat_case.matrix(), expected_z, atol=1e-12)


def test_t3_missing_convention_is_error():
    with pytest.raises(ValidationError):
        Attitude.from_euler([0, 0, 90], "ZYX", None, "deg")
    with pytest.raises(ValidationError):
        Attitude.from_euler([0, 0, 90], None, "intrinsic", "deg")


# ---------------------------------------------------------------------------
# T4 多跳合成（手工几何）
# ---------------------------------------------------------------------------


def test_t4_multihop_composition():
    # a→b：绕 Z 90°；b→c：沿 X 平移 1m；c→a：恒等逆
    records = [
        {
            "id": "T_a_b", "from": "a", "to": "b",
            "rotation": {"type": "matrix", "value": [0, -1, 0, 1, 0, 0, 0, 0, 1]},
            "translation": [0, 0, 0], "status": "design",
        },
        {
            "id": "T_b_c", "from": "b", "to": "c",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [1, 0, 0], "status": "design",
        },
    ]
    led = _two_frame_ledger(records)
    result = led.query("a", "c")          # T_a_c = T_a_b · T_b_c
    expected = np.array([
        [0, -1, 0, 0],
        [1, 0, 0, 1],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ], dtype=float)
    assert np.allclose(result.matrix, expected, atol=1e-12)
    assert result.path == ["c", "b", "a"]


# ---------------------------------------------------------------------------
# T5 反向路径互逆
# ---------------------------------------------------------------------------


def test_t5_reverse_path_inverse():
    led = Ledger.sample()
    forward = led.query("body", "camera_panchro").matrix
    backward = led.query("camera_panchro", "body").matrix
    assert np.max(np.abs(forward @ backward - np.eye(4))) < 1e-12


# ---------------------------------------------------------------------------
# T6 误差传播 RSS
# ---------------------------------------------------------------------------


def test_t6_error_budget_rss():
    records = [
        {
            "id": "T_a_b", "from": "a", "to": "b",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [0, 0, 0], "status": "design",
            "sigma": {"t": 0.003, "r_arcsec": 3.0},
        },
        {
            "id": "T_b_c", "from": "b", "to": "c",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [0, 0, 0], "status": "design",
            "sigma": {"t": 0.004, "r_arcsec": 4.0},
        },
    ]
    led = _two_frame_ledger(records)
    budget = led.error_budget("a", "c")
    assert budget.sigma_r_total_arcsec == pytest.approx(5.0, rel=1e-12)
    assert budget.sigma_t_total_m == pytest.approx(0.005, rel=1e-12)
    assert budget.segments[0].record_id == "T_b_c"      # 占比 16/25 最大
    assert budget.dominant_share == pytest.approx(16 / 25, rel=1e-12)


# ---------------------------------------------------------------------------
# T7 变换对比（分量级 δr/δt + z 判定 + 最大偏差项）
# ---------------------------------------------------------------------------


def test_t7_compare_components_and_verdicts():
    baseline = _identity_record(
        "T_a_b_design", sigma={"t": 0.001, "r_arcsec": 2.0}, status="design",
    )
    # 绕 Z 5″ + Y 向平移 2mm，其余为 0
    rot_z = Attitude.from_rotvec([0, 0, 5.0 / ARCSEC_PER_RAD], "rad")
    candidate = TransformRecord.from_dict({
        "id": "T_a_b_cal",
        "from": "a", "to": "b",
        "rotation": {"type": "matrix", "value": list(rot_z.matrix().reshape(-1))},
        "translation": [0, 0.002, 0],
        "sigma": {"t": 0.001, "r_arcsec": 2.0},
        "status": "calibrated",
    })
    result = compare_transform_records(baseline, candidate)

    assert result.delta_rot_arcsec[2] == pytest.approx(5.0, rel=1e-6)
    assert result.delta_rot_arcsec[0] == pytest.approx(0.0, abs=1e-6)
    assert result.delta_trans_mm[1] == pytest.approx(2.0, rel=1e-6)
    assert result.delta_trans_mm[0] == pytest.approx(0.0, abs=1e-6)

    assert result.z_scores["rot_z"] == pytest.approx(2.5, rel=1e-6)   # 5/2
    assert result.z_scores["trans_y"] == pytest.approx(2.0, rel=1e-6)  # 2/1
    assert result.verdicts["rot_z"] == "warn"
    assert result.verdicts["trans_y"] == "warn"
    assert result.verdicts["rot_x"] == "ok"
    assert result.worst_item == "rot_z"
    assert "rot_z" in result.conclusion or "绕Z" in result.conclusion
    assert result.overall == "warn"

    # 注入 10″ → fail
    rot_bad = Attitude.from_rotvec([0, 0, 10.0 / ARCSEC_PER_RAD], "rad")
    candidate_bad = TransformRecord.from_dict({
        "id": "T_a_b_bad", "from": "a", "to": "b",
        "rotation": {"type": "matrix", "value": list(rot_bad.matrix().reshape(-1))},
        "translation": [0, 0, 0],
        "sigma": {"t": 0.001, "r_arcsec": 2.0},
        "status": "calibrated",
    })
    bad = compare_transform_records(baseline, candidate_bad)
    assert bad.verdicts["rot_z"] == "fail"
    assert bad.has_fail()


# ---------------------------------------------------------------------------
# T8 环路闭合
# ---------------------------------------------------------------------------


def test_t8_loop_closure_self_consistent():
    """design 值精确自洽：e_rot < 1e-6 ″。"""
    led = Ledger.sample()
    graph = TransformGraph(led.document, status="design")
    from radar_tool.coord_core.compare import loop_closure

    report = loop_closure(led.document, graph, sigma_multiplier=3.0)
    assert report.total >= 1
    for item in report.items:
        assert item.e_rot_arcsec < 1e-6
        assert item.e_trans_mm < 1e-6
        assert item.closed


def test_t8_loop_detects_injected_perturbation():
    records = [
        {
            "id": "T_a_b", "from": "a", "to": "b",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [1, 0, 0], "status": "design",
            "sigma": {"t": 0.001, "r_arcsec": 1.0},
        },
        {
            "id": "T_b_c", "from": "b", "to": "c",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [1, 0, 0], "status": "design",
            "sigma": {"t": 0.001, "r_arcsec": 1.0},
        },
        {
            # T_c_a 应为 [-2,0,0]；注入 +1mm 平移扰动与 30″ 旋转扰动
            "id": "T_c_a", "from": "c", "to": "a",
            "rotation": {"type": "rpy", "value": [0, 0, 30], "order": "ZYX",
                         "rotation_type": "intrinsic", "unit": "deg"},
            "translation": [-2.001, 0, 0], "status": "design",
            "sigma": {"t": 0.001, "r_arcsec": 1.0},
        },
    ]
    led = _two_frame_ledger(records)
    report = led.loop_closure()
    assert report.total == 1
    item = report.items[0]
    assert not item.closed
    assert item.e_rot_arcsec > 1000          # 30° ≈ 108000″，必然超差
    assert not report.all_closed


# ---------------------------------------------------------------------------
# T9 指向计算
# ---------------------------------------------------------------------------


def test_t9_pointing_aligned_target():
    led = Ledger.sample()
    # 相机视轴 = camera 系 +Z；目标沿 body Z（相机对地方向）→ 偏离角应≈0
    result = led.pointing("camera_panchro", axis=[0, 0, 1],
                          target_dir=[0, 0, 1], ref="body", status="design")
    assert result.deviation_deg < 5.7e-5          # 1e-6 rad


def test_t9_pointing_known_offset():
    led = Ledger.sample()
    # 目标沿 body −Y（与对地方向垂直）→ 偏离角 90°
    result = led.pointing("camera_panchro", axis=[0, 0, 1],
                          target_dir=[0, -1, 0], ref="body", status="design")
    assert result.deviation_deg == pytest.approx(90.0, abs=0.01)


# ---------------------------------------------------------------------------
# T10 校验器
# ---------------------------------------------------------------------------


def test_t10_validator_detects_errors():
    payload = make_sample_document().to_dict()
    payload["transforms"].append(dict(payload["transforms"][0]))       # 重复 id
    payload["transforms"].append({
        "id": "T_body_ghost", "from": "body", "to": "ghost_frame",     # 引用缺失
        "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "translation": [0, 0, 0], "status": "design",
    })
    payload["transforms"].append({
        "id": "T_body_badrot", "from": "body", "to": "camera_panchro",
        "rotation": {"type": "matrix", "value": [1, 0.2, 0, 0, 1, 0, 0, 0, 1]},  # 非正交
        "translation": [0, 0, 0], "status": "design",
    })
    document = LedgerDocument.from_dict(payload)
    result = document.validate()
    text = "\n".join(result.errors)
    assert "重复" in text
    assert "ghost_frame" in text
    assert "正交归一" in text


def test_t10_validator_rejects_bad_rotation_spec():
    record = {
        "id": "T_a_b", "from": "a", "to": "b",
        "rotation": {"type": "rpy", "value": [0, 0, 90]},   # 缺 order / rotation_type
        "translation": [0, 0, 0], "status": "design",
    }
    led = _two_frame_ledger([record])
    result = led.validate()
    assert not result.ok
    assert any("姿态非法" in line or "必填" in line for line in result.errors)


# ---------------------------------------------------------------------------
# T11 多状态选取规则
# ---------------------------------------------------------------------------


def test_t11_multi_status_selection():
    records = [
        {
            "id": "T_a_b_design", "from": "a", "to": "b",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [0, 0, 0], "status": "design",
        },
        {
            "id": "T_a_b_cal", "from": "a", "to": "b",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [0.1, 0, 0], "status": "calibrated",
        },
        {
            "id": "T_a_b_old", "from": "a", "to": "b",
            "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "translation": [9, 9, 9], "status": "obsolete",
        },
    ]
    led = _two_frame_ledger(records)

    current = led.current_record("a", "b")
    assert current.id == "T_a_b_cal"                    # calibrated > design

    filtered = led.current_record("a", "b", status="design")
    assert filtered.id == "T_a_b_design"

    # obsolete 永不自动选中
    assert led.current_record("a", "b", status=None).status != "obsolete"

    result = led.query("b", "a")
    assert result.transform_id == "T_a_b_cal"
    assert result.status == "calibrated"
    assert "T_a_b_cal" in result.source_line()

    # 显式指定 design
    result_design = led.query("b", "a", status="design")
    assert result_design.transform_id == "T_a_b_design"

    # as_built 优先级最高
    extra = TransformRecord.from_dict({
        "id": "T_a_b_built", "from": "a", "to": "b",
        "rotation": {"type": "matrix", "value": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "translation": [0.2, 0, 0], "status": "as_built",
    })
    led.document.transforms.append(extra)
    assert led.current_record("a", "b").id == "T_a_b_built"


# ---------------------------------------------------------------------------
# T12 单位换算
# ---------------------------------------------------------------------------


def test_t12_unit_conversions():
    assert conv.angle_to_radians(180.0, "deg") == pytest.approx(math.pi, rel=1e-12)
    assert conv.angle_to_arcsec(1.0, "deg") == pytest.approx(3600.0, rel=1e-12)
    assert conv.angle_to_arcsec(1.0, "rad") == pytest.approx(ARCSEC_PER_RAD, rel=1e-9)
    assert conv.angle_from_arcsec(3600.0, "deg") == pytest.approx(1.0, rel=1e-12)
    assert conv.length_to_meters(1000.0, "mm") == pytest.approx(1.0)
    assert conv.length_to_mm(-1.5, "m") == pytest.approx(-1500.0)
    assert conv.length_from_meters(conv.length_to_meters(250.0, "mm"), "mm") == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# T13 批量转换 = 逐点循环
# ---------------------------------------------------------------------------


def test_t13_batch_equals_loop():
    led = Ledger.sample()
    rng = np.random.default_rng(42)
    points = rng.normal(size=(1000, 3))
    batch = led.transform_points(points, "camera_panchro", "body").points
    looped = np.array([
        led.transform_point(point, "camera_panchro", "body") for point in points
    ])
    assert batch.shape == (1000, 3)
    assert np.max(np.abs(batch - looped)) < 1e-12


# ---------------------------------------------------------------------------
# 存储 / 模板 / 导出
# ---------------------------------------------------------------------------


def test_storage_roundtrip(tmp_path):
    led = Ledger.sample()
    filepath = str(tmp_path / "ledger_test_v1.0.json")
    led.save(filepath)
    loaded = Ledger.load(filepath)
    assert loaded.validate().ok
    assert len(loaded.frames()) == len(led.frames())
    assert loaded.document.to_dict() == led.document.to_dict()


def test_storage_backup_on_save(tmp_path):
    led = Ledger.sample()
    filepath = str(tmp_path / "ledger_test_v1.0.json")
    led.save(filepath)
    led.save(filepath)
    assert os.path.isfile(filepath + ".bak")


def test_storage_quarantine_corrupt(tmp_path):
    filepath = str(tmp_path / "broken.json")
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    with pytest.raises(ValidationError):
        Ledger.load(filepath)
    leftovers = [name for name in os.listdir(tmp_path) if name.startswith("broken.json.corrupt-")]
    assert leftovers


def test_template_and_blank(tmp_path):
    filepath = str(tmp_path / "template.json")
    Ledger.blank().export_template(filepath, sample=True)
    loaded = Ledger.load(filepath)
    assert loaded.validate().ok
    assert loaded.document.transforms


def test_codegen_names():
    name = codegen_module.constant_name("body", "camera_panchro", "calibrated")
    assert name == "T_BODY_CAMERA_PANCHRO_CALIBRATED"
    assert codegen_module.constant_name("body", "cam", "design") == "T_BODY_CAM"


def test_codegen_languages_render():
    led = Ledger.sample()
    for language in ("python", "c", "matlab"):
        text = led.export_codegen(language)
        assert "T_BODY_CAMERA_PANCHRO_CALIBRATED" in text or "T_BODY" in text


def test_report_exports(tmp_path):
    led = Ledger.sample()
    markdown = led.export_report_markdown(
        query_result=led.query("body", "camera_panchro"),
        budget=led.error_budget("body", "camera_panchro"),
    )
    assert "当前值来源" in markdown
    assert "误差预算" in markdown

    review = led.export_review_markdown(
        compare=led.compare_transforms("T_body_cam_design", "T_body_cam_cal_202605"),
        loops=led.loop_closure(),
        limits=led.check_limits(),
    )
    assert "结论" in review
    assert "环路" in review

    docx_path = str(tmp_path / "report.docx")
    report_module.write_transform_report_word(
        led, docx_path, query_result=led.query("body", "camera_panchro"),
    )
    assert os.path.isfile(docx_path)

    csv_path = str(tmp_path / "matrix.csv")
    report_module.write_rows_csv(led.export_matrix_table(), csv_path)
    assert os.path.getsize(csv_path) > 0


def test_sample_ledger_health():
    led = Ledger.sample()
    assert led.validate().ok
    loops = led.loop_closure()
    assert loops.all_closed
    limits = led.check_limits()
    assert limits.all_passed
    summary = led.health_summary()
    assert "环路 1/1 闭合" in summary


def test_vector_expression_consistency():
    led = Ledger.sample()
    expressions = led.express_vector([0, 0, 1], "camera_panchro", to_all=True)
    by_frame = {item.frame: np.array(item.vector) for item in expressions}
    # 往返：body → camera → body 应还原
    back = led.transform_vector(by_frame["body"], "body", "camera_panchro")
    assert np.max(np.abs(np.array(back) - np.array([0, 0, 1]))) < 1e-9


# ---------------------------------------------------------------------------
# D3 / D5 / A6 批量转换 · 姿态反算 · 批量导入
# ---------------------------------------------------------------------------


def test_d3_batch_table_matches_points():
    led = Ledger.sample()
    points = np.array([[0, 0, 0], [1, 2, 3], [-0.5, 0.25, 1.0]])
    rows = led.transform_points_table(points, "camera_panchro", "body")
    assert len(rows) == 3
    for row, point in zip(rows, points):
        direct = led.transform_point(point, "camera_panchro", "body")
        assert row["x_out"] == pytest.approx(direct[0], abs=1e-12)
        assert row["y_out"] == pytest.approx(direct[1], abs=1e-12)
        assert row["z_out"] == pytest.approx(direct[2], abs=1e-12)


def test_d3_transform_csv_file(tmp_path):
    import pandas as pd

    led = Ledger.sample()
    input_path = str(tmp_path / "points.csv")
    output_path = str(tmp_path / "out.csv")
    pd.DataFrame({"x": [0, 1], "y": [0, 0], "z": [1, 0]}).to_csv(input_path, index=False)
    led.transform_csv_file(input_path, output_path, "camera_panchro", "body")
    result = pd.read_csv(output_path)
    assert set(result.columns) >= {"x_in", "y_in", "z_in", "x_out", "y_out", "z_out"}
    assert len(result) == 2


def test_d5_required_body_attitude():
    led = Ledger.sample()
    quat = led.required_body_attitude(
        "camera_panchro", axis=[0, 0, 1], target_dir=[0, 0, 1], ref="body",
        status="design",
    )
    # 目标沿 body Z 时，所需姿态应接近恒等（相机已对地）
    attitude = Attitude.from_quaternion(quat, "wxyz")
    expected = Attitude.identity().matrix()
    assert np.max(np.abs(attitude.matrix() - expected)) < 1e-3

    # 目标沿 body X 时：R_body_ref · target 应等于视轴在本体系方向 (0,0,1)
    quat2 = led.required_body_attitude(
        "camera_panchro", axis=[0, 0, 1], target_dir=[1, 0, 0], ref="body",
        status="design",
    )
    attitude2 = Attitude.from_quaternion(quat2, "wxyz")
    rotated = attitude2.apply([1, 0, 0])
    assert rotated == pytest.approx([0, 0, 1], abs=1e-9)


def test_a6_import_transforms_csv(tmp_path):
    import pandas as pd

    led = Ledger.blank("导入测试")
    led.document.frames.extend(Ledger.sample().frames())
    csv_path = str(tmp_path / "transforms.csv")
    pd.DataFrame([
        {
            "id": "T_body_x1", "from": "body", "to": "camera_panchro",
            "qw": 1.0, "qx": 0.0, "qy": 0.0, "qz": 0.0,
            "tx": 0.1, "ty": 0.2, "tz": 1.0,
            "sigma_t": 0.001, "sigma_r_arcsec": 2.0,
            "status": "design", "source": "CAD-01",
        },
    ]).to_csv(csv_path, index=False)
    added = led.import_transforms_csv(csv_path)
    assert added == ["T_body_x1"]
    record = led.document.transform_map()["T_body_x1"]
    assert record.translation == pytest.approx((0.1, 0.2, 1.0))
    assert record.source == "CAD-01"
    # 重复导入应报错
    with pytest.raises(ValidationError):
        led.import_transforms_csv(csv_path)


def test_d5_and_cli_roundtrip(tmp_path):
    """CLI 与 SDK 输出一致（回归基准雏形）。"""
    from radar_tool.coord_ledger_cli import main

    ledger_path = str(tmp_path / "ledger.json")
    Ledger.sample().save(ledger_path)
    assert main(["check", "--ledger", ledger_path]) == 0
    assert main(["loop", "--ledger", ledger_path]) == 0
    assert main(["limits", "--ledger", ledger_path]) == 0


# ---------------------------------------------------------------------------
# 可读性格式化（不倾倒原始 tuple / dict）
# ---------------------------------------------------------------------------


def test_express_vector_skips_unreachable_frames():
    """删除变换导致坐标系孤立后，跨全部系表达应跳过该系而非报错。"""
    led = Ledger.sample()
    led.document.transforms = [
        record for record in led.transforms() if record.id != "T_body_sar_design"
    ]
    led.invalidate()
    items = led.express_vector([0, 0, 1], "body", to_all=True)
    frames = [item.frame for item in items]
    assert "camera_panchro" in frames
    assert "sar_antenna" not in frames
    # 显式指定孤立系仍应报错（用户点名的转换必须可解释）
    with pytest.raises(ValidationError):
        led.express_vector([0, 0, 1], "body", targets=["sar_antenna"])


def test_formatting_helpers():
    from radar_tool.coord_core import formatting as fmt

    assert fmt.fmt_number(0.0010000000000037544) == "0.001"
    assert fmt.fmt_number(2.15397043e-10) == "0"
    assert fmt.fmt_euler([0.001, -0.001, 89.998]) == (
        "欧拉角 ZYX·内旋（deg）：绕X=0.001°, 绕Y=-0.001°, 绕Z=89.998°"
    )
    text = fmt.fmt_quaternion([0.7071068, 0.0, 0.0, 0.7071068])
    assert text == "四元数（wxyz）：w=0.707107, x=0.000000, y=0.000000, z=0.707107"
    assert fmt.fmt_translation((0.0, 0.002, 1.201)) == "X=0.000, Y=2.000, Z=1201.000 mm"
    assert fmt.fmt_status("calibrated") == "标定值 · calibrated"
    assert fmt.fmt_frame_pair(("camera_panchro", "sar_antenna")) == "camera_panchro ↔ sar_antenna"

    led = Ledger.sample()
    detail = fmt.transform_detail(led.document.get_transform("T_body_cam_cal_202605"))
    assert "标定值 · calibrated" in detail
    assert "平移   X=0.000, Y=2.000, Z=1201.000 mm" in detail
    assert "{" not in detail and "''" not in detail        # 无 dict/tuple 倾倒
    limit_text = fmt.limit_detail(led.limits()[0])
    assert "两轴夹角" in limit_text and "↔" in limit_text


def test_formatting_result_blocks():
    from radar_tool.coord_core import formatting as fmt

    led = Ledger.sample()
    query_text = fmt.query_result_text(led.query("body", "camera_panchro"))
    assert "齐次矩阵" in query_text and "当前值来源" in query_text
    assert "{" not in query_text

    compare_text = fmt.comparison_result_text(
        led.compare_transforms("T_body_cam_design", "T_body_cam_cal_202605")
    )
    assert "分量" in compare_text and "z=δ/σ" in compare_text
    assert "最大偏差项" in compare_text
    assert "正常" in compare_text or "关注" in compare_text

    budget_text = fmt.error_budget_result_text(led.error_budget("body", "camera_panchro"))
    assert "方差占比" in budget_text and "合成（RSS）" in budget_text

    loop_text = fmt.loop_report_text(led.loop_closure())
    assert "e_rot" in loop_text and "闭合 ✓" in loop_text

    limit_text = fmt.limit_report_text(led.check_limits())
    assert "通过 ✓" in limit_text and "LIM_cam_sar_angle" in limit_text

    # 中英混排表格按显示宽度对齐
    table = fmt.text_table(["名称", "值"], [["中文列", "1"], ["b", "22"]])
    lines = table.splitlines()
    assert lines[0].startswith("名称")
    assert "│" not in table        # 纯文本分隔
    widths = {fmt._display_width(line) for line in lines}
    assert len(widths) == 1        # 各行等宽


# ---------------------------------------------------------------------------
# 12.3 回归基准：golden_ledger.json + golden_results.json
# ---------------------------------------------------------------------------


def test_golden_regression():
    import json

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    with open(os.path.join(data_dir, "golden_ledger.json"), encoding="utf-8") as handle:
        led = Ledger.from_dict(json.load(handle))
    with open(os.path.join(data_dir, "golden_results.json"), encoding="utf-8") as handle:
        golden = json.load(handle)

    tf = led.query("body", "camera_panchro")
    assert np.allclose(tf.matrix, golden["query_body_cam_matrix"], atol=1e-12)
    assert np.allclose(tf.rpy_deg, golden["query_rpy_deg"], atol=1e-9)

    cmp = led.compare_transforms("T_body_cam_design", "T_body_cam_cal_202605")
    assert cmp.worst_item == golden["compare_worst_item"]
    assert np.allclose(cmp.delta_rot_arcsec, golden["compare_delta_rot_arcsec"], atol=1e-6)
    for key, value in golden["compare_z_scores"].items():
        assert cmp.z_scores[key] == pytest.approx(value, rel=1e-9, abs=1e-9)

    loops = led.loop_closure()
    assert loops.items[0].closed == golden["loop_closed"]
    assert loops.items[0].e_rot_arcsec == pytest.approx(
        golden["loop_e_rot_arcsec"], rel=1e-9, abs=1e-9
    )

    lim = led.check_limits()
    assert lim.items[0].computed == pytest.approx(
        golden["limit_computed_deg"], rel=1e-9, abs=1e-9
    )

    budget = led.error_budget("body", "camera_panchro")
    assert budget.sigma_r_total_arcsec == pytest.approx(
        golden["budget_sigma_r_total_arcsec"], rel=1e-12
    )
