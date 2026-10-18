# 保存并核对双设备发现证据

目标是核对一次已执行的真实广播／扫描回归。前置条件：隔离 VM、两个当前 generation、普通用户 `slctl`、具有独立诊断权限的 capture 进程，以及原始 run/USB capture/捕获统计文件。不要从本站下载固件或将 capture 提交到公开站点。

1. 每轮选择两只不同物理设备，并生成新的随机 marker；保存完整 `slctl` 请求、结果和时间窗口。
2. 记录广播参数／数据／启停 Complete 与接收端报告；交换角色，核对 marker、载荷、地址、RSSI 及 10 秒期限。
3. 抓包另行授权。`slkmon --adapter INDEX --generation GENERATION --write mon.snoop --count 32` 的参数必须替换为本轮身份；不要抄固定 generation。
4. 封存原始 capture 及 kernel-drop 统计。DLI snoop 是协议 seam，不是 USB/HCC 全量捕获或 PHY 监听器。
5. 使用同一源码版本的离线核对器，在新目录生成报告：

```sh
python3 tools/ws73_north_star.py verify --run "$RUN_JSON" \
  --pcap "$USB_PCAP" --capture-stats "$CAPTURE_STATS" --output "$NEW_REPORT_DIR"
```

结果检查：核对器退出为零，并记录匹配源码、输入 hash 和完整范围。完整北极星还包含单设备物理拔插、另一只隔离和 daemon 不重启；缺少这些记录不能声称全项通过。

失败处理：丢包、时钟或 marker 不匹配、旧 generation、输出目录已存在均须保留失败，重新获得输入后另开目录。USB 写入、snoop status=0、日志或广播内容都不能代替连接后的对端应用收发验收。

[抓包格式与权限原文](../../project/reference/diagnostics/snoop.md)、[历史实机核对范围](../../project/reference/discovery/ws73-physical-test.md)；当前 socket 往返资格及长度边界以 [当前资格](../../project/current-capabilities.md) 为准。
