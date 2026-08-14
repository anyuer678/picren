# PicRename AI — 图片批量 AI 重命名/整理器

把 `IMG_20230101_103055.jpg` 变成 `旅行_日本_东京塔_2026.jpg`：AI 看图 → 中文语义命名 → 归档，一条龙。

- **安全第一**：默认 `--dry-run` 只预览，真实改名必须显式 `--execute`，且每次执行自动记录 `rename_map.csv`，可 `--undo` 一键回滚
- **绝不删文件**：只做文件名/目录层操作；`--keep-original`（默认开）让新名保留原名便于回溯
- **本地优先**：图片压缩至最长边 800px 后才发送给模型服务；完全本地模型（Ollama 等）也可用

## 安装

```bash
# 方式一：可编辑安装（推荐，含 picren 命令）
python -m venv .venv
.venv\Scripts\activate        # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -e .

# 方式二：不安装，直接用
.venv\Scripts\python.exe main.py --dir sample --dry-run
```

生成示例图（可选，供演示）：
```bash
.venv\Scripts\python.exe sample\gen_sample.py   # 用 Pillow 现造 3 张示例图片到 sample/
```

## 配置 API Key（必配，否则会清晰报错并退出）

按优先级读取：`--api-key` 参数 > 环境变量 `API_KEY` > 工作目录 `.env` 文件。

```bash
# 方式一：环境变量
set API_KEY=sk-xxxxxxxx          # Windows cmd
export API_KEY=sk-xxxxxxxx       # macOS/Linux

# 方式二：工作目录建 .env（推荐，一行即可）
echo API_KEY=sk-xxxxxxxx > .env
```

自托管/本地模型（如 Ollama 的 OpenAI 兼容端点）：
```bash
picren --dir photos --api-base http://localhost:11434/v1 --model qwen2.5vl --api-key ollama
```

## 模板语法表

| 占位符 | 含义 | 示例输出 |
|---|---|---|
| `{date}` | 拍摄日期（EXIF 优先，无则文件 mtime） | `2023-01-01` |
| `{date:%Y}` | 自定义日期格式（strftime） | `2023` |
| `{category}` | 场景分类（旅行/美食/文档/宠物/人物/街拍/风景/运动/建筑/其他） | `旅行` |
| `{subject}` | 主体名（AI 生成，中文 ≤4 词） | `东京塔` |
| `{scene}` | 场景描述 | `夜晚` |
| `{index}` | 自增序号（01 起） | `01` |
| `{ext}` | 原扩展名（小写） | `jpg` |

默认模板：`{date}_{category}_{subject}_{index}.{ext}`。目标名自动过滤 `/\:*?"<>|` 与首尾点、空格；重名自动追加 `_1` 序号，**绝不覆盖已有文件**。

## CLI 示例

```bash
# 1) 干跑预览（默认模式，不改任何文件）
picren --dir sample --dry-run

# 2) 按类别归档 + 真实执行（先自动展示预览，再改名，写 rename_map.csv）
picren --dir photos --execute --move-by-category

# 3) 只生成标签清单 tags.csv，人工核对后再决定
picren --dir photos --tags-only

# 4) 回滚上一次改名
picren --dir photos --undo

# 5) 自定义模板 + 并发 + JSON 输出
picren --dir photos --recursive --template "{date:%Y}_{category}_{scene}_{index}.{ext}" --workers 8 --json

# 6) 递归 + 指定模式
picren --dir photos --recursive --pattern "*.jpg" --pattern "*.png"
```

示例输出（`--dry-run`）：

```
[picren] 收集 3 张，成功识别 3 张（失败 0），耗时 1.2s：干跑预览（未修改任何文件）
  IMG_20230101_103055.jpg  ->  2023-01-01_旅行_东京塔_01_IMG_20230101_103055.jpg
  IMG_20230615_140020.jpg  ->  2023-06-15_美食_海鲜饭_02_IMG_20230615_140020.jpg
  photo_20240801.jpg       ->  2024-08-01_宠物_柯基犬_03_photo_20240801.jpg
```

## Web 前端（可选）

纯 Python 标准库实现的本地网页界面（`webui.py` + `webui.html`，**零额外依赖**），
功能与 CLI 等价：浏览目录、识别预览、确认执行、回滚、生成标签清单。

```bash
.venv\Scripts\python.exe webui.py --port 8787
# 浏览器打开 http://127.0.0.1:8787
```

- API Key 填在页面输入框（仅存于浏览器内存，不落盘），或留空走环境变量 `API_KEY` / `.env`
- 「识别并预览」= `--dry-run`；「确认执行改名」= `--execute`（点击前有二次确认，可回滚）
- 「生成 tags.csv」「回滚上次改名」对应 `--tags-only` / `--undo`
- 服务只监听 `127.0.0.1`，请勿将端口暴露到公网

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 参数错误（含缺少 API Key） |
| 2 | 无匹配图片文件 |
| 3 | 识别失败比例超过阈值（默认 20%）中止 |

## 测试

```bash
.venv\Scripts\python.exe -m pytest tests/test_main.py -q
```

`tests/test_main.py` 通过 `sys.modules` 注入契约一致的 stub，离线可测；运行时由真实模块替代。

## 隐私声明

- 图片在本地用 Pillow **压缩至最长边 ≤800px、JPEG 质量 80** 后，连同识别 prompt 一起发送给您配置的第三方模型服务；原图、EXIF、路径**不会**上传
- 仅 OpenAI 兼容 API（或自建本地模型端点），key 由您自备并自行管理，请勿将 key 提交到代码仓库
- `.env` 应加入 `.gitignore`
- 若使用云端服务，请知悉：压缩后的图片样本会离开本机

## 免责声明

- 本项目只做文件名/目录层操作，**绝不删除任何原文件**；改名可随时 `--undo` 回滚
- AI 识别结果仅供参考，可能存在错误；高风险场景请先用 `--tags-only` / `--dry-run` 人工核对
- 本项目不涉及人脸识别与身份信息判断，只做内容标签
- 使用本项目造成的任何损失由使用者自行承担，与作者无关
