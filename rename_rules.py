"""模板渲染、非法字符过滤、重名去重。"""

import os
import re


class TemplateError(ValueError):
    """模板占位符错误。"""


_INVALID_CHARS = '/\\:*?"<>|'
_TOKEN_RE = re.compile(r"\{(\w+)(?::([^}]*))?\}")


def render_template(template, img, result, index, index_pad=2):
    """按模板渲染文件名，未知占位符抛 TemplateError。"""
    def render_date(fmt):
        if img.taken_at is None:
            return ""
        return img.taken_at.strftime(fmt if fmt else "%Y-%m-%d")

    def replace(match):
        name = match.group(1)
        fmt = match.group(2)
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
    """去掉 /\\:*?\"<>| 及首尾的点和空格，保留中文与 emoji。"""
    cleaned = "".join(c for c in name if c not in _INVALID_CHARS)
    return cleaned.strip(" .")


def resolve_unique(target_dir, desired, taken):
    """目标目录已存在或已在 taken 中时追加 _{index} 去重，绝不覆盖。"""
    if desired not in taken and not os.path.exists(os.path.join(target_dir, desired)):
        return desired
    stem, sep, suffix = desired.rpartition(".")
    if sep:
        suffix = "." + suffix
    else:
        stem, suffix = desired, ""
    i = 1
    while True:
        candidate = f"{stem}_{i}{suffix}"
        if candidate not in taken and not os.path.exists(os.path.join(target_dir, candidate)):
            return candidate
        i += 1
