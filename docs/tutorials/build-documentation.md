# 构建并浏览第一份文档

这篇教程带你从源码构建 SparkLink 文档，并在浏览器看到四类入口。
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
[文档维护指南](../how-to/write-documentation.md)。

