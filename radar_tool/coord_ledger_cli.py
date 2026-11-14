"""坐标系账本命令行入口（设计文档 8.2，自动化与回归用）。

    python -m radar_tool.coord_ledger_cli check  --ledger ledger.json
    python -m radar_tool.coord_ledger_cli query  --ledger ledger.json --from body --to camera_panchro
    python -m radar_tool.coord_ledger_cli vector --ledger ledger.json --vector "0,0,1" --frame camera_panchro
    python -m radar_tool.coord_ledger_cli loop   --ledger ledger.json
    python -m radar_tool.coord_ledger_cli export --ledger ledger.json --format matrix

不引入独立 CLI 框架，用 stdlib argparse（不新增依赖）。
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .errors import AppError
from .coord_core import Ledger


def _parse_vector(text: str):
    parts = [part.strip() for part in text.replace("，", ",").split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("矢量必须是 3 个分量，如 0,0,1")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"矢量分量不是数值: {text}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coord_ledger_cli",
        description="坐标系账本命令行工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_ledger_arg(command_parser):
        command_parser.add_argument("--ledger", required=True, help="账本 JSON 路径")
        command_parser.add_argument("--status", default=None,
                                    help="状态过滤：design / calibrated / as_built")

    check = sub.add_parser("check", help="校验账本并输出健康度")
    add_ledger_arg(check)

    query = sub.add_parser("query", help="查询两系变换 T_to_from")
    add_ledger_arg(query)
    query.add_argument("--from", dest="from_frame", required=True, help="源系（被变换量所在系）")
    query.add_argument("--to", dest="to_frame", required=True, help="目标系（结果所在系）")
    query.add_argument("--strategy", default="min_error", choices=("min_error", "min_hops"))

    vector = sub.add_parser("vector", help="矢量跨系表达")
    add_ledger_arg(vector)
    vector.add_argument("--vector", required=True, type=_parse_vector, help='矢量，如 "0,0,1"')
    vector.add_argument("--frame", required=True, help="矢量所在系")
    vector.add_argument("--to", dest="targets", action="append", default=None,
                        help="目标系（可重复）；缺省全部坐标系")

    loop = sub.add_parser("loop", help="环路闭合自检")
    add_ledger_arg(loop)

    limits = sub.add_parser("limits", help="限值符合性检查")
    add_ledger_arg(limits)

    compare = sub.add_parser("compare", help="对比两条变换记录")
    add_ledger_arg(compare)
    compare.add_argument("--baseline", required=True, help="基准记录 id（如 design）")
    compare.add_argument("--candidate", required=True, help="对比记录 id（如 calibrated）")

    export = sub.add_parser("export", help="导出矩阵表/坐标系表/代码常量/报告")
    add_ledger_arg(export)
    export.add_argument("--format", default="matrix",
                        choices=("matrix", "frames", "codegen-c", "codegen-python",
                                 "codegen-matlab", "report-md", "review-md"),
                        help="导出格式")
    export.add_argument("--output", default=None, help="输出文件路径（缺省打印到标准输出）")

    return parser


def _cmd_check(ledger: Ledger, args) -> int:
    result = ledger.validate()
    for line in result.errors:
        print(f"[错误] {line}")
    for line in result.warnings:
        print(f"[警告] {line}")
    print(ledger.health_summary())
    return 1 if result.errors else 0


def _cmd_query(ledger: Ledger, args) -> int:
    from .coord_core import formatting as fmt

    result = ledger.query(args.to_frame, args.from_frame, status=args.status,
                          strategy=args.strategy)
    print(f"变换   T_{result.target}_{result.source}（{result.source} → {result.target}）")
    print(f"路径   {fmt.fmt_path(result.path)}")
    print(f"当前值来源   {result.source_line()}")
    print("齐次矩阵")
    print(fmt.fmt_matrix(result.matrix))
    print(f"姿态   {fmt.fmt_euler(result.rpy_deg, order='ZYX', rotation_type='intrinsic', unit='deg')}")
    print(f"       {fmt.fmt_quaternion(result.quaternion, order='wxyz')}")
    print(f"误差   {fmt.fmt_sigma(result.sigma_t_m, result.sigma_r_arcsec)}")
    return 0


def _cmd_vector(ledger: Ledger, args) -> int:
    from .coord_core import formatting as fmt

    expressions = ledger.express_vector(
        args.vector, args.frame, targets=args.targets,
        to_all=args.targets is None,
    )
    print(f"矢量 {tuple(args.vector)} @ {args.frame} 的各系表达")
    for item in expressions:
        print(f"  {item.frame:<18} {fmt.fmt_vec3(item.vector, precision=6)}")
    return 0


def _cmd_loop(ledger: Ledger, args) -> int:
    report = ledger.loop_closure()
    for item in report.items:
        print(item.describe())
    print(report.summary())
    return 0 if report.all_closed else 1


def _cmd_limits(ledger: Ledger, args) -> int:
    report = ledger.check_limits()
    for item in report.items:
        print(item.describe())
    print(report.summary())
    return 0 if report.all_passed else 1


def _cmd_compare(ledger: Ledger, args) -> int:
    result = ledger.compare_transforms(args.baseline, args.candidate)
    for row in result.rows:
        print(f"  {row.label}({row.unit}): δ={row.delta:+.4g} σ={row.sigma:.4g} "
              f"z={row.z:+.3f} [{row.verdict}]")
    print(f"最大偏差项: {result.worst_item} ({result.worst_z:+.3f}σ)")
    print(f"结论: {result.conclusion}")
    for suggestion in result.suggestions:
        print(f"建议: {suggestion}")
    return 1 if result.has_fail() else 0


def _cmd_export(ledger: Ledger, args) -> int:
    fmt = args.format
    if fmt == "matrix":
        import pandas as pd
        from .export_safety import sanitize_dataframe_for_csv

        rows = ledger.export_matrix_table()
        text = sanitize_dataframe_for_csv(pd.DataFrame(rows)).to_csv(index=False)
    elif fmt == "frames":
        import pandas as pd
        from .export_safety import sanitize_dataframe_for_csv

        rows = ledger.export_frames_table()
        text = sanitize_dataframe_for_csv(pd.DataFrame(rows)).to_csv(index=False)
    elif fmt.startswith("codegen-"):
        text = ledger.export_codegen(language=fmt.split("-", 1)[1], status=args.status)
    elif fmt == "report-md":
        text = ledger.export_report_markdown()
    else:
        text = ledger.export_review_markdown(
            compare=ledger.compare_transforms(
                next(r.id for r in ledger.transforms() if r.status == "design"),
                next(r.id for r in ledger.transforms() if r.status == "calibrated"),
            ) if any(r.status == "calibrated" for r in ledger.transforms()) else None,
            loops=ledger.loop_closure(),
            limits=ledger.check_limits(),
        )
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        print(f"已写入 {args.output}")
    else:
        print(text)
    return 0


_COMMANDS = {
    "check": _cmd_check,
    "query": _cmd_query,
    "vector": _cmd_vector,
    "loop": _cmd_loop,
    "limits": _cmd_limits,
    "compare": _cmd_compare,
    "export": _cmd_export,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        ledger = Ledger.load(args.ledger)
        if args.status:
            ledger.build_graph(args.status)
        return _COMMANDS[args.command](ledger, args)
    except (AppError, OSError, ValueError) as exc:
        message = getattr(exc, "user_message", None) or str(exc)
        print(f"错误: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
