"""CLI 集成测试：sys.modules 注入契约一致的 stub，独立可测且不联网。"""

import csv
import os
import re
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime

import pytest


# --------------------------------------------------------------------------
# 契约一致的 stub 模块（与 reader/vision/rename_rules/executor/undo 接口对齐）
# --------------------------------------------------------------------------

def _make_stubs():
    """构造五个契约一致模块的 stub，返回 {name: module}。"""
    stubs = {}

    # ---- reader ----
    reader = types.ModuleType("reader")

    @dataclass
    class ImageFile:
        path: str
        taken_at: object
        width: int
        height: int
        ext: str

    class ImageReadError(Exception):
        pass

    def _exts(patterns):
        exts = set()
        for p in patterns or []:
            p = str(p).strip().lower().lstrip("*")
            p = p[1:] if p.startswith(".") else p
            if p:
                exts.add(p)
        return exts

    def collect_images(directory, *, recursive=False, patterns=None):
        if patterns is None:
            patterns = [".jpg", ".jpeg", ".png", ".heic", ".webp"]
        if not os.path.isdir(directory):
            return []
        exts = _exts(patterns)
        if recursive:
            walker = os.walk(directory)
        else:
            walker = iter([(directory, [], os.listdir(directory))])
        images = []
        for root, _dirs, names in walker:
            for name in names:
                ext = os.path.splitext(name)[1].lower().lstrip(".")
                if ext not in exts:
                    continue
                path = os.path.join(root, name)
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                images.append(ImageFile(path=path, taken_at=mtime, width=0,
                                        height=0, ext=ext))
        images.sort(key=lambda f: f.path)
        return images

    def read_preview(path, max_edge=800):
        if not os.path.exists(path):
            raise ImageReadError(f"无法读取图片 {path!r}")
        return b"stub-preview-bytes"

    reader.ImageFile = ImageFile
    reader.ImageReadError = ImageReadError
    reader.collect_images = collect_images
    reader.read_preview = read_preview
    stubs["reader"] = reader

    # ---- vision ----
    vision = types.ModuleType("vision")
    REQUIRED_KEYS = ("subject", "category", "scene", "confidence")
    CATEGORIES = ("旅行", "美食", "文档", "宠物", "人物", "街拍", "风景", "运动", "建筑", "其他")

    @dataclass
    class VisionResult:
        subject: str
        category: str
        scene: str
        confidence: float
        raw: dict

    class VisionError(Exception):
        pass

    _STATE = {"fail": False, "result": None}

    def analyze(preview_bytes, *, api_base, model, api_key, timeout_s=30, retries=1):
        if not api_key:
            raise VisionError("缺少 API key：请传参 api_key 或设置环境变量")
        if _STATE["fail"]:
            raise VisionError("stub：识别失败（模拟）")
        r = _STATE.get("result")
        if r is not None:
            return r
        return VisionResult(subject="东京塔", category="旅行", scene="夜晚",
                            confidence=0.92, raw={})

    vision.REQUIRED_KEYS = REQUIRED_KEYS
    vision.CATEGORIES = CATEGORIES
    vision.VisionResult = VisionResult
    vision.VisionError = VisionError
    vision._STATE = _STATE
    vision.analyze = analyze
    stubs["vision"] = vision

    # ---- rename_rules ----
    rules = types.ModuleType("rename_rules")
    _TOKEN_RE = re.compile(r"\{(\w+)(?::([^}]*))?\}")
    _INVALID = '/\\:*?"<>|'

    class TemplateError(ValueError):
        pass

    def render_template(template, img, result, index, index_pad=2):
        def render_date(fmt):
            if img.taken_at is None:
                return ""
            return img.taken_at.strftime(fmt if fmt else "%Y-%m-%d")

        def replace(m):
            name, fmt = m.group(1), m.group(2)
            if name == "date":
                return render_date(fmt)
            if name == "category":
                return result.category
            if name == "subject":
                return result.subject
            if name == "scene":
                return result.scene
            if name == "index":
                return str(index).zfill(index_pad)
            if name == "ext":
                return img.ext.lstrip(".").lower()
            raise TemplateError(f"未知占位符: {{{name}}}")

        return _TOKEN_RE.sub(replace, template)

    def sanitize_name(name):
        return "".join(c for c in name if c not in _INVALID).strip(" .")

    def resolve_unique(target_dir, desired, taken):
        if desired not in taken and not os.path.exists(os.path.join(target_dir, desired)):
            return desired
        stem, dot, ext = desired.rpartition(".")
        if dot:
            suffix = "." + ext
        else:
            stem, suffix = desired, ""
        i = 1
        while True:
            cand = f"{stem}_{i}{suffix}"
            if cand not in taken and not os.path.exists(os.path.join(target_dir, cand)):
                return cand
            i += 1

    rules.TemplateError = TemplateError
    rules.render_template = render_template
    rules.sanitize_name = sanitize_name
    rules.resolve_unique = resolve_unique
    stubs["rename_rules"] = rules

    # ---- executor ----
    executor = types.ModuleType("executor")

    @dataclass
    class RenameOp:
        src_abs: str
        dst_abs: str
        mtime_before: float

    @dataclass
    class ApplyStats:
        renamed: int
        failed: list = field(default_factory=list)

    _HEADER = ("old_name", "new_name", "mtime")

    def _map_dir(path):
        return os.path.dirname(os.path.abspath(path))

    def apply_renames(ops, *, undo_map="rename_map.csv"):
        ops = [RenameOp(os.path.abspath(o.src_abs), os.path.abspath(o.dst_abs),
                        o.mtime_before) for o in ops]
        stats = ApplyStats(0, [])
        for op in ops:
            if os.path.lexists(op.dst_abs):
                stats.failed.append((op.src_abs, "目标已存在，拒绝覆盖"))
                continue
            try:
                os.rename(op.src_abs, op.dst_abs)
            except OSError as e:
                stats.failed.append((op.src_abs, str(e)))
                continue
            base = _map_dir(undo_map)
            fresh = not os.path.exists(undo_map) or os.path.getsize(undo_map) == 0
            with open(undo_map, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if fresh:
                    w.writerow(_HEADER)
                w.writerow([os.path.relpath(op.src_abs, base),
                            os.path.relpath(op.dst_abs, base),
                            repr(op.mtime_before)])
            stats.renamed += 1
        return stats

    def dry_run_render(ops):
        return [(o.src_abs, o.dst_abs) for o in ops]

    executor.RenameOp = RenameOp
    executor.ApplyStats = ApplyStats
    executor.apply_renames = apply_renames
    executor.dry_run_render = dry_run_render
    stubs["executor"] = executor

    # ---- undo ----
    undo = types.ModuleType("undo")

    def load_map(path):
        if not os.path.exists(path):
            return []
        base = os.path.dirname(os.path.abspath(path))
        ops = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or len(row) < 2:
                    continue
                if row[0].strip() == _HEADER[0] and row[1].strip() == _HEADER[1]:
                    continue
                mtime = 0.0
                if len(row) >= 3:
                    try:
                        mtime = float(row[2])
                    except ValueError:
                        pass
                ops.append(RenameOp(src_abs=os.path.normpath(os.path.join(base, row[0])),
                                    dst_abs=os.path.normpath(os.path.join(base, row[1])),
                                    mtime_before=mtime))
        return ops

    def reverse_ops(ops):
        return [RenameOp(src_abs=o.dst_abs, dst_abs=o.src_abs, mtime_before=o.mtime_before)
                for o in reversed(ops)]

    def undo_from_map(path):
        stats = ApplyStats(0, [])
        if not os.path.exists(path):
            return stats
        ops = load_map(path)
        done = [False] * len(ops)
        for i, op in reversed(list(enumerate(ops))):
            if not os.path.lexists(op.dst_abs):
                stats.failed.append((op.dst_abs, "目标不存在，跳过"))
                continue
            if os.path.lexists(op.src_abs):
                stats.failed.append((op.src_abs, "原名被占用，跳过"))
                continue
            try:
                os.rename(op.dst_abs, op.src_abs)
                stats.renamed += 1
                done[i] = True
            except OSError as e:
                stats.failed.append((op.dst_abs, str(e)))
        remaining = [op for i, op in enumerate(ops) if not done[i]]
        if remaining:
            tmp = path + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(_HEADER)
                for op in remaining:
                    base = os.path.dirname(os.path.abspath(path))
                    w.writerow([os.path.relpath(op.src_abs, base),
                                os.path.relpath(op.dst_abs, base),
                                repr(op.mtime_before)])
            os.replace(tmp, path)
        else:
            os.remove(path)
        return stats

    undo.load_map = load_map
    undo.reverse_ops = reverse_ops
    undo.undo_from_map = undo_from_map
    stubs["undo"] = undo

    return stubs


# --------------------------------------------------------------------------
# fixture：注入 stub → import main → 测试 → 恢复现场
# --------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def cli_env():
    names = ("reader", "vision", "rename_rules", "executor", "undo", "pipeline", "main")
    saved = {n: sys.modules.get(n) for n in names}
    stubs = _make_stubs()
    for n, mod in stubs.items():
        sys.modules[n] = mod
    saved_key = os.environ.get("API_KEY")
    os.environ["API_KEY"] = "stub-test-key"
    try:
        import main as main_mod
        yield main_mod, stubs
    finally:
        if saved_key is None:
            os.environ.pop("API_KEY", None)
        else:
            os.environ["API_KEY"] = saved_key
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------

def _make_images(directory, names):
    """造若干仅含占位文本的图片（stub reader 不读内容，只认扩展名）。"""
    for name in names:
        with open(os.path.join(directory, name), "w") as f:
            f.write("stub-image")


def _snapshot(directory):
    """目录快照：条目清单 + 每个文件字节 + 目录 mtime。"""
    entries = sorted(os.listdir(directory))
    contents = {}
    for name in entries:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                contents[name] = f.read()
    return entries, contents, os.stat(directory).st_mtime


IMG_NAMES = ("IMG_20230101_103055.jpg", "IMG_20230615_140020.jpg", "photo_20240801.jpg")


# --------------------------------------------------------------------------
# 用例
# --------------------------------------------------------------------------

def test_unknown_argument_exit_1(cli_env, capsys):
    main_mod, _ = cli_env
    assert main_mod.main(["--bogus-flag"]) == 1
    err = capsys.readouterr().err
    assert "参数错误" in err


def test_missing_dir_exit_1(cli_env, capsys):
    main_mod, _ = cli_env
    assert main_mod.main([]) == 1
    err = capsys.readouterr().err
    assert "--dir" in err


def test_nonexistent_dir_exit_1(cli_env, capsys, tmp_path):
    main_mod, _ = cli_env
    code = main_mod.main(["--dir", str(tmp_path / "nope")])
    assert code == 1
    assert "目录不存在" in capsys.readouterr().err


def test_dry_run_no_changes(cli_env, tmp_path, capsys):
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = False
    _make_images(tmp_path, IMG_NAMES)
    before = _snapshot(tmp_path)
    code = main_mod.main(["--dir", str(tmp_path), "--dry-run"])
    assert code == 0
    assert before == _snapshot(tmp_path)
    out = capsys.readouterr().out
    assert "->" in out  # 预览表已打印
    assert not (tmp_path / "rename_map.csv").exists()
    assert not (tmp_path / "tags.csv").exists()


def test_dry_run_sample_unchanged(cli_env):
    """对 sample/ 目录干跑：目录内容与 mtime 不变（若 sample 存在）。"""
    sample = os.path.join(os.getcwd(), "sample")
    if not os.path.isdir(sample):
        pytest.skip("sample 目录不存在，跳过")
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = False
    before = _snapshot(sample)
    # dry-run 无论有无匹配图片（0 有图 / 2 无图）都不允许改动目录
    assert main_mod.main(["--dir", sample, "--dry-run"]) in (0, 2)
    assert before == _snapshot(sample)


def test_no_api_key_clear_error(cli_env, tmp_path, capsys, monkeypatch):
    main_mod, _ = cli_env
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("PICRENAME_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # .env 检查落在 tmp_path，保证无 key
    _make_images(tmp_path, IMG_NAMES[:1])
    code = main_mod.main(["--dir", str(tmp_path), "--dry-run"])
    assert code != 0
    err = capsys.readouterr().err
    assert "API Key" in err and "API_KEY" in err


def test_execute_writes_map_then_undo_restores(cli_env, tmp_path, capsys):
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = False
    _make_images(tmp_path, IMG_NAMES)
    before_names = sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".jpg"))

    # --execute：先展示 dry-run 表，再真实改名并写 rename_map.csv
    code = main_mod.main(["--dir", str(tmp_path), "--execute"])
    assert code == 0
    out = capsys.readouterr().out
    assert "执行前预览" in out and "->" in out
    assert (tmp_path / "rename_map.csv").exists()
    after_names = sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".jpg"))
    assert after_names != before_names

    # --undo：全部恢复原名
    code = main_mod.main(["--dir", str(tmp_path), "--undo"])
    assert code == 0
    restored = sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".jpg"))
    assert restored == before_names


def test_execute_without_dir_undo_reports_missing_map(cli_env, tmp_path, capsys):
    main_mod, _ = cli_env
    code = main_mod.main(["--dir", str(tmp_path), "--undo"])
    assert code == 1
    assert "未找到回滚映射" in capsys.readouterr().err


def test_fail_ratio_abort_exit_3(cli_env, tmp_path, capsys):
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = True
    try:
        _make_images(tmp_path, IMG_NAMES)
        code = main_mod.main(["--dir", str(tmp_path), "--dry-run"])
        assert code == 3
        err = capsys.readouterr().err
        assert "识别质量过低" in err
    finally:
        stubs["vision"]._STATE["fail"] = False


def test_fail_ratio_abort_blocks_execute(cli_env, tmp_path, capsys):
    """execute 模式下识别失败过多同样中止，不产生改名与映射。"""
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = True
    try:
        _make_images(tmp_path, IMG_NAMES)
        code = main_mod.main(["--dir", str(tmp_path), "--execute"])
        assert code == 3
        assert not (tmp_path / "rename_map.csv").exists()
    finally:
        stubs["vision"]._STATE["fail"] = False


def test_no_images_exit_2(cli_env, tmp_path, capsys):
    main_mod, _ = cli_env
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    code = main_mod.main(["--dir", str(tmp_path), "--dry-run"])
    assert code == 2
    assert "未找到匹配的图片文件" in capsys.readouterr().err


def test_tags_only_writes_csv(cli_env, tmp_path, capsys):
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = False
    _make_images(tmp_path, IMG_NAMES)
    code = main_mod.main(["--dir", str(tmp_path), "--tags-only"])
    assert code == 0
    csv_path = tmp_path / "tags.csv"
    assert csv_path.exists()
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["文件名", "日期", "类别", "主题", "场景", "置信度"]
    assert len(rows) == 1 + len(IMG_NAMES)
    assert rows[1][2] == "旅行" and rows[1][3] == "东京塔"
    # 未改名
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".jpg")) == \
        sorted(IMG_NAMES)


def test_json_output_mode(cli_env, tmp_path, capsys):
    main_mod, stubs = cli_env
    stubs["vision"]._STATE["fail"] = False
    _make_images(tmp_path, IMG_NAMES)
    code = main_mod.main(["--dir", str(tmp_path), "--dry-run", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    import json as _json
    data = _json.loads(out)
    assert data["executed"] is None
    assert len(data["planned"]) == len(IMG_NAMES)
    assert data["tags"][0]["subject"] == "东京塔"
