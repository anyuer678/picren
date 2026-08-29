"""图片收集与预览压缩。"""

import io
import os
from dataclasses import dataclass
from datetime import datetime

from PIL import ExifTags, Image, ImageOps


@dataclass
class ImageFile:
    """一张图片的元信息。"""

    path: str
    taken_at: datetime | None
    width: int
    height: int
    ext: str


class ImageReadError(Exception):
    """图片读取或解码失败。"""


_DATETIME_ORIGINAL = 0x9003
_EXIF_DT_FORMAT = "%Y:%m:%d %H:%M:%S"


def _normalize_patterns(patterns):
    """把扩展名模式统一为小写、无点、无星号的集合。"""
    exts = set()
    for p in patterns:
        p = p.strip().lower().lstrip("*")
        p = p[1:] if p.startswith(".") else p
        if p:
            exts.add(p)
    return exts


def _read_datetime_original(im):
    """读取 EXIF DateTimeOriginal（顶层 IFD 与 ExifIFD 均查），无则返回 None。"""
    try:
        exif = im.getexif()
    except Exception:
        return None
    raw = None
    try:
        raw = exif.get(_DATETIME_ORIGINAL)
    except Exception:
        pass
    if not raw:
        try:
            raw = exif.get_ifd(ExifTags.IFD.Exif).get(_DATETIME_ORIGINAL)
        except Exception:
            pass
    if not raw:
        return None
    try:
        return datetime.strptime(raw, _EXIF_DT_FORMAT)
    except (TypeError, ValueError):
        return None


def _build_image_file(path):
    """读取单张图片的元信息，解码失败时宽高为 0 但仍返回。"""
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    width = height = 0
    taken_at = mtime
    try:
        with Image.open(path) as im:
            width, height = im.size
            exif_dt = _read_datetime_original(im)
            if exif_dt is not None:
                taken_at = exif_dt
    except Exception:
        pass
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ImageFile(path=path, taken_at=taken_at, width=width, height=height, ext=ext)


def collect_images(directory, *, recursive, patterns=[".jpg", ".jpeg", ".png", ".heic", ".webp"]):
    """按扩展名过滤收集目录内图片元信息，recursive 控制是否递归子目录。"""
    if not os.path.isdir(directory):
        return []
    exts = _normalize_patterns(patterns)
    if recursive:
        walker = os.walk(directory)
    else:
        try:
            walker = iter([(directory, [], os.listdir(directory))])
        except OSError:
            return []
    images = []
    for root, _dirs, names in walker:
        for name in names:
            if os.path.splitext(name)[1].lower().lstrip(".") not in exts:
                continue
            images.append(_build_image_file(os.path.join(root, name)))
    images.sort(key=lambda f: f.path)
    return images


def read_preview(path, max_edge=800):
    """将图片压缩为最长边≤max_edge的JPEG(质量80)字节流，失败抛ImageReadError。"""
    try:
        if max_edge <= 0:
            raise ValueError("max_edge 必须为正数")
        with Image.open(path) as im:
            ImageOps.exif_transpose(im, in_place=True)
            im.thumbnail((max_edge, max_edge))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
            return buf.getvalue()
    except ImageReadError:
        raise
    except Exception as exc:
        raise ImageReadError(f"无法读取图片 {path!r}: {exc}") from exc
