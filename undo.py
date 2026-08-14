"""rename_map 读写与回滚：解析、反转、逆序回滚并原子写回。"""

from __future__ import annotations

import csv
import os
from typing import List

from executor import ApplyStats, RenameOp

_HEADER = ("old_name", "new_name", "mtime")


def _map_dir(path: str) -> str:
    return os.path.dirname(os.path.abspath(path))


def _to_abs(name: str, base: str) -> str:
    if os.path.isabs(name):
        return os.path.normpath(name)
    return os.path.normpath(os.path.join(base, name))


def _rel(path: str, base: str) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:  # 跨盘符时回退绝对路径
        return path


def _fmt_mtime(mtime: float) -> str:
    return repr(mtime) if mtime else "0"


def load_map(path: str) -> List[RenameOp]:
    """解析 rename_map.csv（old_name,new_name,mtime）为 RenameOp 列表，坏行容错跳过。"""
    if not os.path.exists(path):
        return []
    base = _map_dir(path)
    ops: List[RenameOp] = []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if row[0].strip() == _HEADER[0] and len(row) >= 2 and row[1].strip() == _HEADER[1]:
                continue
            if len(row) < 2:  # 缺 old_name/new_name 的坏行
                continue
            mtime = 0.0
            if len(row) >= 3:
                try:
                    mtime = float(row[2])
                except ValueError:
                    mtime = 0.0
            ops.append(RenameOp(
                src_abs=_to_abs(row[0], base),
                dst_abs=_to_abs(row[1], base),
                mtime_before=mtime,
            ))
    return ops


def reverse_ops(ops: List[RenameOp]) -> List[RenameOp]:
    """dst→src 交换并逆序，返回可直接执行的回滚序列。"""
    return [RenameOp(src_abs=op.dst_abs, dst_abs=op.src_abs, mtime_before=op.mtime_before)
            for op in reversed(ops)]


def _write_map(path: str, ops: List[RenameOp]) -> None:
    """原子写回剩余条目；为空则删除 map 文件。"""
    if not ops:
        if os.path.exists(path):
            os.remove(path)
        return
    base = _map_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(_HEADER)
        for op in ops:
            writer.writerow([_rel(op.src_abs, base), _rel(op.dst_abs, base), _fmt_mtime(op.mtime_before)])
    os.replace(tmp, path)


def undo_from_map(path: str) -> ApplyStats:
    """逆序回滚 map 中的改名（目标不存在或原名被占用则跳过），成功后原子写回。"""
    if not os.path.exists(path):
        return ApplyStats(renamed=0, failed=[])
    ops = load_map(path)
    stats = ApplyStats(renamed=0, failed=[])
    done = [False] * len(ops)
    for i, op in reversed(list(enumerate(ops))):
        if not os.path.lexists(op.dst_abs):
            stats.failed.append((op.dst_abs, "目标已不存在，跳过回滚: %s" % op.dst_abs))
            continue
        if os.path.lexists(op.src_abs):
            stats.failed.append((op.src_abs, "原名位置已被占用，跳过避免覆盖: %s" % op.src_abs))
            continue
        try:
            os.rename(op.dst_abs, op.src_abs)
            if op.mtime_before > 0:
                try:
                    os.utime(op.src_abs, (op.mtime_before, op.mtime_before))
                except OSError:
                    pass  # 恢复 mtime 失败不影响回滚本身
            stats.renamed += 1
            done[i] = True
        except OSError as e:
            stats.failed.append((op.dst_abs, str(e)))
    remaining = [op for i, op in enumerate(ops) if not done[i]]
    _write_map(path, remaining)
    return stats
