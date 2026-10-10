# PHY／加密状态的旧实现清理与开放条件

2026-10-11；Linux `f16ac912a8ff`、可见性修正 `f1704a2e44dc`。R09限定整改，
K7/K16/U4与完整安全/PHY验收仍OPEN。未发布UAPI无兼容期，最终调用者迁移后删除。

## 调用关系及清理

| 旧路径 | 本批处理 | 后续唯一来源 |
|---|---|---|
| core PHY setters → local PhyConfig → controller send_command | 删除生产setter及ControllerState.phy；全部8个PHY/SINR ioctl明确EOPNOTSUPP | 每连接、generation绑定的请求/事务/匹配硬件完成及确认快照 |
| PHY_INFO/MCS_SELECT/HOP_NEXT/SINR → 默认或估算模型 | 不再返回默认MCS4/1MHz/10dBm等“设备状态”；不生成模拟成功 | 实际控制器可证明的已确认值；未查询/未支持明确未知或不支持 |
| SEC_ENCRYPT_ON → enable_encryption先置Encrypted → 空参数StartEncrypt | legacy enable始终EOPNOTSUPP，不改凭据/状态/计数，不发送命令；删除无调用者StartEncrypt helper | 已认证每连接凭据、实际安装参数、匹配成功终态 |
| MCS/MIMO/PhyConfig/旧PHY codec | 移至专用selftests/phy-model，默认production不编译；保留边界/历史证据，不作为标准向量 | 需要标准核对、实际协商及硬件验收后重新设计，不能直接重新链接模型 |
| ChannelMap/HoppingState → sle_conn、core AFH | 仍有实际调用者，暂保留并缩为crate可见，删除原phy模块global lint压制 | 连接/socket迁移后审计和替换；其存在不代表硬件AFH/PHY支持 |

拒绝操作仍经既有权限/Runtime/管理租约检查；权限失败可先返回EPERM等错误。
本批没有修改Native WS73 typed discovery或增加测试密钥、伪造Complete和注入hook。
其余旧模块的global lint与旧DLI路径继续审计，不能称为整个内核清理已完成。

## 测试及证据范围

专用run_phy_model.py编译实际PHY拒绝match arm，命令常量标识/错误构造是fixture，
不代替实际ioctl编号/权限/VFS证明。3项测试编译隔离历史模型及实际production
channel-map/hopping，覆盖边界、环绕、空map、参数失败不改字段及codec本地roundtrip。
严格-D warnings，无global dead_code suppression；不是当前标准/WS73向量。

实际security模块新增回归遍历Idle/Pairing/Paired/Encrypted，预填密钥/SM4/counter后
legacy enable仍拒绝，状态、凭据、计数保持，无FFI调用。security7及原C失败阶段/
sanitizers本地通过；既有backend2、TX11、SSAP9、event9实际实现边界回归通过。
固定新kernel pin的CI增加模型/拒绝分支门禁；完整镜像和新VM实机回归结果另行记录，
之前`3a6669114069`的20+2/live read证据只支持当时源码，不能自动覆盖本次生产变化。

## 重新开放能力所需门禁

请求值、pending、已确认值明确分开；只有同controller/generation/connection请求的
匹配成功硬件终态可提交。backend接受、CommandStatus或无关/迟到Complete不能提交。
发送失败、拒绝、超时、取消、断链、退役保持最后确认值或显式未知。查询不得把模型
默认值或请求值称为硬件值。安全须有认证凭据/算法/长度/nonce、真实安装及安全强制，
不能仅把send调用移到本地setter之前就称为修复完成。

普通用户真实双设备数据、PHY策略及安全互通、旧generation/多连接隔离、标准向量/
Agent/Bond恢复均仍待验收。自然WS73超时/重枚举/消失根因和无人工恢复独立开放，
北极星7/8、VM-only与完整S0–S6不变。
