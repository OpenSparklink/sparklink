# 文档构建配置

| 项目 | 约定 |
|---|---|
| 环境管理 | 根目录 `pyproject.toml` 的 `docs` dependency group |
| 依赖锁定 | 提交 `uv.lock`；本地和 CI 使用 `--locked` |
| Python | 3.12–3.14；CI 使用 3.12 |
| 源格式 | MyST Markdown；Sphinx 也接受 reStructuredText |
| 构建入口 | `docs/conf.py` 和 `docs/index.md` |
| 主题／语言 | Furo／简体中文；原有英文内容保留 |
| 构建结果 | `docs/_build/html/`，不提交到 Git |
| 严格门禁 | 清单检查 + `sphinx-build -n -W --keep-going` |
| 本地预览 | `make docs-live`；只监听 127.0.0.1 |
| 外部链接 | `make docs-linkcheck`；独立、需要网络 |
| CI | 构建并上传 HTML artifact；没有自动发布或部署步骤 |
| 文档清单 | `docs/documentation-map.toml` |

根目录 Python 项目只管理文档工具，不构建或安装 SparkLink Python 绑定。
文档构建不会执行示例中的 WS73 操作或固件部署。

Mermaid 浏览器渲染固定使用上游 11.12.1 JS，查看这些图需要访问 jsDelivr。
HTML 构建本身不下载该 JS。完全离线浏览和 PDF 图形导出尚未作为本批门禁；
需要时可单独引入经过校验、包含许可证的本地资源，不静默增加 Node 工具链。

旧文档路径在过渡期保持稳定。重新编排的是读者入口，尚未完成的内容拆分
明确记录在[迁移计划](../project/documentation-migration.md)。

