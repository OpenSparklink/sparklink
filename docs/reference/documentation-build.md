# 文档构建配置

| 项目 | 约定 |
|---|---|
| 环境管理 | 根目录 `pyproject.toml` 的 `docs` dependency group |
| 依赖锁定 | 提交 `uv.lock`；本地和 CI 使用 `--locked` |
| Python | 3.12–3.14；CI 使用 3.12 |
| 源格式 | MyST Markdown；Sphinx 也接受 reStructuredText |
| 构建入口 | `docs/conf.py` 和 `docs/index.md` |
| 主题／语言 | Sphinx Book Theme／简体中文；原有英文内容保留 |
| 构建结果 | `docs/_build/html/`，不提交到 Git |
| 严格门禁 | 清单检查 + `sphinx-build -n -W --keep-going` |
| 本地预览 | `make docs-live`；只监听 127.0.0.1 |
| 外部链接 | `make docs-linkcheck`；独立、需要网络 |
| CI | 构建并上传 HTML artifact；没有自动发布或部署步骤 |
| 文档清单 | `docs/documentation-map.toml` |
| 当前审计快照 | `docs/_build/documentation-audit.json`，包含当前源码 hash、dirty 状态及逐篇处置；与 HTML 一起作为 CI artifact |

根目录 Python 项目只管理文档工具，不构建或安装 SparkLink Python 绑定。
文档构建不会执行示例中的 WS73 操作或固件部署。

Mermaid 浏览器渲染固定使用上游 11.12.1 JS，查看这些图需要访问 jsDelivr。
HTML 构建本身不下载该 JS。完全离线浏览和 PDF 图形导出尚未作为本批门禁；
需要时可单独引入经过校验、包含许可证的本地资源，不静默增加 Node 工具链。

旧文档路径在过渡期保持稳定。重新编排的是读者入口，尚未完成的内容拆分
明确记录在[迁移计划](../project/documentation-migration.md)。


中文搜索使用锁定的 jieba 分词。Sphinx 9.1 的中文搜索器实际使用 EnglishStemmer，
本站以局部注册修正其错误的 JavaScript 构造器名称，保留原中文索引规则。
升级 Sphinx 后必须重新检查中文和接口名称搜索，不能仅以 HTML 构建成功判断搜索可用。
官方配置与依赖约定见 [Sphinx 配置](https://www.sphinx-doc.org/en/master/usage/configuration.html)
及 [uv dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/)。

## DQ1 检查边界与失败处理

`make docs` 先执行文档检查负对照、Python 示例静态契约，再核对资格摘要、清单、
严格 HTML 与内部链接/资源。示例检查解析实际 Adapter/NativeAdapter 方法，不导入
动态库或执行设备操作；不声称参数语义、权限、运行或完整跨语言 ABI 已验收。

源码相对链接不存在或逃出仓库会使构建失败；私有材料须以明确的来源/hash/访问/
重放说明表达，不能自动替换成 unavailable 掩盖断链。源码链接不是内容验收。
HTML 根目录、首页、搜索及全部预期发布页必须存在且非空，构建输出中的
`documentation-build.json` 绑定准确文档 revision 与页面 hash；`--html` 对缺页、
被替换页面、坏 anchor、资源或不符版本失败。它不是签名来源证明或浏览器检查。

若审计失败，保留日志及原输出，修复源文件/清单/链接后重新执行完整构建；不要
手改生成 HTML、关闭 warnings-as-errors 或复用旧构建冒充当前。外链网络失败、
浏览器与使用流程重放继续独立记录，完整任务见唯一计划 DQ1–DQ5。

## 站点发布范围

按用户要求，HTML 仅构建首页和 tutorials／how-to／reference／explanation 四类。
project、history、decisions、evidence 原文保留仓库、清单和源码链接，**不构建**，
也不进入站点搜索。架构解释通过既有 include-only 入口读取唯一 architecture，
不复制正文；计划与资格链接指向准确提交中的 canonical 源文件。
检查器拒绝四类之外的 HTML。旧 URL 仅当旧路径和目标均在四类内时生成跳转；
排除的旧页面不生成跳转 HTML，路径映射和原始处置仍在仓库保留。

阅读主题采用 [Sphinx Book Theme](https://sphinx-book-theme.readthedocs.io/en/stable/)，
提供类似 GitBook 的章节导航与页内目录；不依赖 GitBook 托管或帐号。主题及依赖
由 uv.lock 固定，CSS/JS 随 HTML 构建输出。Mermaid 的 CDN 依赖仍单独保留；
主题变更须重查搜索、代码复制、宽表格、夜间/移动布局与 `/sparklink/` 子路径。

Book Theme 1.4.0／PyData 0.20.0 的组合会保留隐藏的父导航和重复 toggle；
本站通过标准 `layout.html` 模板扩展只保留 Book 阅读控件，保留父主题 scroll-spy
所需的空几何锚点。浏览器门禁要求唯一 toggle、真实移动菜单和实际复制/粘贴；
升级主题时重新核对模板与行为。两个未渲染的上游 webpack Jinja 模板不随产物发布，
其余主题资源仍受完整性检查；两主题 LICENSE 随 `_static/licenses/` 分发。
