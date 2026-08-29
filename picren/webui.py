"""PicRename AI - 简单本地 Web 前端（纯 Python 标准库，零额外依赖）。

用法：
    python webui.py [--port 8787]

浏览器打开 http://127.0.0.1:8787 即可使用（页面文件 webui.html 需与
本文件同目录）。API Key 填在页面（仅存于浏览器内存，不落盘），或留空
使用环境变量 API_KEY / .env（与 CLI 一致）。服务只监听 127.0.0.1，
请勿暴露到公网。

端点：
    GET  /              前端页面（webui.html）
    GET  /api/list      列出目录（?path= 或 POST JSON）
    POST /api/preview   dry-run 预览计划
    POST /api/execute   执行改名（写 rename_map.csv）
    POST /api/undo      回滚 rename_map.csv
    POST /api/tags      生成 tags.csv
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import main as cli  # 复用 _load_api_key / _write_tags_csv / KEY_HINT / _iter_plan
from .pipeline import DEFAULT_PATTERNS, UNDO_MAP_NAME, PipelineConfig, run_pipeline
from .undo import undo_from_map

_HERE = os.path.dirname(os.path.abspath(__file__))
_PAGE_PATH = os.path.join(_HERE, "webui.html")
_PAGE_CACHE = None

IMAGE_EXTS = {p.strip().lower().lstrip("*").lstrip(".") for p in DEFAULT_PATTERNS if p.strip()}


def _load_page() -> bytes:
    global _PAGE_CACHE
    if _PAGE_CACHE is None:
        with open(_PAGE_PATH, encoding="utf-8") as fh:
            _PAGE_CACHE = fh.read().encode("utf-8")
    return _PAGE_CACHE


def _is_image(name: str) -> bool:
    return os.path.splitext(name)[1].lower().lstrip(".") in IMAGE_EXTS


def _build_cfg(directory: str, post: dict, dry_run_first: bool) -> PipelineConfig:
    patterns = None
    raw = (post.get("patterns") or "").strip()
    if raw:
        patterns = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
    try:
        workers = max(1, int(post.get("workers") or 4))
    except (TypeError, ValueError):
        workers = 4
    try:
        max_fail = float(post.get("max_fail_ratio") or 0.2)
    except (TypeError, ValueError):
        max_fail = 0.2
    return PipelineConfig(
        directory=directory,
        recursive=bool(post.get("recursive")),
        patterns=patterns,
        template=(post.get("template") or "").strip() or None,
        dry_run_first=dry_run_first,
        workers=workers,
        api_base=(post.get("api_base") or "").strip() or None,
        model=(post.get("model") or "").strip() or None,
        api_key=(post.get("api_key") or "").strip(),
        move_by_category=bool(post.get("move_by_category")),
        keep_original=bool(post.get("keep_original", True)),
        max_fail_ratio=max_fail,
    )


def _api_key_hint(post: dict) -> str:
    key = (post.get("api_key") or "").strip()
    if key:
        return key
    return os.environ.get("API_KEY", "") or cli._load_api_key("") or ""


def _rel(base: str, path: str) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


def api_list(path: str) -> dict:
    path = os.path.abspath(path or os.getcwd())
    if not os.path.isdir(path):
        return {"ok": False, "error": f"目录不存在：{path}"}
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append({
            "name": name,
            "is_dir": os.path.isdir(full),
            "is_image": _is_image(name),
        })
    return {
        "ok": True,
        "path": path,
        "parent": os.path.dirname(path),
        "image_count": sum(1 for e in entries if e["is_image"]),
        "entries": entries,
    }


def api_preview(directory: str, post: dict) -> dict:
    if not _api_key_hint(post):
        return {"ok": False, "need_key": True,
                "error": "未配置 API Key：请在页面填写，或设置环境变量 API_KEY"}
    if not os.path.isdir(directory):
        return {"ok": False, "error": f"目录不存在：{directory}"}
    cfg = _build_cfg(directory, post, dry_run_first=True)
    report = run_pipeline(cfg)
    items = []
    for op in cli._iter_plan(report.planned):
        src, dst = op
        items.append({"src": _rel(directory, src), "dst": _rel(directory, dst)})
    return {
        "ok": True,
        "total": len(report.tags) + len(report.failed),
        "recognized": len(report.tags),
        "failed": [[_rel(directory, p), err] for p, err in report.failed],
        "planned": items,
        "elapsed_s": round(report.elapsed_s, 2),
    }


def api_execute(directory: str, post: dict) -> dict:
    if not _api_key_hint(post):
        return {"ok": False, "need_key": True,
                "error": "未配置 API Key：请在页面填写，或设置环境变量 API_KEY"}
    if not os.path.isdir(directory):
        return {"ok": False, "error": f"目录不存在：{directory}"}
    cfg = _build_cfg(directory, post, dry_run_first=False)
    report = run_pipeline(cfg)
    if report.executed is None:
        return {"ok": False, "error": "无可用计划（可能识别失败比例过高）",
                "failed": [[_rel(directory, p), err] for p, err in report.failed]}
    return {
        "ok": True,
        "renamed": report.executed.renamed,
        "failed": [[src, err] for src, err in report.executed.failed],
        "elapsed_s": round(report.elapsed_s, 2),
    }


def api_undo(directory: str, post: dict) -> dict:
    directory = os.path.abspath(directory or os.getcwd())
    map_path = os.path.join(directory, UNDO_MAP_NAME)
    if not os.path.exists(map_path):
        return {"ok": False, "error": f"未找到回滚映射：{map_path}"}
    stats = undo_from_map(map_path)
    return {
        "ok": True,
        "renamed": stats.renamed,
        "failed": list(stats.failed),
    }


def api_tags(directory: str, post: dict) -> dict:
    if not _api_key_hint(post):
        return {"ok": False, "need_key": True,
                "error": "未配置 API Key：请在页面填写，或设置环境变量 API_KEY"}
    if not os.path.isdir(directory):
        return {"ok": False, "error": f"目录不存在：{directory}"}
    cfg = _build_cfg(directory, post, dry_run_first=True)
    report = run_pipeline(cfg)
    path = cli._write_tags_csv(directory, report)
    return {"ok": True, "path": path, "rows": len(report.tags),
            "failed": len(report.failed)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安静日志
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _post(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self._send(200, _load_page(), "text/html")
        elif parsed.path == "/api/list":
            self._json(api_list((query.get("path", [""])[0] or "").strip()))
        elif parsed.path == "/api/health":
            self._json({"ok": True, "app": "picren-webui"})
        else:
            self._json({"ok": False, "error": f"未知端点：{parsed.path}"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        post = self._post()
        query = parse_qs(parsed.query)
        d = (post.get("dir") or query.get("dir", [""])[0] or "").strip()
        try:
            if parsed.path == "/api/list":
                self._json(api_list(d))
            elif parsed.path == "/api/preview":
                self._json(api_preview(d, post))
            elif parsed.path == "/api/execute":
                self._json(api_execute(d, post))
            elif parsed.path == "/api/undo":
                self._json(api_undo(d, post))
            elif parsed.path == "/api/tags":
                self._json(api_tags(d, post))
            else:
                self._json({"ok": False, "error": f"未知端点：{parsed.path}"}, 404)
        except Exception as exc:  # 服务端异常不崩溃
            self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PicRename AI 本地 Web 前端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[picren-webui] 打开 http://{args.host}:{args.port} 开始使用（Ctrl+C 退出）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[picren-webui] 已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
