# Tofino Traffic Manager 实验：限速与监控

本项目包含一组用于在 Tofino 交换机上进行流量管理（Traffic Manager, TM）实验的脚本。主要功能包括：在 egress 端口或队列上施加限速（Shaping）、实时观测队列堆积、水位（Watermark）以及丢包（Drops）情况。

**注意**：本 SDE 版本（bf-sde-9.13.0）的 BFRT API 不支持设置队列深度（Queue Depth）。队列深度配置需要通过其他方式（如控制平面 C 代码）实现。

---

## 🚀 快速上手

### 1. 实验拓扑

```
[Sender Host](192.168.5.2) ---> Tofino Switch(dev_port 189) ---> [Receiver Host](192.168.6.2)
```

### 2. 启动交换机程序

```bash
cd /home/qfr23/zgy/P4_Exp/p4
make
./contrl_test
```

### 3. 设置端口限速

对 dev_port=189 设置 120Mbps 限速：

```bash
./tm_shape_queue.sh apply --dev-port 189 --max-mbps 120
```

### 4. 生成实验脚本

```bash
python3 ./gen_experiment.py --config I --out-dir ./exp_scripts
```

生成的脚本：
- `run_sender_confI.sh` - 发送端脚本
- `run_receiver_confI.sh` - 接收端脚本

### 5. 运行实验

1. **Receiver 端**：运行 `run_receiver_confI.sh`
2. **Sender 端**：运行 `run_sender_confI.sh`
3. **Sender 端 (可选)**：运行 TCP 高精度采集器
   ```bash
   # 基础采集（仅 CSV）
   python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 1 --duration 500 --output ./exp_logs_I/tcp_metrics.csv
   
   # 采集 + 实时绘图
   python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 1 --duration 500 --output ./exp_logs_I/tcp_metrics.csv --plot --verbose
   ```
4. **交换机**：实时监控队列
   ```bash
   ./tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues
   ```

### 6. 数据处理与可视化

```bash
# 可视化 TCP 细粒度指标
python3 ./visualize_tcp_metrics.py --input ./exp_logs_I/tcp_metrics.csv --output ./exp_logs_I/plots
```

### 7. 实验清理

```bash
./tm_shape_queue.sh reset
```

---

## 🛠️ 脚本说明

### 1. `tm_shape_queue.sh` - 核心限速与监控工具

```bash
# 限速
./tm_shape_queue.sh apply --dev-port 189 --max-mbps 120

# 实时监控
./tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues --log-file ./tm.tsv

# 重置所有端口的限速
./tm_shape_queue.sh reset
```

### 2. `visualize_tm_queue.py` - TM 队列数据可视化

```bash
python3 ./visualize_tm_queue.py --tm-log ./tm.tsv --metric all --output tm_metrics.png
```

**支持的指标**：`queue_usage`, `queue_wm`, `drop_rate`, `rate`, `all`, `detailed`

### 3. `tcp_metrics_collector.py` - TCP 高精度指标采集

利用 `ss` 命令以毫秒级精度采集 TCP 连接状态（RTT, CWND, Delivery Rate, Retransmits 等）。

```bash
# 基础采集（仅 CSV）
python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 20 --duration 500 --output tcp_metrics.csv

# 采集 + 实时绘图
python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 20 --duration 500 --output tcp_metrics.csv --plot --verbose

# 自定义绘图参数
python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 20 --duration 500 --plot --plot-dir ./my_plots --plot-interval 500
```

**CSV 输出列**：
- `timestamp_ns` - 纳秒时间戳
- `local_port` - 本地端口号
- `remote_port` - 远程端口号
- `state` - TCP 连接状态
- `flow_type` - 流类型（cubic, prague, unknown）
- `flow_id` - 唯一流标识符
- `cwnd` - 拥塞窗口（段数）
- `rtt_us` - RTT（微秒）
- `rtt_var_us` - RTT 方差（微秒）
- `retrans` - 重传计数
- `lost` - 丢包计数
- `delivery_rate_bps` - 传输速率（比特/秒）

**实时绘图功能**：
- `--plot` - 启用实时绘图
- `--plot-dir` - 指定绘图输出目录（默认：`./plots`）
- `--plot-interval` - 指定绘图更新间隔（样本数，默认：1000）

生成的图表：
- RTT over Time
- Congestion Window over Time
- Delivery Rate over Time（对数坐标）
- Retransmits over Time

### 4. `visualize_tcp_metrics.py` - TCP 指标可视化

针对 TCP 指标 CSV 数据进行优化可视化，支持大规模数据点。兼容以下两种数据源：

1. **tcp_metrics_collector.py** 生成的 CSV 文件
2. **bpftrace** 生成的 CSV 文件（使用 `trace_tcp.bt`）

```bash
# 可视化 tcp_metrics_collector.py 生成的数据
python3 ./visualize_tcp_metrics.py --input ./exp_logs_I/tcp_metrics.csv --output ./exp_logs_I/plots

# 可视化 bpftrace 生成的数据（注：csv文件生成后需要修改文件首行，具体参考脚本中的注释）
sudo bpftrace trace_tcp.bt > tcp_metrics.csv
python3 ./visualize_tcp_metrics.py --input tcp_metrics.csv --output ./plots
```

**CSV 格式兼容性**：
- `tcp_metrics_collector.py` 和 `trace_tcp.bt` 生成的 CSV 文件格式完全一致
- CSV 列：`timestamp_ns, local_port, remote_port, state, flow_type, flow_id, cwnd, rtt_us, rtt_var_us, retrans, lost, delivery_rate_bps`
- `visualize_tcp_metrics.py` 自动读取所需列进行可视化

生成的图表：
- RTT over Time (Full Resolution)
- Congestion Window over Time (Full Resolution)
- Delivery Rate over Time (Full Resolution, 对数坐标)
- Retransmits over Time (Full Resolution)

### 5. `trace_tcp.bt` - BPFtrace TCP 指标采集

使用 BPFtrace 直接从内核采集 TCP 指标，提供另一种高精度数据采集方式。

```bash
# 运行 bpftrace 采集（需要 root 权限）
sudo bpftrace trace_tcp.bt > tcp_metrics.csv

# 可视化采集的数据
python3 ./visualize_tcp_metrics.py --input tcp_metrics.csv --output ./plots
```

**端口范围识别**：
- Cubic 流：端口 5201-5225
- Prague 流：端口 5226-5250

**采集指标**：
- `timestamp_ns` - 纳秒时间戳
- `local_port` - 本地端口号
- `remote_port` - 远程端口号
- `state` - TCP 连接状态
- `flow_type` - 流类型（cubic, prague）
- `flow_id` - 唯一流标识符
- `cwnd` - 拥塞窗口（段数）
- `rtt_us` - RTT（微秒）
- `rtt_var_us` - RTT 方差（微秒）
- `retrans` - 重传计数
- `lost` - 丢包计数
- `delivery_rate_bps` - 传输速率（比特/秒）

**与 tcp_metrics_collector.py 的对比**：

| 特性 | tcp_metrics_collector.py | trace_tcp.bt |
|------|-------------------------|--------------|
| 采集方式 | `ss` 命令 | BPFtrace 内核探针 |
| 精度 | 毫秒级 | 纳秒级 |
| 权限要求 | root/sudo | root/sudo |
| 实时绘图 | 支持 | 不支持 |
| CSV 格式 | 标准格式 | 完全兼容 |

### 6. 辅助脚本

- `bfrt_explore.sh` - 探索 BFRT API 所有可用接口
   ```bash
   ./bfrt_explore.sh                    # 探索所有 BFRT 接口
   ./bfrt_explore.sh --filter tm        # 过滤 TM 相关的表
   ./bfrt_explore.sh --list-tables      # 仅列出所有表
   ./bfrt_explore.sh --sde /path/sde    # 使用自定义 SDE 路径
   ```

- `check_queues.sh` - 扫描端口，显示端口计数器、限速配置
   ```bash
   ./check_queues.sh                    # 扫描 Pipe 1 (ports 128-255)
   ./check_queues.sh --pipe 0           # 扫描 Pipe 0 (ports 0-127)
   ./check_queues.sh --dev-port 189     # 查询特定端口
   ```

---

## 📊 实验配置 (Table 2)

| Config | Bandwidth | RTT | MTU |
|--------|-----------|-----|-----|
| I | 120 Mbps | 10ms | 1500B |
| II | 120 Mbps | 50ms | 1500B |
| III | 1000 Mbps | 10ms | 1500B |
| IV | 1000 Mbps | 50ms | 1500B |
| V | 120 Mbps | 10ms | 800B |
| VI | 120 Mbps | 50ms | 800B |
| VII | 1000 Mbps | 10ms | 800B |
| VIII | 1000 Mbps | 50ms | 800B |
| IX | 120 Mbps | 10ms | 400B |
| X | 120 Mbps | 50ms | 400B |
| XI | 1000 Mbps | 10ms | 400B |
| XII | 1000 Mbps | 50ms | 400B |

**负载阶段**：每阶段 120 秒，流数从 1 → 2 → 10 → 25 递增。

---

## ❓ 常见问题

1. **`could not initialize bf_rt ... err: 1`**
   - 确保已运行 `./contrl_test`

2. **重启程序后限速失效**
   - 重新运行 `apply` 命令

3. **重启交换机后两台主机无法ping通**
   - 在交换机上运行 `ifconfig enp4s0f0 up`
   - 在 receiver 端运行 `sudo ip route add 192.168.0.0/16 via 192.168.6.1`

