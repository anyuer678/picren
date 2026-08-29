"""改名执行与 dry-run 展示：逐个 os.rename、失败隔离、成功后追加 undo_map。"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class RenameOp:
    src_abs: str
    dst_abs: str
    mtime_before: float


@dataclass
class ApplyStats:
    renamed: int
    failed: list  # [(src, err), ...]


_HEADER = ("old_name", "new_name", "mtime")


def _map_dir(path: str) -> str:
    return os.path.dirname(os.path.abspath(path))


def _rel(path: str, base: str) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:  # 跨盘符时回退绝对路径
        return path


def _fmt_mtime(mtime: float) -> str:
    return repr(mtime) if mtime else "0"


def _append_map_row(undo_map: str, op: RenameOp) -> None:
    base = _map_dir(undo_map)
    fresh = not os.path.exists(undo_map) or os.path.getsize(undo_map) == 0
    with open(undo_map, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if fresh:
            writer.writerow(_HEADER)
        writer.writerow([_rel(op.src_abs, base), _rel(op.dst_abs, base), _fmt_mtime(op.mtime_before)])


def apply_renames(ops: List[RenameOp], *, undo_map: str = "rename_map.csv") -> ApplyStats:
    """逐个 os.rename；单个失败只记录不中断整批，成功后 append 一行到 undo_map。"""
    ops = [RenameOp(os.path.abspath(o.src_abs), os.path.abspath(o.dst_abs), o.mtime_before)
           for o in ops]
    stats = ApplyStats(renamed=0, failed=[])
    for op in ops:
        if os.path.lexists(op.dst_abs):
            stats.failed.append((op.src_abs, "目标已存在，拒绝覆盖: %s" % op.dst_abs))
            continue
        try:
            os.rename(op.src_abs, op.dst_abs)
        except OSError as e:
            stats.failed.append((op.src_abs, str(e)))
            continue
        _append_map_row(undo_map, op)
        stats.renamed += 1
    return stats


def dry_run_render(ops: List[RenameOp]) -> List[Tuple[str, str]]:
    """纯展示 (src→dst) 列表，绝不触碰文件系统。"""
    return [(op.src_abs, op.dst_abs) for op in ops]
