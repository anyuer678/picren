# PicRename AI —— 图片批量 AI 重命名/整理器

> 把 `IMG_20230101_103055.jpg` 变成 `旅行_日本_东京塔_2026.jpg`：AI 看图 → 中文语义命名 → 归档，一条龙。

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-110%20passed-brightgreen)](tests/)
[![Deps](https://img.shields.io/badge/deps-Pillow%20%2B%20httpx-blueviolet)](requirements.txt)

高频、隐私刚需场景：相册几百张图批量整理。图片压缩至最长边 800px 后才发送给视觉模型，支持完全本地模型（Ollama 等）。

## 功能特性

| 能力 | 说明 |
|---|---|
| AI 视觉识别 | 主体/场景分类/置信度，category 封闭枚举校验（旅行/美食/文档/宠物/人物/街拍/风景/运动/建筑/其他） |
| 模板化命名 | `{date}_{category}_{subject}_{index}.{ext}`，支持 strftime 自定义日期格式 |
| 安全第一 | 默认 `--dry-run` 只预览；真实改名必须显式 `--execute` |
| 可回滚 | 每次执行记录 `rename_map.csv`，`--undo` 一键回滚（含 mtime 恢复） |
| 绝不覆盖 | 目标重名自动追加 `_1` 序号；非法字符过滤；可选按类别移入子目录 |
| 三种界面 | CLI / 零依赖 Web UI / JSON 输出 |

## 快速开始

```bash
pip install -e .        # 安装 picren 命令（Pillow / httpx 自动装）

# 生成示例图（可选）
python sample\gen_sample.py

# 配置 API Key（优先级：--api-key > 环境变量 API_KEY > 工作目录 .env）
set API_KEY=sk-xxxx     # Windows

# dry-run 预览（默认，不修改任何文件）
picren --dir sample --dry-run

# 真实执行（自动记录 rename_map.csv，可 --undo 回滚）
picren --dir photos --execute --move-by-category

# 回滚
picren --dir photos --undo

# 本地模型（Ollama OpenAI 兼容端点）
picren --dir photos --api-base http://localhost:11434/v1 --model qwen2.5vl --api-key ollama
```

## 命令参考

| 参数 | 说明 |
|---|---|
| `--dir DIR` | 图片目录（必选） |
| `--recursive` | 递归子目录 |
| `--pattern "*.jpg"` | 扩展名/通配模式，可重复 |
| `--template` | 命名模板（默认 `{date}_{category}_{subject}_{index}.{ext}`） |
| `--dry-run` / `--execute` | 预览 / 执行（默认预览） |
| `--undo` | 回滚最近的 rename_map.csv |
| `--move-by-category` | 按类别移入子目录 |
| `--tags-only` | 只生成 tags.csv，不改名 |
| `--workers N` | 并发线程数（默认 4） |

退出码：`0` 成功 · `1` 参数错误/无 Key · `2` 无匹配文件 · `3` 识别质量过低（超过 `--max-fail-ratio` 阈值中止）。

## 项目结构

```
main.py           CLI 入口、API key 优先级、退出码
pipeline.py       收集 → 并发识别 → 渲染计划 → 执行/预览
vision.py         视觉模型调用与严格 JSON 解析（不访问文件系统）
reader.py         图片收集与预览压缩
rename_rules.py   模板渲染、非法字符过滤、重名去重
executor.py       改名执行 + undo_map 追加（绝不覆盖）
undo.py           回滚解析与逆序执行
webui.py + webui.html   零依赖 Web 界面
tests/            pytest 测试（110 例，不触网）
```

## 测试

```bash
python -m pytest tests/ -q
```

## 隐私与免责

- 图片压缩至最长边 800px 后才发送到模型服务；完全本地模型（Ollama）可零上传使用。
- 工具只做文件名/目录层操作，**绝不删除文件**；`--keep-original`（默认开）让新名保留原名便于回溯。
- AI 命名仅供参考，执行前请核对 dry-run 预览；建议在副本目录上先试验。

本项目仅供学习交流与演示用途，不构成任何形式的商业服务或技术承诺。软件按「现状」提供，不作任何明示或暗示的保证，包括但不限于适销性、特定用途适用性与非侵权性。
您理解并同意：使用本项目即表示您自行承担全部风险。如您在使用过程中发现缺陷或问题，欢迎通过 GitHub Issues 反馈，但作者不因使用本软件所直接或间接产生的任何损失（包括但不限于数据丢失、业务中断、第三方索赔）承担责任。
本项目以功能演示与学习交流为主要目的，其架构设计、安全基线、容错机制与性能表现均未按生产级标准进行验证与加固，不适用于实际生产环境或关键业务场景。任何将本项目部署于生产系统、对外提供服务、或将其接入真实业务工作流的做法，均属使用者的自主决策行为；由此产生的任何直接或间接不良后果，包括但不限于服务中断、数据损坏或泄露、业务损失、合规风险、以及因依赖本软件而引发的第三方纠纷，**开发者均不承担任何责任**。若您确有生产级使用需求，请在充分评估与自行加固（包括但不限于安全审计、压力测试、代码审查）后，自行承担相应风险。

## License

[GPL-3.0](LICENSE) — Copyright (C) 2026 anyuer678
