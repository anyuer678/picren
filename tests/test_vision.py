"""vision 模块测试：全部 stub/mock，不发起真实网络请求。"""

import json
import os
import sys
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vision

VALID_JSON = {
    "subject": "东京塔",
    "category": "旅行",
    "scene": "夜晚",
    "confidence": 0.92,
}


def ok_response(content=None):
    text = content if content is not None else json.dumps(VALID_JSON, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


class FakeClient:
    def __init__(self, handler, headers=None):
        self._handler = handler
        self._headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        headers = dict(self._headers)
        headers.update(kwargs.get("headers") or {})
        request = httpx.Request("POST", url, json=kwargs.get("json"), headers=headers)
        response = self._handler(request)
        response.request = request  # 绑定 request，raise_for_status 依赖它
        return response


def fake_client_patch(handler):
    def client_factory(*args, **client_kwargs):
        return FakeClient(handler, headers=client_kwargs.get("headers"))

    return patch("httpx.Client", side_effect=client_factory)


def run_analyze(responses, **kwargs):
    queue = list(responses)
    calls = []

    def handler(request):
        calls.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    with fake_client_patch(handler):
        result = vision.analyze(
            b"fake-jpeg-bytes",
            api_base="https://api.example.com/v1",
            model="qwen-vl",
            api_key=kwargs.pop("api_key", "test-key"),
            **kwargs,
        )
    return result, calls


# ---------------- parse_json ----------------

def test_parse_json_normal():
    result = vision.parse_json(json.dumps(VALID_JSON, ensure_ascii=False))
    assert result.subject == "东京塔"
    assert result.category == "旅行"
    assert result.scene == "夜晚"
    assert result.confidence == 0.92
    assert result.raw == VALID_JSON


def test_parse_json_markdown_fence():
    text = "```json\n" + json.dumps(VALID_JSON, ensure_ascii=False) + "\n```"
    result = vision.parse_json(text)
    assert result.subject == "东京塔"
    assert result.confidence == 0.92


def test_parse_json_extra_fields_tolerated():
    data = dict(VALID_JSON, location="东京", colors=["red", "white"])
    result = vision.parse_json(json.dumps(data, ensure_ascii=False))
    assert result.subject == "东京塔"
    assert result.raw["location"] == "东京"
    assert result.raw["colors"] == ["red", "white"]


@pytest.mark.parametrize("missing", list(vision.REQUIRED_KEYS))
def test_parse_json_missing_key_fails(missing):
    data = dict(VALID_JSON)
    del data[missing]
    with pytest.raises(vision.VisionError):
        vision.parse_json(json.dumps(data, ensure_ascii=False))


@pytest.mark.parametrize("bad_category", ["美食啊", "unknown", "", "旅行2", 123, None])
def test_parse_json_category_out_of_enum_fails(bad_category):
    data = dict(VALID_JSON, category=bad_category)
    with pytest.raises(vision.VisionError):
        vision.parse_json(json.dumps(data, ensure_ascii=False))


@pytest.mark.parametrize("bad_conf", [1.5, -0.1, "0.9", True, None, 2])
def test_parse_json_confidence_out_of_range_fails(bad_conf):
    data = dict(VALID_JSON, confidence=bad_conf)
    with pytest.raises(vision.VisionError):
        vision.parse_json(json.dumps(data, ensure_ascii=False))


def test_parse_json_confidence_bounds_accepted():
    for value in (0.0, 1.0, 0.0e0, 1):
        result = vision.parse_json(json.dumps(dict(VALID_JSON, confidence=value)))
        assert 0.0 <= result.confidence <= 1.0


def test_parse_json_not_json_text_fails():
    with pytest.raises(vision.VisionError):
        vision.parse_json("这不是 JSON 而是自然语言")


def test_parse_json_top_level_array_fails():
    with pytest.raises(vision.VisionError):
        vision.parse_json("[1, 2, 3]")


# ---------------- analyze ----------------

def test_analyze_success():
    result, calls = run_analyze([ok_response()])
    assert result.subject == "东京塔"
    assert result.category == "旅行"
    assert result.scene == "夜晚"
    assert result.confidence == 0.92
    assert len(calls) == 1


def test_analyze_retries_after_500_then_success():
    result, calls = run_analyze([httpx.Response(500), ok_response()], retries=1)
    assert result.subject == "东京塔"
    assert len(calls) == 2


def test_analyze_retries_after_bad_json_then_success():
    result, calls = run_analyze([httpx.Response(200, text="not-json"), ok_response()], retries=1)
    assert result.subject == "东京塔"
    assert len(calls) == 2


def test_analyze_retries_after_content_parse_failure():
    bad = httpx.Response(200, json={"choices": [{"message": {"content": '{"subject": "x"}'}}]})
    result, calls = run_analyze([bad, ok_response()], retries=1)
    assert result.category == "旅行"
    assert len(calls) == 2


def test_analyze_all_attempts_fail_raises_visionerror():
    with pytest.raises(vision.VisionError):
        run_analyze([httpx.Response(500), httpx.Response(500)], retries=1)


def test_analyze_timeout_raises_visionerror():
    with pytest.raises(vision.VisionError):
        run_analyze(
            [httpx.ConnectTimeout("timeout"), httpx.ConnectTimeout("timeout")],
            retries=1,
        )


def test_analyze_zero_retries_single_attempt():
    with pytest.raises(vision.VisionError):
        run_analyze([httpx.Response(500)], retries=0)


def test_analyze_missing_key_raises(monkeypatch):
    monkeypatch.delenv("PICRENAME_API_KEY", raising=False)
    with pytest.raises(vision.VisionError):
        vision.analyze(b"x", api_base="https://api.example.com/v1", model="m", api_key="")


def test_analyze_api_key_from_env(monkeypatch):
    monkeypatch.setenv("PICRENAME_API_KEY", "env-key")
    result, calls = run_analyze([ok_response()], api_key="")
    assert calls[0].headers["Authorization"] == "Bearer env-key"
    assert result.subject == "东京塔"


def test_analyze_payload_shape():
    queue = [ok_response()]
    seen = {}

    def handler(request):
        seen["request"] = request
        seen["body"] = json.loads(request.content)
        return queue.pop(0)

    with fake_client_patch(handler):
        vision.analyze(
            b"\xff\xd8jpeg",
            api_base="https://api.example.com/v1",
            model="qwen-vl",
            api_key="k",
        )
    req = seen["request"]
    assert str(req.url) == "https://api.example.com/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer k"
    body = seen["body"]
    assert body["model"] == "qwen-vl"
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert "旅行" in content[0]["text"]
    assert "category" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_analyze_api_base_trailing_slash():
    queue = [ok_response()]
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return queue.pop(0)

    with fake_client_patch(handler):
        vision.analyze(b"x", api_base="https://api.example.com/v1/", model="m", api_key="k")
    assert seen["url"] == "https://api.example.com/v1/chat/completions"


# ---------------- build_vision_prompt ----------------

def test_build_vision_prompt_contains_enum_and_json_requirements():
    prompt = vision.build_vision_prompt()
    for cat in vision.CATEGORIES:
        assert cat in prompt
    assert "JSON" in prompt
    assert "subject" in prompt and "category" in prompt
    assert "scene" in prompt and "confidence" in prompt
    assert "4 个词" in prompt
