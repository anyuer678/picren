"""rename_rules 模板渲染、非法字符过滤、重名去重测试。"""

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from picren.reader import ImageFile
from picren.rename_rules import TemplateError, render_template, sanitize_name, resolve_unique


class Result:
    subject = "东京塔"
    category = "旅行"
    scene = "夜晚"


def make_img(taken_at=None, ext="jpg"):
    taken_at = taken_at or datetime(2026, 8, 8, 10, 30, 55)
    return ImageFile(path="C:/x/IMG_0001.JPG", taken_at=taken_at,
                     width=800, height=600, ext=ext)


def test_render_date_default():
    assert render_template("{date}", make_img(), Result(), 1) == "2026-08-08"


def test_render_date_year():
    assert render_template("{date:%Y}", make_img(), Result(), 1) == "2026"


def test_render_date_custom():
    assert render_template("{date:%Y%m%d}", make_img(), Result(), 1) == "20260808"


def test_render_date_time():
    assert render_template("{date:%H:%M}", make_img(), Result(), 1) == "10:30"


def test_render_date_none_safe():
    img = ImageFile(path="C:/x/a.jpg", taken_at=None, width=1, height=1, ext="jpg")
    assert render_template("{date}", img, Result(), 1) == ""


def test_render_index_padding():
    assert render_template("{index}", make_img(), Result(), 7) == "07"


def test_render_index_pad3():
    assert render_template("{index}", make_img(), Result(), 7, index_pad=3) == "007"


def test_render_index_large():
    assert render_template("{index}", make_img(), Result(), 123) == "123"


def test_render_ext_lower():
    assert render_template("{ext}", make_img(ext=".JPG"), Result(), 1) == "jpg"


def test_render_fields():
    out = render_template("{category}_{subject}_{scene}", make_img(), Result(), 1)
    assert out == "旅行_东京塔_夜晚"


def test_render_combined_template():
    tpl = "{date}_{category}_{subject}_{index}.{ext}"
    assert render_template(tpl, make_img(), Result(), 1) == "2026-08-08_旅行_东京塔_01.jpg"


def test_render_duck_typing_result():
    class Duck:
        subject = "富士山"
        category = "风景"
        scene = "白天"

    out = render_template("{subject}_{category}_{scene}", make_img(), Duck(), 1)
    assert out == "富士山_风景_白天"


def test_render_unknown_placeholder():
    with pytest.raises(TemplateError):
        render_template("{foo}", make_img(), Result(), 1)


def test_render_unknown_placeholder_in_middle():
    with pytest.raises(TemplateError):
        render_template("{category}_{foo}", make_img(), Result(), 1)


def test_render_date_multiple_occurrences():
    out = render_template("{date}|{date:%Y}", make_img(), Result(), 1)
    assert out == "2026-08-08|2026"


def test_sanitize_invalid_chars():
    raw = 'a/b\\c:d*e?f"g<h>i|j'
    assert sanitize_name(raw) == "abcdefghij"


def test_sanitize_keeps_chinese():
    assert sanitize_name("旅行_日本_东京塔") == "旅行_日本_东京塔"


def test_sanitize_keeps_emoji():
    assert sanitize_name("东京塔🗼夜景🌃") == "东京塔🗼夜景🌃"


def test_sanitize_trim_dots_and_spaces():
    assert sanitize_name("  东京塔.  ") == "东京塔"


def test_sanitize_mixed():
    assert sanitize_name(" a/b/c:名字. ") == "abc名字"


def test_sanitize_all_invalid():
    assert sanitize_name('/\\:*?"<>|') == ""


def test_resolve_unique_no_conflict(tmp_path):
    assert resolve_unique(str(tmp_path), "a.jpg", set()) == "a.jpg"


def test_resolve_unique_taken():
    assert resolve_unique("x", "a.jpg", {"a.jpg"}) == "a_1.jpg"


def test_resolve_unique_existing_file(tmp_path):
    (tmp_path / "a.jpg").touch()
    assert resolve_unique(str(tmp_path), "a.jpg", set()) == "a_1.jpg"


def test_resolve_unique_taken_and_existing(tmp_path):
    (tmp_path / "a.jpg").touch()
    (tmp_path / "a_1.jpg").touch()
    assert resolve_unique(str(tmp_path), "a.jpg", {"a.jpg", "a_1.jpg"}) == "a_2.jpg"


def test_resolve_unique_existing_plus_taken(tmp_path):
    (tmp_path / "a.jpg").touch()
    (tmp_path / "a_1.jpg").touch()
    assert resolve_unique(str(tmp_path), "a.jpg", {"a.jpg"}) == "a_2.jpg"


def test_resolve_unique_no_extension(tmp_path):
    (tmp_path / "photo").touch()
    assert resolve_unique(str(tmp_path), "photo", set()) == "photo_1"


def test_resolve_unique_never_overwrite(tmp_path):
    existing = set()
    for _ in range(3):
        name = resolve_unique(str(tmp_path), "b.txt", existing)
        (tmp_path / name).touch()
        existing.add(name)
    assert sorted(os.listdir(tmp_path)) == ["b.txt", "b_1.txt", "b_2.txt"]
