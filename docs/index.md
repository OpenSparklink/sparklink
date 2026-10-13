# SparkLink 文档

SparkLink 的 Linux 子系统与用户态工具仍在开发中。阅读使用步骤前，请先查看
[当前能力与资格](CURRENT_CAPABILITIES.md)：目标架构、代码存在和历史实机通过
分别描述不同事实。

文档按 [Diátaxis](https://diataxis.fr/) 的四类读者需求组织：

| 你想做什么 | 从哪里开始 |
|---|---|
| 跟着步骤学习，第一次得到一个明确结果 | [教程](tutorials/index.md) |
| 已有具体任务，寻找操作步骤 | [操作指南](how-to/index.md) |
| 查找接口、配置、权限和错误的准确契约 | [技术参考](reference/index.md) |
| 理解分层、所有权与设计取舍 | [原理解释](explanation/index.md) |

实验驱动和真实 WS73 I/O 的当前开发约束是 **VM-only**。文档构建和纯离线验证
可以在主机执行。用户态业务应用无需 sudo；环境管理和底层诊断权限另有边界。

```{toctree}
:maxdepth: 2

tutorials/index
how-to/index
reference/index
explanation/index
project/index
history/index
decisions/index
evidence/index
```

项目计划、资格矩阵和历史故障记录有独立入口，不冒充教程或当前 API 承诺。


[按主题查找46份大写原文与阅读去向](project/uppercase-document-guide.md)。
