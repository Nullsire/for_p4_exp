# Tofino Traffic Manager Experiment: Shaping & Monitoring

本项目包含一组用于在 Tofino 交换机上进行流量管理（Traffic Manager, TM）实验的脚本。主要功能包括：在 egress 端口或队列上施加限速（Shaping），并实时观测队列堆积、水位（Watermark）以及丢包（Drops）情况。

目标是复现并观测 **“限速/拥塞 → 队列累积/丢包 → RTT/吞吐变化”** 这一完整链路。

---

## 🚀 快速上手 (实验复现指南)

### 1. 实验拓扑与配置

假设交换机连接两台主机：
- **Port 3 (Client)**: `192.168.1.2/24` (Gateway: `192.168.1.1`)
- **Port 4 (Server)**: `192.168.2.2/24` (Gateway: `192.168.2.1`)

**主机路由配置**:
```bash
# Client Host
sudo ip route replace default via 192.168.1.1 dev eth0

# Server Host
sudo ip route replace default via 192.168.2.1 dev eth0
```

### 2. 启动交换机程序

在交换机上编译并运行 P4 程序：
```bash
cd /home/qfr23/zgy/P4_Exp/p4
make
./contrl_test
```
> **注意**: 如果遇到 bind error，请先执行 `pkill -f contrl_test` 清理进程。后续脚本均依赖此程序（或 `bf_switchd`）提供的 BFRT 服务。

### 3. 设置端口限速 (Shaping)

新开一个交换机终端，对 Port 4 (假设 dev_port 为 **189**) 设置 100Mbps 限速：

```bash
# 推荐：使用端口级限速
./scripts/tm_shape_queue.sh apply --dev-port 189 --scope port --max-mbps 120
```

### 4. 开始实时观测

在交换机终端启动监控，每 1 秒刷新一次，观测所有队列状态：

```bash
./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues --clear-counters
```

**重点关注指标**:
- `usage_cells` / `watermark_cells`: 队列当前占用与历史峰值（是否堆积？）
- `d_egress_drop`: 端口总丢包增量（是否正在丢包？）

### 5. 产生流量与观测 RTT

**服务端 (Port 4 Host)**:
```bash
iperf3 -s
```

**客户端 (Port 3 Host)**:
启动 8 并发流量以制造拥塞：
```bash
iperf3 -c 192.168.2.2 -P 8 -t 120
```

同时在客户端观测 RTT 变化：
```bash
watch -n 0.5 "ss -ti dst 192.168.2.2 | grep -E '(rtt:|cwnd:|estab)'"
```

### 6. 实验结束清理

```bash
# [推荐] 重置所有端口的限速配置（避免遗忘）
./scripts/tm_shape_queue.sh reset

# 或仅重置指定端口
# ./scripts/tm_shape_queue.sh reset --dev-port 189 --scope port

# 停止程序
pkill -f contrl_test
```

---

## 🛠️ 脚本使用手册 (Scripts)

脚本目录：`./scripts/`。所有脚本均会自动加载 SDE 环境（默认 `/root/bf-sde-9.13.0`），如需指定 SDE 路径，可使用 `--sde` 参数。

### 1. `tm_shape_queue.sh` (核心工具)

该脚本是实验的核心，集成了限速配置 (apply)、重置 (reset) 和监控 (watch) 功能。

#### 基本语法
```bash
./scripts/tm_shape_queue.sh <COMMAND> [OPTIONS]
```
**COMMAND**:
- `apply`: 应用限速配置（Shaping）。
- `buffer`: 配置队列 Buffer 大小限制。
- `reset`: 清除限速配置。
- `watch`: 实时监控端口/队列计数器。

#### 通用参数
- `--dev-port <N>`: 目标设备端口号（如 189）。`apply`/`watch` 必填，`reset` 可选（不指定则重置所有端口）。
- `--queue <N>`: 指定逻辑队列号 (0-7)，默认为 0。
- `--scope <port|queue>`: 限速生效范围。
  - `port`: 限制整个物理端口的总速率（推荐，更直观）。
  - `queue`: 仅限制指定队列的速率。
- `--sde <PATH>`: 指定 SDE 安装路径（默认 `/root/bf-sde-9.13.0`）。

#### 子命令详解

**(A) Apply - 应用限速**
必须指定速率上限，支持三种单位（三选一）：
- `--max-mbps <N>`: 设置速率上限为 N Mbps。
- `--max-gbps <N>`: 设置速率上限为 N Gbps。
- `--max-bps <N>`: 设置速率上限为 N bps。

**示例**:
```bash
# [推荐] 对端口 189 整体限速 100Mbps
./scripts/tm_shape_queue.sh apply --dev-port 189 --scope port --max-mbps 100

# 对端口 189 的队列 0 单独限速 50Mbps
./scripts/tm_shape_queue.sh apply --dev-port 189 --scope queue --queue 0 --max-mbps 50
```

**(B) Buffer - 配置队列缓冲区大小**

限制指定队列（或所有队列）的最大 Buffer 大小。通过减小 Buffer，可以更容易触发队列丢包（Tail Drop），便于实验观测。

**背景说明**:
- Tofino1 的 Buffer 以 Cell 为单位，每个 Cell 约 80 字节。
- 默认情况下，队列 Buffer 非常大（几 MB），TCP 拥塞控制会自动适应限速，稳态时几乎不会丢包。
- 通过限制 Buffer 大小，可以让队列更容易溢出，从而观测到真实的队列丢包。

**参数**:
- `--max-cells <N>`: 设置 Buffer 上限为 N 个 Cells（与 `--max-kb` 二选一）。
- `--max-kb <N>`: 设置 Buffer 上限为 N KB（自动换算为 Cells）。
- `--queue <N>`: 指定队列号 (0-7)，默认为 0。
- `--all-queues`: **(推荐)** 同时配置该端口的所有 8 个队列 (0-7)。

**示例**:
```bash
# 限制端口 189 队列 0 的 Buffer 为 100 cells（约 8KB）
./scripts/tm_shape_queue.sh buffer --dev-port 189 --queue 0 --max-cells 100

# 限制端口 189 队列 0 的 Buffer 为 16KB
./scripts/tm_shape_queue.sh buffer --dev-port 189 --queue 0 --max-kb 16

# [推荐] 限制端口 189 所有队列的 Buffer 为 100 cells
./scripts/tm_shape_queue.sh buffer --dev-port 189 --all-queues --max-cells 100

# 结合限速使用：先限速再限 Buffer，更容易观测丢包
./scripts/tm_shape_queue.sh apply --dev-port 189 --max-mbps 10
./scripts/tm_shape_queue.sh buffer --dev-port 189 --all-queues --max-cells 50
```

**实验建议**:
| Buffer 大小 | 效果 |
|-------------|------|
| 50 cells (~4KB) | 非常容易丢包，适合观测 Tail Drop |
| 100 cells (~8KB) | 中等，可观测到周期性丢包 |
| 500 cells (~40KB) | 较大，主要观测队列堆积 |

**(C) Watch - 实时监控**
用于观测 TM 内部计数器（丢包、占用、水位）。
- `--interval <SEC>`: 刷新间隔，单位秒（默认 1.0）。
- `--all-queues`: **(推荐)** 同时监控该端口下的所有 8 个队列 (0-7)。
- `--clear-counters`: 启动监控前先清零计数器（便于观测本次实验产生的增量）。
- `--duration <SEC>`: 运行指定时长后自动退出。
- `--iterations <N>`: 运行指定次数后自动退出。

**示例**:
```bash
# 每秒刷新一次，监控所有队列，开始前清零
./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues --clear-counters

# 监控并保存日志到文件
./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues --log-file ./logs/experiment.tsv

# 追加模式写入日志（多次实验）
./scripts/tm_shape_queue.sh watch --dev-port 189 --duration 60 --log-file ./logs/combined.tsv --log-append
```

**(D) 日志功能**
输出可以同时写入终端和日志文件，便于实验数据记录和后续分析。

- `--log-file <PATH>`: 指定日志文件路径，输出将同时写入 stdout 和该文件。
- `--log-append`: 追加模式，不覆盖已有文件内容（适用于多次实验合并记录）。

日志文件格式为 TSV (Tab-Separated Values)，包含：
- 文件头部注释：开始/结束时间戳、命令参数
- 数据列标题行
- 每行一条监控记录

**日志文件示例**:
```
# Log started at 2025-12-22 11:00:00
# Log file: ./logs/experiment.tsv
# Command: mode=watch, dev_port=189, queue=0, scope=port
time	dev_port	queue	egress_drop	d_egress_drop	...
1734868800.123	189	0	1000	50	...
1734868801.125	189	0	1050	50	...
# Log ended at 2025-12-22 11:01:00
```

**(E) Reset - 清除限速和 Buffer 配置**
移除端口或队列的限速配置，**同时恢复 Buffer 配置为默认值**，恢复线速转发。

**重置内容**:
- **Shaping（限速）**: 禁用 `max_rate_enable`
- **Buffer（缓冲区）**: 恢复默认值
  - `guaranteed_cells`: 20
  - `pool_max_cells`: 13
  - `hysteresis_cells`: 32
  - `dynamic_baf`: "80%"

**⚠️ 重要**: 为避免因遗忘导致端口速度/Buffer 被长期修改，**强烈建议在实验结束后使用不带 `--dev-port` 参数的 reset 命令，一次性重置所有端口的配置**。

**参数**:
- `--dev-port <N>`: **(可选)** 如不指定，将重置所有端口 (Pipe 0: 0-127, Pipe 1: 128-255)
- `--scope <port|queue>`: 重置范围，默认为 `port`

**示例**:
```bash
# [推荐] 重置所有端口的限速和 Buffer 配置（避免遗忘）
./scripts/tm_shape_queue.sh reset

# 重置所有端口的队列级限速和 Buffer
./scripts/tm_shape_queue.sh reset --scope queue

# 仅重置指定端口的限速和 Buffer
./scripts/tm_shape_queue.sh reset --dev-port 189 --scope port
```

---

### 2. `check_queues.sh` (全网扫描)

无需参数。自动扫描 Pipe 1 (Port 128-255) 下所有端口，仅输出存在异常（有丢包、有占用或有水位）的端口。

**用途**: 当你不知道流量堵在哪里时，用此脚本快速定位拥塞端口。

```bash
./scripts/check_queues.sh
```

**输出示例**:
```text
Dev_Port  Drop_Pkts  Usage_Cells  Watermark_Cells
189       5020       1200         4500
```

---

### 3. `read_qdelay.py` (寄存器读取)

直接读取 `SwitchEgress.qdelay_reg` 寄存器的工具。此工具需要使用 `bfrt_python` 调用。

**语法**:
```bash
bfrt_python ./scripts/read_qdelay.py <INDEX> [--pipe <PIPE_ID>] [--from-hw]
```

- `<INDEX>`: **(必填)** 寄存器索引。
- `--pipe <PIPE_ID>`: 指定 Pipe ID（默认根据 index 自动推导）。
- `--from-hw`: 强制从硬件读取（脚本默认已开启）。

**示例**:
```bash
bfrt_python ./scripts/read_qdelay.py 0
```

---

### 4. `scan_valid_pg_ids.py` (诊断工具)

无需参数。扫描 Pipe 1 上所有可能的 `pg_id` (Port Group ID)，检查哪些 ID 是有效的（即能够被读取）。

**用途**: 用于开发阶段排查 `dev_port` 到 `pg_id` 的映射关系是否符合预期。

```bash
./scripts/scan_valid_pg_ids.py
```

---

### 5. `gen_experiment.py` (实验脚本生成器)

根据 iRED 论文中的实验配置 (Table 2 & Table 3)，自动生成 Sender 和 Receiver 端的 Shell 脚本。

#### 基本语法
```bash
python3 ./scripts/gen_experiment.py --config <CONFIG_ID> [OPTIONS]
```

#### 参数说明
- `--config <I-XII>`: **(必填)** 配置 ID，对应论文 Table 2 中的 12 种配置组合。
- `--sender-if <IFACE>`: Sender 端网络接口名（默认 `eth0`）。
- `--receiver-if <IFACE>`: Receiver 端网络接口名（默认 `eth0`）。
- `--receiver-ip <IP>`: Receiver 端 IP 地址（默认 `192.168.2.2`）。
- `--out-dir <DIR>`: 输出目录（默认当前目录）。

#### 实验配置 (Table 2)

| Config | Bandwidth (Mbps) | RTT (ms) | MTU (Bytes) |
|--------|------------------|----------|-------------|
| I      | 120              | 10       | 1500        |
| II     | 120              | 50       | 1500        |
| III    | 1000             | 10       | 1500        |
| IV     | 1000             | 50       | 1500        |
| V      | 120              | 10       | 800         |
| VI     | 120              | 50       | 800         |
| VII    | 1000             | 10       | 800         |
| VIII   | 1000             | 50       | 800         |
| IX     | 120              | 10       | 400         |
| X      | 120              | 50       | 400         |
| XI     | 1000             | 10       | 400         |
| XII    | 1000             | 50       | 400         |

#### 负载阶段 (Table 3)

实验分为 4 个阶段，每阶段 120 秒，逐步增加并发流数量：

| Phase | 时间点 (s) | Cubic Flows | Prague Flows |
|-------|-----------|-------------|--------------|
| 1     | 0         | 1           | 1            |
| 2     | 120       | 2           | 2            |
| 3     | 240       | 10          | 10           |
| 4     | 360       | 25          | 25           |

#### 生成脚本说明

**Sender 脚本** (`run_sender_conf<ID>.sh`):
- 设置 MTU (使用 `ifconfig`)
- 分 4 阶段启动 iperf3 流量（Cubic + Prague 拥塞控制算法）

**Receiver 脚本** (`run_receiver_conf<ID>.sh`):
- 设置 MTU (使用 `ifconfig`)
- 设置 RTT 延迟 (使用 `tc netem` 延迟 ACK)
- 启动 iperf3 服务器

#### iperf3 日志记录 (默认启用)

**日志功能默认启用**，生成的脚本会自动记录 iperf3 的 JSON 日志，避免因忘记配置而丢失实验数据。

- `--log-dir <DIR>`: 指定 iperf3 JSON 日志输出目录（默认: `./exp_logs`）
  - 每个流生成独立日志文件（如 `cubic_flow_1.json`, `prague_flow_1.json`）
  - 使用 iperf3 的 `-J` 标志输出详细 JSON 格式
  - 包含每秒吞吐量、重传等详细数据
- `--no-log`: 禁用日志记录（**不推荐**，可能导致实验数据丢失）

#### 使用示例

```bash
# 生成配置 I 的实验脚本（日志默认保存到 ./exp_logs/）
python3 ./scripts/gen_experiment.py --config I --out-dir ./exp_scripts/

# 自定义日志目录
python3 ./scripts/gen_experiment.py --config IV --out-dir ./exp_scripts/ --log-dir /data/experiment_logs/

# 禁用日志（不推荐）
python3 ./scripts/gen_experiment.py --config I --out-dir ./exp_scripts/ --no-log
```

#### 完整实验流程

1. **生成脚本**:
   ```bash
   python3 ./scripts/gen_experiment.py --config I --out-dir ./exp_scripts/
   ```

2. **配置交换机带宽限制**:
   ```bash
   ./scripts/tm_shape_queue.sh apply --dev-port 189 --scope port --max-mbps 120
   ```

3. **在 Receiver 端运行**:
   ```bash
   scp ./exp_scripts/run_receiver_confI.sh receiver:/tmp/
   ssh receiver "chmod +x /tmp/run_receiver_confI.sh && /tmp/run_receiver_confI.sh"
   ```

4. **在 Sender 端运行**:
   ```bash
   scp ./exp_scripts/run_sender_confI.sh sender:/tmp/
   ssh sender "chmod +x /tmp/run_sender_confI.sh && /tmp/run_sender_confI.sh"
   ```

5. **监控队列状态** (交换机):
   ```bash
   ./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 --all-queues --clear-counters
   ```

> **注意**: Prague 拥塞控制算法需要在主机上预先安装支持。如果系统不支持 Prague，可以修改生成的脚本将 `-C prague` 替换为其他算法（如 `bbr`）。

---

### 6. `visualize_iperf3.py` (iperf3 数据可视化)

可视化 iperf3 JSON 日志文件，支持多种指标的绘图。

#### 环境准备

首次使用需要安装 Python 依赖：
```bash
# 使用虚拟环境（推荐）
cd /home/qfr23/zgy/P4_Exp/p4
source venv/bin/activate

# 或手动安装依赖
pip install matplotlib numpy
```

#### 基本语法
```bash
python3 ./scripts/visualize_iperf3.py --iperf-dir <DIR> [OPTIONS]
```

#### 参数说明
- `--iperf-dir <DIR>`: **(必填)** iperf3 JSON 日志目录路径
- `--output <FILE>`: 输出图片文件名（默认 `iperf3_plot.png`）
- `--metric <TYPE>`: 要绘制的指标类型
  - `goodput`: 吞吐量 (Mbps)，聚合显示（默认）
  - `bytes`: 传输字节数 (MB)，聚合显示
  - `retransmits`: 重传次数，聚合显示
  - `cwnd`: 拥塞窗口 (KB)，平均值显示
  - `rtt`: 往返时延 (ms)，平均值显示
  - `rttvar`: RTT 方差 (ms)，平均值显示
  - `all`: 生成包含主要指标的组合图表
- `--title <TITLE>`: 自定义图表标题
- `--max-time <SEC>`: 最大绘图时间（默认 480 秒）
- `--show-individual`: 对于每流指标，显示单独的流曲线

#### 支持的日志格式
- 由 `gen_experiment.py --log-dir` 生成的 iperf3 JSON 日志
- 文件格式：`cubic_flow_N.json`, `prague_flow_N.json`

#### 使用示例

```bash
# 激活虚拟环境
source venv/bin/activate

# 可视化吞吐量（默认）
python3 ./scripts/visualize_iperf3.py --iperf-dir ./exp_logs --output goodput.png

# 可视化 RTT
python3 ./scripts/visualize_iperf3.py --iperf-dir ./exp_logs --metric rtt --output rtt.png

# 可视化拥塞窗口
python3 ./scripts/visualize_iperf3.py --iperf-dir ./exp_logs --metric cwnd --output cwnd.png

# 可视化重传次数
python3 ./scripts/visualize_iperf3.py --iperf-dir ./exp_logs --metric retransmits --output retransmits.png

# 生成所有主要指标的组合图
python3 ./scripts/visualize_iperf3.py --iperf-dir ./exp_logs --metric all --output all_metrics.png
```

---

### 7. `visualize_tm_queue.py` (TM 队列数据可视化)

可视化 tm_shape_queue TSV 日志文件，支持多种队列指标的绘图。

#### 基本语法
```bash
python3 ./scripts/visualize_tm_queue.py --tm-log <FILE> [OPTIONS]
```

#### 参数说明
- `--tm-log <FILE>`: **(必填)** tm_shape_queue TSV 日志文件路径
- `--output <FILE>`: 输出图片文件名（默认 `tm_queue_plot.png`）
- `--metric <TYPE>`: 要绘制的指标类型
  - `queue_usage`: 队列占用 (cells)（默认）
  - `queue_wm`: 队列水位 (cells)
  - `drop_rate`: 丢包率 (packets/interval)
  - `drop_count`: 累计丢包数 (packets)
  - `egress_usage`: Egress 端口占用 (cells)
  - `egress_wm`: Egress 端口水位 (cells)
  - `egress_drop_rate`: Egress 端口丢包率
  - `rate`: 端口 RX/TX 速率 (Mbps)
  - `all`: 生成主要指标的组合图表
  - `detailed`: 生成包含所有可用指标的详细图表
- `--title <TITLE>`: 自定义图表标题
- `--max-time <SEC>`: 最大绘图时间

#### 支持的日志格式
- 由 `tm_shape_queue.sh watch --log-file` 生成的 TSV 日志
- 支持单队列模式和多队列模式 (`--all-queues`)

#### 使用示例

```bash
# 激活虚拟环境
source venv/bin/activate

# 可视化队列占用（默认）
python3 ./scripts/visualize_tm_queue.py --tm-log ./logs/tm_watch.tsv --output queue_usage.png

# 可视化丢包率
python3 ./scripts/visualize_tm_queue.py --tm-log ./logs/tm_watch.tsv --metric drop_rate --output drops.png

# 可视化 RX/TX 速率
python3 ./scripts/visualize_tm_queue.py --tm-log ./logs/tm_watch.tsv --metric rate --output rate.png

# 生成主要指标的组合图
python3 ./scripts/visualize_tm_queue.py --tm-log ./logs/tm_watch.tsv --metric all --output all_metrics.png

# 生成详细的多面板图表
python3 ./scripts/visualize_tm_queue.py --tm-log ./logs/tm_watch.tsv --metric detailed --output detailed.png
```

#### 完整数据收集与可视化流程

```bash
# 1. 生成实验脚本（启用日志）
python3 ./scripts/gen_experiment.py --config I \
    --out-dir ./exp_scripts/ \
    --log-dir ./exp_logs/

# 2. 启动交换机监控并记录日志
./scripts/tm_shape_queue.sh watch --dev-port 189 --interval 1 \
    --all-queues --log-file ./logs/tm_watch.tsv &

# 3. 运行实验（Sender/Receiver 端）
# ... 执行实验脚本 ...

# 4. 实验结束后生成可视化图表
source venv/bin/activate

# iperf3 吞吐量图
python3 ./scripts/visualize_iperf3.py \
    --iperf-dir ./exp_logs/ \
    --output ./results/goodput.png

# TM 队列指标图
python3 ./scripts/visualize_tm_queue.py \
    --tm-log ./logs/tm_watch.tsv \
    --metric detailed \
    --output ./results/queue_metrics.png
```

---

## 📖 关键术语与原理

### Traffic Manager (TM)
Tofino 芯片中负责报文缓存、队列管理和调度的核心模块。报文处理流程：`Ingress Pipeline` -> `TM` -> `Egress Pipeline`。

### 观测指标解释

1.  **Queue (队列)**
    *   TM 为每个 Egress Port 维护多个队列（逻辑号 0-7）。
    *   脚本会自动处理逻辑队列号到硬件 Queue ID 的映射 (`egress_qid_queues`)。

2.  **Usage Cells (当前占用)**
    *   当前时刻该端口/队列占用的 Buffer 单元数 (Cell)。
    *   **现象**: 当 egress 速率 < ingress 速率时，Usage 上升。

3.  **Watermark Cells (水位)**
    *   历史峰值占用（自上次清零后的最大 Usage）。
    *   **作用**: 即使当前 Usage 已回落，Watermark 也能告诉你刚才发生了多严重的拥塞。

4.  **Drop Packets (丢包)**
    *   TM 侧的丢包计数。
    *   **原因**: Buffer 耗尽 (Tail Drop) 或 WRED 策略触发。

5.  **Shaping (限速)**
    *   **Port Scope**: 限制整个物理端口的发送速率（推荐）。
    *   **Queue Scope**: 限制特定队列的速率（更细粒度）。

---

## ❓ 常见问题 (Troubleshooting)

1.  **报错: `could not initialize bf_rt ... err: 1`**
    *   **原因**: BFRT 服务未运行。
    *   **解决**: 确保已运行 `./contrl_test` 或 SDE 的 `run_switchd.sh`。

2.  **重启程序后限速失效**
    *   `bf_switchd` 重启后，TM 的配置（Shaping/Counters）会被重置。请重新运行 `apply` 命令。

3.  **脚本找不到 SDE**
    *   脚本默认 SDE 路径为 `/root/bf-sde-9.13.0`。如果你的 SDE 在其他位置，请添加参数: `--sde ~/my-sde-path`。
