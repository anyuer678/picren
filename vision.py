"""OpenAI 兼容多模态接口调用与严格 JSON 解析（vision 不访问文件系统）。"""

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

REQUIRED_KEYS = ("subject", "category", "scene", "confidence")
CATEGORIES = ("旅行", "美食", "文档", "宠物", "人物", "街拍", "风景", "运动", "建筑", "其他")
ENV_API_KEYS = ("PICREN_API_KEY", "PICRENAME_API_KEY")  # 首选专用名，旧名兼容


@dataclass
class VisionResult:
    subject: str        # 中文 ≤4 词
    category: str       # CATEGORIES 枚举之一
    scene: str
    confidence: float   # 0~1
    raw: dict


class VisionError(Exception):
    """网络或解析失败。"""


def build_vision_prompt() -> str:
    """返回带封闭枚举与 JSON 输出要求的视觉识别 prompt。"""
    enum = "、".join(CATEGORIES)
    return (
        "你是图片内容识别助手。请分析这张图片，并只返回一个 JSON 对象，不要输出任何其他文字。\n"
        "JSON 字段要求：\n"
        '1. "subject"：图片主体，用中文描述，不超过 4 个词（例如 "东京塔"、"海边日落"）。\n'
        '2. "category"：必须是以下枚举值之一：' + enum + "。\n"
        '3. "scene"：场景描述，中文，简短（例如 "夜晚"、"室内"、"海边"）。\n'
        '4. "confidence"：0 到 1 之间的小数，表示识别置信度。\n'
        '只返回 JSON，格式如下：\n'
        '{"subject": "主体", "category": "分类", "scene": "场景", "confidence": 0.9}'
    )


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_json(text: str) -> VisionResult:
    """严格解析 LLM JSON 文本，兼容 markdown 包裹与 extra fields。"""
    try:
        data = json.loads(_strip_code_fence(text))
    except ValueError as exc:
        raise VisionError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise VisionError("JSON 顶层必须是对象")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise VisionError(f"缺少必需字段: {missing}")
    subject, category, scene, confidence = (
        data["subject"], data["category"], data["scene"], data["confidence"],
    )
    if not isinstance(subject, str) or not subject.strip():
        raise VisionError("subject 必须是非空字符串")
    if not isinstance(scene, str) or not scene.strip():
        raise VisionError("scene 必须是非空字符串")
    if category not in CATEGORIES:
        raise VisionError(f"category 不在枚举中: {category!r}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise VisionError("confidence 必须是数字")
    confidence_f = float(confidence)
    if not 0.0 <= confidence_f <= 1.0:
        raise VisionError(f"confidence 超出 [0,1]: {confidence_f}")
    return VisionResult(
        subject=subject.strip(),
        category=category,
        scene=scene.strip(),
        confidence=confidence_f,
        raw=data,
    )


def _build_payload(model: str, prompt: str, data_url: str) -> Dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }


def _post_chat_completions(api_base: str, model: str, prompt: str, data_url: str,
                           api_key: str, timeout_s: int) -> str:
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = _build_payload(model, prompt, data_url)
    with httpx.Client(timeout=timeout_s, headers=headers) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError as exc:
            raise VisionError(f"响应不是合法 JSON: {exc}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionError(f"响应结构缺少 content: {exc}") from exc
    if not isinstance(content, str):
        raise VisionError("响应 content 不是字符串")
    return content


def analyze(preview_bytes: bytes, *, api_base: str, model: str,
            api_key: str, timeout_s: int = 30, retries: int = 1) -> VisionResult:
    """发送压缩图调用视觉模型，失败按 retries 重试，仍失败抛 VisionError。"""
    key = api_key or next((os.environ.get(n, "") for n in ENV_API_KEYS if os.environ.get(n)), "")
    if not key:
        raise VisionError("缺少 API key：请传参 api_key 或设置环境变量 PICREN_API_KEY")
    prompt = build_vision_prompt()
    data_url = "data:image/jpeg;base64," + base64.b64encode(preview_bytes).decode("ascii")
    attempts = max(0, retries) + 1
    last_exc: Optional[Exception] = None
    for _ in range(attempts):
        try:
            content = _post_chat_completions(api_base, model, prompt, data_url, key, timeout_s)
            return parse_json(content)
        except VisionError as exc:
            last_exc = exc
        except httpx.HTTPError as exc:
            last_exc = VisionError(f"网络请求失败: {exc}")
    assert last_exc is not None
    raise VisionError(f"视觉识别失败（已重试 {retries} 次）: {last_exc}") from last_exc
