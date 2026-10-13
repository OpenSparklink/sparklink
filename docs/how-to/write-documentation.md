# 增补和验证文档

## 选择页面类型

先写清读者要解决的问题：

- 教程：读者跟随一次学习过程；说明环境、步骤和可观察结果。
- 操作指南：直接完成一个任务；说明前置条件、命令和失败处理。
- 技术参考：精确定义接口、配置、单位、权限、边界和错误。
- 原理解释：说明职责、因果关系、选择和取舍，不夹入长篇操作步骤。

新的计划和逐轮验收记录放入 `project/` 或 `history/`。
修改现有权威文档时，仍直接修改原文件，不另建一份当前能力或实施计划。

## 编写 MyST Markdown

新页面放在对应目录，并加入该目录 `index.md` 的 toctree。
Markdown 页面链接使用相对路径和 `.md` 后缀：

```markdown
[权限契约](../DBUS_AUTHORIZATION.md)
```

目录、提示和代码引用使用 MyST 指令。例如：

````markdown
```{note}
说明已验证的范围及仍缺失的条件。
```
````

避免手抄结构体大小、命令总数、测试数量或“全部完成”声明。
API 以源码和匹配的内核 UAPI 为准；资格以
[当前能力入口](../CURRENT_CAPABILITIES.md) 为准。

## 验证并预览

在仓库根目录执行：

```sh
make docs
make docs-live
```

`make docs` 将警告视为失败；不要通过全局忽略警告掩盖断链。
`make docs-live` 的服务器只监听本机，按 Ctrl-C 停止。

检查外部网站链接时执行：

```sh
make docs-linkcheck
```

外部检查需要网络。若遇到 GitHub 限流，应记录具体失败并复查；
不要把外部网络检查失败解释为硬件测试失败。

## 提交

只提交源码、构建配置和 `uv.lock`，不要提交 `.venv` 或 `docs/_build`。
按照仓库提交规范保留 Signed-off-by 与 Assisted-by。文档构建通过仅说明文档
门禁通过，不升级功能、形式化证明或真实设备验收资格。


## 独立浏览器门禁

严格构建不验证浏览器 JavaScript。需要 Firefox；此门禁是可选的文档 UI 检查，
不在 `make docs` 中启动浏览器、服务或硬件。先以 localhost 提供 HTML，
在独立 Firefox profile 启动 `--headless --no-remote --remote-debugging-port 9239`，
然后执行（输出目录必须是新目录）：

```sh
uv run --locked --only-group docs python tools/check_docs_browser.py \
  --websocket ws://127.0.0.1:9239/session \
  --base-url http://127.0.0.1:8769/sparklink/ \
  --output /tmp/sparklink-docs-ui-new
```

准备预览时，让服务器根下的 `sparklink/` 指向构建 HTML；这同时验证项目站点子路径。
不要连接现有浏览器 profile。完成后停止预览服务器和独立 Firefox。
门禁覆盖点击导航、完整接口词及中文搜索、代码块、表格、Mermaid、390 像素宽布局，
保存 JSON 和截图。查看截图后再记录视觉结论。搜索按词匹配，不承诺前缀自动补全。
Mermaid 仍需要已声明的 CDN 网络；失败必须记录，不能用 DOM 容器存在代替图形成功。
