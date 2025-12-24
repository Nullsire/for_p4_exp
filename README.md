# Tofino Traffic Manager 实验：限速与监控

本项目包含一组用于在 Tofino 交换机上进行流量管理（Traffic Manager, TM）实验的脚本。主要功能包括：在 egress 端口或队列上施加限速（Shaping），并实时观测队列堆积、水位（Watermark）以及丢包（Drops）情况。

---

## 🚀 快速上手

### 1. 实验拓扑

```
[Sender Host] ---> Tofino Switch(dev_port 189) ---> [Receiver Host]
  192.168.5.2                                                                      192.168.6.2
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
./scripts/tm_shape_queue.sh apply --dev-port 189 --max-mbps 120
```

### 4. 生成实验脚本

```bash
python3 ./scripts/gen_experiment.py --config I --out-dir ./scripts/
```

生成的脚本：
- `run_sender_confI.sh` - 发送端脚本
- `run_receiver_confI.sh` - 接收端脚本（含 JSON 日志记录）
- `run_ss_sampler_confI.sh` - TCP 细粒度采样脚本

### 5. 运行实验

1. **Receiver 端**：运行 `run_receiver_confI.sh`
2. **Sender 端**：运行 `run_sender_confI.sh`
3. **交换机**：实时监控队列
   ```bash
   ./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues
   ```

### 6. 数据处理与可视化

```bash
# 合并 sender 和 receiver 的日志（获取准确的 goodput 和 RTT）
python3 ./scripts/merge_iperf3_logs.py \
    --sender-dir ./exp_logs_I \
    --receiver-dir ./exp_logs_I_receiver \
    --output-dir ./merged_logs_I

# 可视化
python3 ./scripts/visualize_iperf3.py --iperf-dir ./merged_logs_I --output goodput.png
```

### 7. 实验清理

```bash
./scripts/tm_shape_queue.sh reset
```

---

## 📊 指标测量说明

### ⚠️ 重要：Goodput 与 RTT 的准确测量

**iperf3 Sender 和 Receiver 报告的指标准确性不同**：

| 指标 | 准确来源 | 原因 |
|------|----------|------|
| **goodput** (bits_per_second) | **Receiver** | Sender 报告的是 TCP 发送缓冲区写入速率，不是实际交付速率 |
| **rtt** / **rttvar** | **Sender** | 只有 Sender 能通过 ACK 延迟测量 RTT |
| **retransmits** | **Sender** | 只有 Sender 知道重传次数 |
| **cwnd** | **Sender** | 发送端的拥塞窗口 |

**解决方案**：使用 `merge_iperf3_logs.py` 合并两端日志，自动选取每个指标的准确来源。

---

## 🛠️ 脚本说明

### 1. `tm_shape_queue.sh` - 核心限速与监控工具

```bash
# 限速
./scripts/tm_shape_queue.sh apply --dev-port 189 --max-mbps 120

# 限制队列 Buffer
./scripts/tm_shape_queue.sh buffer --dev-port 189 --all-queues --max-cells 100

# 实时监控
./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues --log-file ./tm.tsv

# 重置所有端口
./scripts/tm_shape_queue.sh reset
```

### 2. `gen_experiment.py` - 实验脚本生成器

```bash
python3 ./scripts/gen_experiment.py --config I --out-dir ./scripts/ --log-dir ./exp_logs
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

### 3. `merge_iperf3_logs.py` - 日志合并工具

合并 sender 和 receiver 的 iperf3 日志，提取各自准确的指标：

```bash
python3 ./scripts/merge_iperf3_logs.py \
    --sender-dir ./exp_logs_I \
    --receiver-dir ./exp_logs_I_receiver \
    --output-dir ./merged_logs_I
```

**合并逻辑**：
- 从 Sender 取：rtt, rttvar, snd_cwnd, retransmits
- 从 Receiver 取：bits_per_second, bytes

### 4. `visualize_iperf3.py` - iperf3 数据可视化

```bash
# 可视化 goodput
python3 ./scripts/visualize_iperf3.py --iperf-dir ./merged_logs_I --metric goodput --output goodput.png

# 可视化 RTT
python3 ./scripts/visualize_iperf3.py --iperf-dir ./merged_logs_I --metric rtt --output rtt.png

# 可视化所有指标
python3 ./scripts/visualize_iperf3.py --iperf-dir ./merged_logs_I --metric all --output all.png
```

**支持的指标**：`goodput`, `bytes`, `retransmits`, `cwnd`, `rtt`, `rttvar`, `all`

### 5. `visualize_tm_queue.py` - TM 队列数据可视化

```bash
python3 ./scripts/visualize_tm_queue.py --tm-log ./tm.tsv --metric all --output tm_metrics.png
```

**支持的指标**：`queue_usage`, `queue_wm`, `drop_rate`, `rate`, `all`, `detailed`

### 6. `visualize_ss.py` - ss 采样数据可视化

```bash
python3 ./scripts/visualize_ss.py --ss-log ./exp_logs_I/ss_stats.csv --metric cwnd --output cwnd.png
```

### 7. 辅助脚本

- `check_queues.sh` - 扫描所有端口，显示有拥塞/丢包的端口
- `scan_valid_pg_ids.py` - 诊断 dev_port 到 pg_id 的映射

---

## ❓ 常见问题

1. **`could not initialize bf_rt ... err: 1`**
   - 确保已运行 `./contrl_test` 或 `run_switchd.sh`

2. **重启程序后限速失效**
   - 重新运行 `apply` 命令

3. **Goodput 超过设定的带宽限制**
   - 你可能使用了 sender 端的日志，请使用 `merge_iperf3_logs.py` 合并日志后再可视化

4. **图表中没有 RTT 数据**
   - RTT 只有 sender 端才有，确保使用了 sender 的日志或合并后的日志