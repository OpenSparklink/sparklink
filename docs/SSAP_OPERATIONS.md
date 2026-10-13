# SSAP 权限契约：历史整改与当前入口

有效权限位、mask、缩窄和安全边界已抽到[权限参考](reference/ssap-permissions.md)。
旧生产内核数据库/staging 与 SSAP ioctl 已剥离；不能继续把旧构造器消费者
描述为当前内核业务实现。实验 Profile 不构成默认 daemon 能力。

[完整旧整改记录（准确提交）](https://github.com/OpenSparklink/sparklink/blob/ac64b3566f330557a025f1994b0a6f49a22b3bd3/docs/SSAP_OPERATIONS.md)
保留2026-10-11标准来源、2052组权限输入、历史固件回归及未完成条件。
历史 PASS 不转授给当前 actor 或真实 SSAP。保留权限类型与跨语言回归，禁止另造语义。

[旧路径剥离清单](SSAP_PRODUCTION_SEPARATION_20261013.md)、
[唯一计划](IMPLEMENTATION_PLAN.md)和[全部原文归纳](project/uppercase-document-guide.md)
分别说明迁移、剩余工作和阅读去向。
