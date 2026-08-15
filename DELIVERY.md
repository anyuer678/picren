# 交付清单 — 图片批量 AI 重命名/整理器（PicRename AI）

## 一、文件清单

```
main.py           CLI 入口：参数解析、API key 优先级、退出码、tags/undo 装配
pipeline.py       管道编排：收集 → 并发识别 → 渲染计划 → 执行/预览
vision.py         视觉模型调用与严格 JSON 解析（category 枚举校验，不访问文件系统）
reader.py         图片收集（递归/通配）与预览压缩（最长边 800px）
rename_rules.py   模板渲染、非法字符过滤、重名去重（绝不覆盖）
executor.py       改名执行 + undo_map 追加（拒绝覆盖已有目标）
undo.py           rename_map 解析、逆序回滚、mtime 恢复、原子写回
webui.py + webui.html   零依赖 Web 界面（标准库 http.server）
sample/           3 张示例图片 + gen_sample.py（Pillow 现造）
requirements.txt  Pillow + httpx
tests/
  test_rules.py   28 项：模板占位符/非法字符/去重/序号
  test_vision.py  21 项：JSON 解析/枚举校验/confidence 范围/重试
  test_reader.py  20 项：收集/递归/通配/预览压缩
  test_undo.py    15 项：map 解析/逆序回滚/mtime/坏行容错
  test_main.py    13 项：CLI 参数/退出码/API key 优先级/undo
```

## 二、验证结果（本机 Windows / Python 3.12.3）

- `python -m pytest tests/ -q` → **110 passed**
- 无 API Key：`picren --dir sample --dry-run` → 清晰报错（三种配置方式提示 + 隐私说明），退出码 1
- mock 视觉模型端到端：收集 3 张 → 识别 3/3 → 模板命名（`2026-08-08_旅行_东京塔_01_IMG_20230101_103055.jpg`）→ 真实改名 renamed=3 → `--undo` 回滚 restored=3
- Web 端到端：`GET /` → 200；`/api/health` ok；`/api/list?path=sample` 返回 3 张图片
- 安全：重名拒绝覆盖、改名记录 `rename_map.csv`、undo 恢复 mtime

## 三、接口核对清单（架构设计 §接口，全部通过）

- [x] `run_pipeline(PipelineConfig) -> PipelineReport`（planned/executed/failed/tags/elapsed_s）
- [x] `analyze(preview_bytes, ...) -> VisionResult`（subject/category/scene/confidence）
- [x] `apply_renames(ops, undo_map)` 绝不覆盖已有目标；`undo_from_map(path)` 逆序回滚
- [x] CLI 退出码：0 成功 / 1 参数错误或无 Key / 2 无匹配文件 / 3 识别质量过低中止
- [x] `--tags-only` 只生成 tags.csv 不改名；`--dry-run` 默认零副作用

## 四、本轮交付（前端重做 + 协议统一）

**前端重做（webui.html + webui.py，零新依赖）**

- 形态：标准库 `http.server` + 独立 HTML 页面，仅绑定 `127.0.0.1`
- 设计：kb-ui 风格设计令牌（CSS 变量），单一「侘寂」主题（米白灰 + 日式克制）
- 交互：目录浏览（上级/子目录/图片计数）→ 模板与参数配置 → 识别预览（进度条 + 原/新名表格）→ 执行确认 → 回滚；emoji 图标改为克制符号
- 安全：API Key 仅存浏览器内存/环境变量；`--execute` 前有确认

**协议**

- LICENSE 统一为 GPL-3.0（Copyright (C) 2026 anyuer678）；pyproject license 由 MIT 改为 GPL-3.0

## 五、安全与隐私

- 图片压缩至最长边 800px 后才发送到模型服务；支持完全本地模型（Ollama）
- 工具只做文件名/目录层操作，**绝不删除文件**；`--keep-original`（默认）保留原名可回溯
- 每次执行自动记录 `rename_map.csv`，可 `--undo` 一键回滚

## 六、与文档的偏差

- `dry-run` 预览仍需 API Key（识别是管道必经步骤，README 已说明配置顺序）
- 模板默认值含 `{subject}`；category 为封闭枚举（10 类），超出报错
