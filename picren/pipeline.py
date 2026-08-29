"""管道编排：收集图片→并发识别→渲染计划→执行或预览。"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .executor import ApplyStats, RenameOp, apply_renames
from .reader import ImageFile, collect_images, read_preview
from .rename_rules import render_template, resolve_unique, sanitize_name
from .vision import VisionResult, analyze

DEFAULT_PATTERNS = [".jpg", ".jpeg", ".png", ".heic", ".webp"]
UNDO_MAP_NAME = "rename_map.csv"


@dataclass
class PipelineConfig:
    """一次批量重命名运行的配置。"""

    directory: str
    recursive: bool = False
    patterns: list = None
    template: str = "{date}_{category}_{subject}_{index}.{ext}"
    dry_run_first: bool = True
    workers: int = 8
    api_base: str = None
    model: str = None
    api_key: str = None
    move_by_category: bool = False
    keep_original: bool = True
    max_fail_ratio: float = 0.2


@dataclass
class PipelineReport:
    """pipeline 运行结果：计划、执行结果、失败项、标签、耗时。"""

    planned: list = field(default_factory=list)  # [(src, dst), ...]
    executed: object = None  # ApplyStats | None
    failed: list = field(default_factory=list)  # [(path, err), ...]
    tags: list = field(default_factory=list)  # [VisionResult, ...]
    elapsed_s: float = 0.0
    tagged: list = field(default_factory=list)  # [(ImageFile, VisionResult), ...]


def _analyze_one(img: ImageFile, cfg: PipelineConfig) -> VisionResult:
    """单张图片：压缩预览字节流后调用视觉识别。"""
    preview = read_preview(img.path)
    return analyze(preview, api_base=cfg.api_base, model=cfg.model, api_key=cfg.api_key)


def _analyze_batch(images: List[ImageFile], cfg: PipelineConfig):
    """并发识别全部图片；单张失败只记 failed，不中断整批。"""
    tags, failed, tagged = [], [], []
    if not images:
        return tags, failed, tagged
    workers = max(1, cfg.workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_analyze_one, img, cfg) for img in images]
        for img, fut in zip(images, futures):
            try:
                result = fut.result()
            except Exception as exc:
                failed.append((img.path, str(exc)))
                continue
            tags.append(result)
            tagged.append((img, result))
    return tags, failed, tagged


def _with_original(name: str, img: ImageFile) -> str:
    """把原名 stem 追加到目标名，保证可回溯。"""
    stem = os.path.splitext(os.path.basename(img.path))[0]
    base, dot, ext = name.rpartition(".")
    return f"{base}_{stem}{dot}{ext}" if dot else f"{name}_{stem}"


def _build_ops(images: List[ImageFile], tagged: List[Tuple[ImageFile, VisionResult]],
               cfg: PipelineConfig) -> List[RenameOp]:
    """按模板渲染+去重，产出改名操作序列（不触碰文件系统）。"""
    taken: Dict[str, set] = {}
    ops: List[RenameOp] = []
    for img, result in tagged:
        idx = len(ops) + 1
        name = render_template(cfg.template, img, result, idx)
        if cfg.keep_original:
            name = _with_original(name, img)
        name = sanitize_name(name)
        if not name:
            name = f"{os.path.splitext(os.path.basename(img.path))[0]}_{idx}"
        if cfg.move_by_category and result.category:
            dst_dir = os.path.join(cfg.directory, result.category)
        else:
            dst_dir = cfg.directory
        used = taken.setdefault(dst_dir, set())
        unique = resolve_unique(dst_dir, name, used)
        used.add(unique)
        mtime = 0.0
        try:
            mtime = os.path.getmtime(img.path)
        except OSError:
            pass
        ops.append(RenameOp(src_abs=img.path,
                            dst_abs=os.path.join(dst_dir, unique),
                            mtime_before=mtime))
    return ops


def _prepare_dirs(ops: List[RenameOp]) -> None:
    """为 move_by_category 的目标子目录建目录（仅执行阶段调用）。"""
    for op in ops:
        d = os.path.dirname(op.dst_abs)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)


def run_pipeline(cfg: PipelineConfig) -> PipelineReport:
    """收集→识别→渲染；失败比例超标中止，否则 dry-run 展示或执行改名。"""
    start = time.monotonic()
    images = collect_images(cfg.directory, recursive=cfg.recursive,
                            patterns=cfg.patterns or DEFAULT_PATTERNS)
    tags, failed, tagged = _analyze_batch(images, cfg)
    total = len(images)
    fail_ratio = len(failed) / total if total else 0.0
    planned: List[Tuple[str, str]] = []
    executed: Optional[ApplyStats] = None
    if fail_ratio <= cfg.max_fail_ratio:
        planned = _build_ops(images, tagged, cfg)
        if not cfg.dry_run_first:
            _prepare_dirs(planned)
            undo_map = os.path.join(cfg.directory, UNDO_MAP_NAME)
            executed = apply_renames(planned, undo_map=undo_map)
    return PipelineReport(
        planned=planned, executed=executed, failed=failed, tags=tags,
        elapsed_s=time.monotonic() - start, tagged=tagged,
    )
