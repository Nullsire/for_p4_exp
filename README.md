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
python3 ./gen_experiment.py --config I --out-dir ./exp_
```

生成的脚本：
- `run_sender_confI.sh` - 发送端脚本
- `run_receiver_confI.sh` - 接收端脚本

### 5. 运行实验

1. **Receiver 端**：运行 `run_receiver_confI.sh`
2. **Sender 端**：运行 `run_sender_confI.sh`
3. **Sender 端 (可选)**：运行 TCP 高精度采集器
   ```bash
   # 采集 TCP 指标 (RTT, CWND 等) 到 tcp_metrics.csv
   # 建议 duration 略长于实验时长一致 (例如 500s)
   python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 1 --duration 500 --output ./exp_logs_I/tcp_metrics.csv
   ```
4. **交换机**：实时监控队列
   ```bash
   ./tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues
   ```

### 6. 数据处理与可视化

```bash
# 可视化 TCP 细粒度指标 (需先运行 tcp_metrics_collector.py)
python3 ./visualize_tcp_metrics.py --input ./exp_logs_I/tcp_metrics.csv --output ./exp_logs_I/plots
```

### 7. 实验清理

```bash
# 重置所有端口的限速
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

**注意**：本 SDE 版本不支持通过 BFRT API 设置队列深度。

### 2. `gen_experiment.py` - 实验脚本生成器

```bash
python3 ./gen_experiment.py --config I --out-dir ./ --log-dir ./exp_logs
```

**实验配置 (Table 2)**:

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

**支持的指标**：`goodput`, `bytes`, `retransmits`, `cwnd`, `rtt`, `rttvar`, `all`

### 3. `visualize_tm_queue.py` - TM 队列数据可视化

```bash
python3 ./visualize_tm_queue.py --tm-log ./tm.tsv --metric all --output tm_metrics.png
```

**支持的指标**：`queue_usage`, `queue_wm`, `drop_rate`, `rate`, `all`, `detailed`

### 4. `tcp_metrics_collector.py` - TCP 高精度指标采集

利用 `ss` 命令以毫秒级精度采集 TCP 连接状态（RTT, CWND, Delivery Rate, Retransmits 等）。

```bash
python3 ./tcp_metrics_collector.py --dst-ip 192.168.6.2 --interval-ms 1 --duration 500 --output tcp_metrics.csv
```

### 5. `visualize_tcp_metrics.py` - TCP 指标可视化

针对 `tcp_metrics_collector.py` 生成的 CSV 数据进行优化可视化，支持大规模数据点。

```bash
python3 ./visualize_tcp_metrics.py --input tcp_metrics.csv --output ./plots
```

### 6. 辅助脚本

- `bfrt_explore.sh` - 探索 BFRT API 所有可用接口
   ```bash
   # 探索所有 BFRT 接口
   ./bfrt_explore.sh
   
   # 过滤 TM 相关的表
   ./bfrt_explore.sh --filter tm
   
   # 仅列出所有表
   ./bfrt_explore.sh --list-tables
   
   # 使用自定义 SDE 路径
   ./bfrt_explore.sh --sde /custom/path/bf-sde-9.13.0
   ```

- `check_queues.sh` - 扫描端口，显示端口计数器、限速配置
   ```bash
   # 扫描 Pipe 1 (ports 128-255)
   ./check_queues.sh
   
   # 扫描 Pipe 0 (ports 0-127)
   ./check_queues.sh --pipe 0
   
   # 查询特定端口
   ./check_queues.sh --dev-port 189
   ```

---

## ❓ 常见问题

1. **`could not initialize bf_rt ... err: 1`**
   - 确保已运行 `./contrl_test`

2. **重启程序后限速失效**
   - 重新运行 `apply` 命令
