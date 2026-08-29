"""PicRename AI 命令行入口：参数解析、API key 优先级、退出码、tags/undo 装配。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from .pipeline import UNDO_MAP_NAME, PipelineConfig, run_pipeline
from .undo import undo_from_map

DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
KEY_NAMES = ("PICREN_API_KEY", "PICRENAME_API_KEY", "API_KEY")  # 首选专用名，旧名向后兼容

KEY_HINT = (
    "[picren] 错误：未找到 API Key，无法调用视觉模型。\n"
    "  请用以下任一方式提供：\n"
    "    1) 命令行参数：--api-key <你的Key>\n"
    "    2) 环境变量：API_KEY=<你的Key>\n"
    "    3) 工作目录 .env 文件写入：API_KEY=sk-xxx\n"
    "  提示：图片会压缩至最长边 800px 后发送给第三方模型服务；\n"
    "  本地模型（如 Ollama）可传 --api-key ollama。"
)


class _UsageError(Exception):
    """参数错误（退出码 1）。"""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError(message)


def _build_parser() -> _Parser:
    p = _Parser(prog="picren",
                description="图片批量 AI 重命名/整理器（PicRename AI）")
    p.add_argument("--dir", help="图片目录")
    p.add_argument("--recursive", action="store_true", help="递归子目录")
    p.add_argument("--pattern", action="append", default=[],
                   help="扩展名/通配模式，可重复（如 *.jpg）")
    p.add_argument("--template", default="{date}_{category}_{subject}_{index}.{ext}",
                   help="命名模板")
    p.add_argument("--tags-only", action="store_true", help="只生成 tags.csv，不改名")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="仅预览，不写盘（默认模式）")
    mode.add_argument("--execute", action="store_true", help="真实执行（先自动预览）")
    p.add_argument("--undo", action="store_true", help="回滚最近的 rename_map.csv")
    p.add_argument("--move-by-category", action="store_true", help="按类别移入子目录")
    p.add_argument("--keep-original", action="store_true", default=True,
                   help="目标名保留原名以可回溯（默认开启）")
    p.add_argument("--no-keep-original", dest="keep_original", action="store_false")
    p.add_argument("--api-base", default=DEFAULT_API_BASE, help="OpenAI 兼容 API 地址")
    p.add_argument("--model", default=DEFAULT_MODEL, help="视觉模型名")
    p.add_argument("--api-key", default=None, help="API key（也可用环境变量/.env）")
    p.add_argument("--workers", type=int, default=4, help="并发线程数")
    p.add_argument("--max-fail-ratio", type=float, default=0.2,
                   help="识别失败比例阈值，超过则中止")
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return p


def _read_dotenv_key() -> str:
    """从工作目录 .env 中读取 API_KEY（手写 dotenv，不引依赖）。"""
    path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() in KEY_NAMES and v.strip():
                    return v.strip()
    except OSError:
        return ""
    return ""


def _load_api_key(cli_key) -> str:
    """key 优先级：--api-key > 环境变量 > .env 文件。"""
    if cli_key:
        return cli_key
    for name in KEY_NAMES:
        v = os.environ.get(name)
        if v:
            return v
    return _read_dotenv_key()


def _iter_plan(planned):
    """把 planned 元素统一为 (src, dst) 元组（兼容 RenameOp 与二元组）。"""
    for item in planned:
        if hasattr(item, "src_abs"):
            yield item.src_abs, item.dst_abs
        else:
            yield item


def _format_plan(planned) -> str:
    """把 [(src, dst)] 渲染成对齐的文本表。"""
    if not planned:
        return "  （无）"
    items = list(_iter_plan(planned))
    width = max((len(str(s)) for s, _ in items), default=0)
    lines = [f"  {src:<{width}}  ->  {dst}" for src, dst in items]
    return "\n".join(lines)


def _write_tags_csv(directory: str, report) -> str:
    """写 tags.csv（文件名,日期,类别,主题,场景,置信度）。"""
    path = os.path.join(directory, "tags.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["文件名", "日期", "类别", "主题", "场景", "置信度"])
        for img, result in (report.tagged or []):
            rel = os.path.relpath(img.path, directory)
            date = img.taken_at.strftime("%Y-%m-%d") if img.taken_at else ""
            w.writerow([rel, date, result.category, result.subject,
                        result.scene, f"{result.confidence:.2f}"])
    return path


def _report_to_json(report) -> dict:
    """把 PipelineReport 序列化为 JSON 可打印结构。"""
    executed = None
    if report.executed is not None:
        executed = {
            "renamed": report.executed.renamed,
            "failed": [[src, str(err)] for src, err in report.executed.failed],
        }
    return {
        "planned": [[src, dst] for src, dst in _iter_plan(report.planned)],
        "executed": executed,
        "failed": [[path, err] for path, err in report.failed],
        "tags": [
            {"subject": t.subject, "category": t.category, "scene": t.scene,
             "confidence": t.confidence}
            for t in report.tags
        ],
        "elapsed_s": round(report.elapsed_s, 3),
    }


def _cmd_undo(args) -> int:
    """--undo：读取目录下最近的 rename_map.csv 回滚。"""
    directory = args.dir or os.getcwd()
    map_path = os.path.join(directory, UNDO_MAP_NAME)
    if not os.path.exists(map_path):
        print(f"[picren] 未找到回滚映射：{map_path}", file=sys.stderr)
        return 1
    stats = undo_from_map(map_path)
    print(f"[picren] 已回滚 {stats.renamed} 个文件"
          + (f"，失败 {len(stats.failed)} 个" if stats.failed else ""))
    for src, err in stats.failed:
        print(f"  - {src}: {err}", file=sys.stderr)
    return 0


def _cmd_run(args) -> int:
    """--dir 主流程：校验→建配置→跑管道→按退出码/模式输出。"""
    if not args.dir:
        raise _UsageError("缺少必选参数 --dir")
    if not os.path.isdir(args.dir):
        raise _UsageError(f"目录不存在：{args.dir}")
    key = _load_api_key(args.api_key)
    if not key:
        print(KEY_HINT, file=sys.stderr)
        return 1
    cfg = PipelineConfig(
        directory=args.dir,
        recursive=args.recursive,
        patterns=args.pattern or None,
        template=args.template,
        dry_run_first=not args.execute,  # 默认 dry-run；--execute 才落盘（--dry-run 与其互斥）
        workers=max(1, args.workers),
        api_base=args.api_base,
        model=args.model,
        api_key=key,
        move_by_category=args.move_by_category,
        keep_original=args.keep_original,
        max_fail_ratio=args.max_fail_ratio,
    )
    report = run_pipeline(cfg)
    total = len(report.failed) + len(report.tags)
    if total == 0:
        print(f"[picren] 未找到匹配的图片文件：{args.dir}", file=sys.stderr)
        return 2
    fail_ratio = len(report.failed) / total
    if fail_ratio > cfg.max_fail_ratio:
        print(f"[picren] 识别质量过低（失败 {len(report.failed)}/{total}），已中止；"
              f"阈值 {cfg.max_fail_ratio:.0%}", file=sys.stderr)
        for path, err in report.failed[:5]:
            print(f"  - {path}: {err}", file=sys.stderr)
        return 3
    if args.tags_only:
        path = _write_tags_csv(args.dir, report)
        print(f"[picren] 已生成 {path}（{len(report.tags)} 行），未改名")
        return 0
    if args.json:
        print(json.dumps(_report_to_json(report), ensure_ascii=False, indent=2))
        return 0
    mode = "干跑预览（未修改任何文件）" if not args.execute else "执行前预览"
    print(f"[picren] 收集 {total} 张，成功识别 {len(report.tags)} 张"
          f"（失败 {len(report.failed)}），耗时 {report.elapsed_s:.1f}s：{mode}")
    print(_format_plan(report.planned))
    if args.execute:
        stats = report.executed
        if stats is None:
            print("[picren] 未执行（无可用计划）", file=sys.stderr)
            return 1
        print(f"[picren] 已重命名 {stats.renamed} 个文件"
              + (f"，失败 {len(stats.failed)} 个" if stats.failed else ""))
        for src, err in stats.failed:
            print(f"  - {src}: {err}", file=sys.stderr)
    return 0


def _fix_win_encoding() -> None:
    """Windows 下重定向/管道输出统一为 UTF-8，避免中文乱码。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    """CLI 入口，返回进程退出码。"""
    _fix_win_encoding()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.undo:
            return _cmd_undo(args)
        return _cmd_run(args)
    except _UsageError as exc:
        print(f"[picren] 参数错误：{exc}", file=sys.stderr)
        parser.print_usage(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
