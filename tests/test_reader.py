"""reader 图片收集与预览压缩测试。"""

import io
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from PIL import Image

from picren.reader import ImageReadError, collect_images, read_preview


def make_image(path, size=(1600, 1200), color="red", fmt="JPEG", exif_dt=None):
    im = Image.new("RGB", size, color)
    if exif_dt is not None:
        ex = Image.Exif()
        ex[36867] = exif_dt
        im.save(path, fmt, exif=ex)
    else:
        im.save(path, fmt)


def test_collect_filters_extensions(tmp_path):
    make_image(tmp_path / "a.jpg", (100, 80))
    make_image(tmp_path / "b.JPEG", (100, 80))
    make_image(tmp_path / "c.png", (100, 80))
    (tmp_path / "d.txt").write_text("not an image")
    imgs = collect_images(str(tmp_path), recursive=False)
    assert {i.ext for i in imgs} == {"jpg", "jpeg", "png"}


def test_collect_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    make_image(tmp_path / "top.jpg", (100, 80))
    make_image(sub / "deep.png", (100, 80))
    imgs = collect_images(str(tmp_path), recursive=True)
    assert len(imgs) == 2
    assert {i.ext for i in imgs} == {"jpg", "png"}


def test_collect_not_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    make_image(tmp_path / "top.jpg", (100, 80))
    make_image(sub / "deep.png", (100, 80))
    imgs = collect_images(str(tmp_path), recursive=False)
    assert len(imgs) == 1
    assert imgs[0].ext == "jpg"


def test_collect_missing_dir(tmp_path):
    assert collect_images(str(tmp_path / "nope"), recursive=False) == []


def test_collect_empty_dir(tmp_path):
    assert collect_images(str(tmp_path), recursive=False) == []


def test_collect_exif_preferred(tmp_path):
    p = tmp_path / "with_exif.jpg"
    make_image(p, exif_dt="2023:01:02 03:04:05")
    imgs = collect_images(str(tmp_path), recursive=False)
    assert imgs[0].taken_at == datetime(2023, 1, 2, 3, 4, 5)


def test_collect_mtime_fallback(tmp_path):
    p = tmp_path / "no_exif.jpg"
    make_image(p)
    t = 1_600_000_000.0
    os.utime(p, (t, t))
    imgs = collect_images(str(tmp_path), recursive=False)
    assert imgs[0].taken_at == datetime.fromtimestamp(t)


def test_collect_size(tmp_path):
    make_image(tmp_path / "s.jpg", size=(640, 480))
    imgs = collect_images(str(tmp_path), recursive=False)
    assert (imgs[0].width, imgs[0].height) == (640, 480)


def test_collect_broken_image_included(tmp_path):
    (tmp_path / "fake.jpg").write_text("this is not an image")
    imgs = collect_images(str(tmp_path), recursive=False)
    assert len(imgs) == 1
    assert imgs[0].width == 0
    assert imgs[0].taken_at is not None


def test_collect_custom_patterns(tmp_path):
    make_image(tmp_path / "a.jpg", (100, 80))
    make_image(tmp_path / "b.png", (100, 80))
    imgs = collect_images(str(tmp_path), recursive=False, patterns=[".png"])
    assert [i.ext for i in imgs] == ["png"]


def test_preview_max_edge(tmp_path):
    p = tmp_path / "big.jpg"
    make_image(p, size=(1600, 1200))
    out = read_preview(str(p))
    im = Image.open(io.BytesIO(out))
    assert im.size == (800, 600)


def test_preview_jpeg_magic(tmp_path):
    p = tmp_path / "a.jpg"
    make_image(p)
    out = read_preview(str(p))
    assert out.startswith(b"\xff\xd8")


def test_preview_small_image_not_upscaled(tmp_path):
    p = tmp_path / "small.png"
    make_image(p, size=(100, 50), fmt="PNG")
    out = read_preview(str(p))
    im = Image.open(io.BytesIO(out))
    assert im.size == (100, 50)


def test_preview_custom_max_edge(tmp_path):
    p = tmp_path / "a.jpg"
    make_image(p, size=(1200, 800))
    out = read_preview(str(p), max_edge=200)
    im = Image.open(io.BytesIO(out))
    assert im.width <= 200 and im.height <= 200


def test_preview_keeps_ratio(tmp_path):
    p = tmp_path / "a.jpg"
    make_image(p, size=(1200, 800))
    out = read_preview(str(p))
    im = Image.open(io.BytesIO(out))
    assert im.width <= 800 and im.height <= 800
    assert abs(im.width / im.height - 1.5) < 0.01


def test_preview_png_to_jpeg(tmp_path):
    p = tmp_path / "a.png"
    make_image(p, size=(300, 300), fmt="PNG")
    out = read_preview(str(p))
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.mode == "RGB"


def test_preview_broken_file_raises(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"\x00\x01\x02 not a jpeg")
    with pytest.raises(ImageReadError):
        read_preview(str(p))


def test_preview_text_file_raises(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_text("plain text")
    with pytest.raises(ImageReadError):
        read_preview(str(p))


def test_preview_missing_file_raises(tmp_path):
    with pytest.raises(ImageReadError):
        read_preview(str(tmp_path / "nope.jpg"))


def test_preview_invalid_max_edge(tmp_path):
    p = tmp_path / "a.jpg"
    make_image(p)
    with pytest.raises(ImageReadError):
        read_preview(str(p), max_edge=0)
