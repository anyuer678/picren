"""executor/undo 模块测试：改名、失败隔离、回滚字节一致、dry-run 与解析（不联网）。"""

import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor import ApplyStats, RenameOp, apply_renames, dry_run_render
from undo import load_map, reverse_ops, undo_from_map


def _op(src, dst, mtime=1234.5):
    return RenameOp(src_abs=str(src), dst_abs=str(dst), mtime_before=mtime)


# ---------- apply_renames ----------

def test_apply_renames_success(tmp_path):
    src = tmp_path / "IMG_0001.jpg"
    dst = tmp_path / "旅行_日本_东京塔_01.jpg"
    src.write_bytes(b"photo-data")
    map_path = str(tmp_path / "rename_map.csv")
    stats = apply_renames([_op(src, dst)], undo_map=map_path)
    assert stats.renamed == 1
    assert stats.failed == []
    assert not src.exists()
    assert dst.read_bytes() == b"photo-data"
    with open(map_path, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["old_name", "new_name", "mtime"]
    assert len(rows) == 2
    assert rows[1][2] == "1234.5"


def test_apply_renames_no_overwrite(tmp_path):
    src = tmp_path / "a.jpg"
    dst = tmp_path / "b.jpg"
    src.write_bytes(b"aaa")
    dst.write_bytes(b"bbb")
    stats = apply_renames([_op(src, dst)], undo_map=str(tmp_path / "m.csv"))
    assert stats.renamed == 0
    assert len(stats.failed) == 1
    assert stats.failed[0][0] == str(src)
    assert src.read_bytes() == b"aaa"
    assert dst.read_bytes() == b"bbb"  # 未被覆盖


def test_apply_renames_missing_src(tmp_path):
    src = tmp_path / "ghost.jpg"  # 源文件不存在 → os.rename 抛 OSError
    dst = tmp_path / "ok.jpg"
    alive = tmp_path / "alive.jpg"
    alive.write_bytes(b"y")
    stats = apply_renames([_op(src, dst), _op(alive, tmp_path / "alive2.jpg")],
                          undo_map=str(tmp_path / "m.csv"))
    assert stats.renamed == 1  # OSError 分支不中断整批
    assert len(stats.failed) == 1
    assert stats.failed[0][0] == str(src)
    assert (tmp_path / "alive2.jpg").exists()


def test_apply_renames_isolate_failure(tmp_path):
    a, b, c = (tmp_path / n for n in ("1.jpg", "2.jpg", "3.jpg"))
    for f in (a, b, c):
        f.write_bytes(b"x")
    b_dst = tmp_path / "b_new.jpg"
    b_dst.write_bytes(b"occupied")
    ops = [_op(a, tmp_path / "a_new.jpg"), _op(b, b_dst), _op(c, tmp_path / "c_new.jpg")]
    stats = apply_renames(ops, undo_map=str(tmp_path / "m.csv"))
    assert stats.renamed == 2
    assert len(stats.failed) == 1
    assert stats.failed[0][0] == str(b)
    assert not a.exists() and not c.exists()
    assert (tmp_path / "a_new.jpg").exists() and (tmp_path / "c_new.jpg").exists()
    assert b.read_bytes() == b"x" and b_dst.read_bytes() == b"occupied"


def test_apply_renames_map_append(tmp_path):
    map_path = str(tmp_path / "m.csv")
    a = tmp_path / "a.jpg"
    a.write_bytes(b"1")
    b = tmp_path / "b.jpg"
    b.write_bytes(b"2")
    apply_renames([_op(a, tmp_path / "a2.jpg")], undo_map=map_path)
    apply_renames([_op(b, tmp_path / "b2.jpg")], undo_map=map_path)
    ops = load_map(map_path)
    assert len(ops) == 2
    assert {os.path.basename(o.src_abs) for o in ops} == {"a.jpg", "b.jpg"}
    assert {os.path.basename(o.dst_abs) for o in ops} == {"a2.jpg", "b2.jpg"}


# ---------- undo_from_map ----------

def test_undo_roundtrip_bytes(tmp_path):
    src = tmp_path / "原始_照片.jpg"
    dst = tmp_path / "旅行_日本_东京塔.jpg"
    payload = "东京塔夜景".encode("utf-8") + b"\x00\xff\x01\x02"
    src.write_bytes(payload)
    map_path = str(tmp_path / "m.csv")
    op = RenameOp(str(src), str(dst), os.stat(src).st_mtime)
    assert apply_renames([op], undo_map=map_path).renamed == 1
    assert os.path.exists(map_path)
    back = undo_from_map(map_path)
    assert back.renamed == 1
    assert back.failed == []
    assert src.read_bytes() == payload  # 字节一致
    assert not dst.exists()
    assert os.stat(src).st_mtime == pytest.approx(op.mtime_before, abs=0.01)  # mtime 已恢复
    assert not os.path.exists(map_path)  # 全部成功 → map 删除


def test_undo_skip_missing_target(tmp_path):
    src = tmp_path / "a.jpg"
    dst = tmp_path / "b.jpg"
    src.write_bytes(b"x")
    map_path = str(tmp_path / "m.csv")
    apply_renames([_op(src, dst)], undo_map=map_path)
    dst.unlink()  # 回滚目标已不存在
    back = undo_from_map(map_path)
    assert back.renamed == 0
    assert len(back.failed) == 1
    assert "不存在" in back.failed[0][1]
    assert not src.exists()
    assert os.path.exists(map_path)  # 未完成条目保留在 map


def test_undo_avoids_overwrite_other_file(tmp_path):
    src = tmp_path / "a.jpg"
    dst = tmp_path / "b.jpg"
    src.write_bytes(b"original")
    map_path = str(tmp_path / "m.csv")
    apply_renames([_op(src, dst)], undo_map=map_path)
    src.write_bytes(b"someone-else")  # 他人文件占用原名位置
    back = undo_from_map(map_path)
    assert back.renamed == 0
    assert len(back.failed) == 1
    assert src.read_bytes() == b"someone-else"  # 他人文件未被覆盖
    assert dst.read_bytes() == b"original"
    assert os.path.exists(map_path)


def test_undo_idempotent(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    map_path = str(tmp_path / "m.csv")
    apply_renames([_op(src, tmp_path / "b.jpg")], undo_map=map_path)
    assert undo_from_map(map_path).renamed == 1
    assert not os.path.exists(map_path)
    again = undo_from_map(map_path)  # map 已删除 → 安全空操作
    assert again.renamed == 0
    assert again.failed == []
    assert src.read_bytes() == b"x"


def test_undo_chinese_filename_bytes(tmp_path):
    src = tmp_path / "IMG_20230101_103055.jpg"
    dst = tmp_path / "旅行_日本_东京塔_2026.jpg"
    data = os.urandom(1024)
    src.write_bytes(data)
    map_path = str(tmp_path / "rename_map.csv")
    apply_renames([RenameOp(str(src), str(dst), os.stat(src).st_mtime)], undo_map=map_path)
    assert undo_from_map(map_path).renamed == 1
    assert src.read_bytes() == data


# ---------- dry_run_render ----------

def test_dry_run_render_no_fs(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    before = set(os.listdir(tmp_path))
    out = dry_run_render([_op(src, tmp_path / "b.jpg")])
    assert out == [(str(src), str(tmp_path / "b.jpg"))]
    assert set(os.listdir(tmp_path)) == before  # 未产生任何文件
    assert src.exists()


# ---------- load_map / reverse_ops ----------

def test_load_map_roundtrip(tmp_path):
    m = tmp_path / "m.csv"
    m.write_text(
        "old_name,new_name,mtime\n"
        "照片\\IMG_0001.jpg,照片\\旅行_东京塔_01.jpg,1234.5\n"
        "photo2.jpg,旅行_日本_富士山.jpg,100.25\n",
        encoding="utf-8-sig",
    )
    ops = load_map(str(m))
    assert len(ops) == 2
    assert ops[0].src_abs.endswith(os.path.join("照片", "IMG_0001.jpg"))
    assert ops[0].dst_abs.endswith(os.path.join("照片", "旅行_东京塔_01.jpg"))
    assert ops[0].mtime_before == pytest.approx(1234.5)
    assert ops[1].mtime_before == pytest.approx(100.25)


def test_load_map_bad_rows_tolerated(tmp_path):
    m = tmp_path / "m.csv"
    m.write_text(
        "old_name,new_name,mtime\n"
        "badrow\n"
        "x.jpg,y.jpg,not_a_number\n"
        "z.jpg,w.jpg\n",
        encoding="utf-8-sig",
    )
    ops = load_map(str(m))
    assert len(ops) == 2  # 坏行跳过、非法 mtime 与缺列容错为 0.0
    assert ops[0].mtime_before == 0.0
    assert ops[1].mtime_before == 0.0


def test_load_map_missing_file(tmp_path):
    assert load_map(str(tmp_path / "none.csv")) == []


def test_reverse_ops(tmp_path):
    a, b, c, d = (tmp_path / n for n in ("a", "b", "c", "d"))
    ops = [_op(a, b, 1.0), _op(c, d, 2.0)]
    rev = reverse_ops(ops)
    assert [(o.src_abs, o.dst_abs) for o in rev] == [(str(d), str(c)), (str(b), str(a))]
    assert rev[0].mtime_before == 2.0
    assert rev[1].mtime_before == 1.0
