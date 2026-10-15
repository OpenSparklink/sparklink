# SparkLink 文档

SparkLink 的 Linux 子系统与用户态工具仍在开发中。阅读使用步骤前，请先查看
[当前能力与资格](../project/current-capabilities.md)：目标架构、代码存在和历史实机通过
分别描述不同事实。

先从你的任务开始。设备和应用学习入口见[双设备消息教程](tutorials/first-ws73-message.md)
（限已准备的实验 VM，完整入门流程仍待重放）；能力与限制始终单独核对。
项目文档按 [Diátaxis](https://diataxis.fr/) 区分下列读者需求：

| 你想做什么 | 从哪里开始 |
|---|---|
| 初次使用真实设备，学习发送和回复 | [教程](tutorials/index.md) |
| 已有具体任务，寻找操作步骤 | [操作指南](how-to/index.md) |
| 查找接口、配置、权限和错误的准确契约 | [技术参考](reference/index.md) |
| 理解分层、所有权与设计取舍 | [原理解释](explanation/index.md) |

实验驱动和真实 WS73 I/O 的当前开发约束是 **VM-only**。文档构建和纯离线验证
可以在主机执行。用户态业务应用无需 sudo；环境管理和底层诊断权限另有边界。

```{toctree}
:maxdepth: 1

tutorials/index
how-to/index
reference/index
explanation/index
```

项目计划、资格矩阵、ADR、审计、历史与证据只保留仓库源码入口，不构建为本站页面。
首页与上述四类是唯一公开 HTML 内容，搜索/索引和静态资源仅服务这些页面。
