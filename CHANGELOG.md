# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- d1e145a chore: 版本 0.1.0 → 0.1.1（0.1.0 的 PyPI 包缺依赖声明，需重传）
- 07651cc fix: 删除 requirements.txt 重复声明源（钉死 Pillow==12.2.0 覆盖了 pyproject 的 >=12.3.0），CI 改从 pyproject 安装
- 40a149f fix: Pillow 下限提至 12.3.0（pip-audit 发现 12.2.0 存在 20 个已知漏洞）
- 0e77e53 ci: 添加依赖安全审计步骤（npm audit / pip-audit）
- 7f3c7fd fix: 补声明 Pillow/httpx 依赖（原 dependencies 为空，全新安装后 reader/vision 导入即崩）
- 0107113 fix: 包布局重构——平铺 py-modules 改为 picren/ 正式包
- e34f7a7 fix: --dry-run 与 --execute 互斥生效；API key 环境变量统一 PICREN_API_KEY
- 24f3a55 fix: normalize Windows backslashes in _to_abs for Linux CI
- df83bdb ci: use python -m pytest instead of pytest (fix exit code 127)
- 9bd07f1 ci: add GITHUB_STEP_SUMMARY for failure debugging
- 77780f0 ci: add pytest CI workflow
- 68411f2 fix: 完全重写 pyproject.toml，修复损坏的文件
- fc0be4c fix: pyproject.toml license GPL-3.0 → MIT，与 LICENSE 文件一致
- eae7b28 chore: 替换为标准 SPDX MIT 许可证
- 37c2819 docs: 合并隐私与免责章节
- f1406ce docs: 补充免责声明
- c8096f6 chore: 依赖精确锁定（== 版本，消除供应链漂移风险）
- 13c1060 docs: 新增交付报告（DELIVERY.md）
- 8e37d3d feat: 重做 Web 前端（侘寂单主题）+ GPL-3.0 协议
- 70cb42e chore: 初始化图片批量 AI 重命名器（PicRename AI）

