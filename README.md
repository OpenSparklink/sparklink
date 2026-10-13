# SparkLink

SparkLink 的 Linux 子系统和 Rust 用户态工具正在开发，提供每控制器管理、监控及应用通道的基础设施。
已有特定提交在隔离 VM 中完成真实 WS73 广播扫描、连接和普通用户短消息双向往返；这不表示完整生态或当前镜像已经验收。

- [文档：按读者任务导航](docs/index.md)
- [当前能力、准确提交与限制](docs/CURRENT_CAPABILITIES.md)
- [目标架构](docs/ARCHITECTURE.md)、[唯一实施计划](docs/IMPLEMENTATION_PLAN.md)
- [贡献规范](AGENTS.md)

实验驱动和真实 WS73 测试保持 **VM-only**。自然故障根因、非人工自动恢复及未完成的 SSAP、安全和发布事项继续开放。UAPI 尚未发布。

文档使用独立的 uv 环境，不打包 Rust 项目或 Python 绑定：

```sh
uv sync --locked --only-group docs
make docs
make docs-live
```

预览仅监听本机；外部链接另用 `make docs-linkcheck`。HTML artifact 由文档 CI 提供，本批不发布 GitHub Pages。
