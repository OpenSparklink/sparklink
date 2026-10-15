# 构建和预览文档（贡献者）

任务：为修改文档的贡献者生成可审查的本地 HTML，并检查导航。
这不是 SparkLink 设备使用入门，适用于含 uv.lock 和本页工具链的源码版本。
不需要 WS73、实验内核或 sudo。

## 准备

需要 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和
Python 3.12–3.14。在已经取得的 SparkLink 仓库根目录操作；如果从 GitHub 获取源码，
请先切到包含这套文档基础设施的分支或提交。

确认工具：

```sh
uv --version
python3 --version
```

## 安装隔离的文档依赖

```sh
uv sync --locked --only-group docs
```

uv 根据仓库中的 `uv.lock` 创建本项目的 `.venv`。这不会安装 SparkLink 服务，
也不会使用 `bindings/python` 的 Python 包配置。

## 构建

```sh
make docs
```

命令会先检查文档清单，再使用 Sphinx 和 MyST 构建 HTML。
成功时退出码为零，输出入口是 `docs/_build/html/index.html`。

## 浏览

```sh
uv run --locked --only-group docs python -m http.server 8000 --bind 127.0.0.1 --directory docs/_build/html
```

打开 `http://127.0.0.1:8000/`。首页应出现教程、操作指南、技术参考和原理解释，
另有项目计划与历史记录入口。进入“技术参考”，再返回首页，确认导航可用。
按 Ctrl-C 停止本地服务器。

你现在已经得到一份本地文档站。继续写作时，使用
[文档维护指南](write-documentation.md)。


## 失败与清理

清单、示例、源码链接或严格构建失败时，保留完整输出，修复对应源文件后重新构建。
不要关闭警告或手改 HTML。停止预览按 Ctrl-C；`docs/_build/` 和 `.venv/` 都是
可重新生成的本地文件，不提交。外链和浏览器独立门禁见
[文档维护](write-documentation.md)；构建成功不代表功能或用户操作流程通过。
