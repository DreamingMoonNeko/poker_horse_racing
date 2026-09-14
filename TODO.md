# TODO

> 最后更新：随「阶段一 + 图形化 + 联机 + ACK 锁」实现同步刷新

## 进度总览

| # | 任务 | 状态 | 落地位置 |
| --- | --- | --- | --- |
| 1 | 玩家输入（阶段一：一个客户端 4 名玩家） | ✅ 已完成 | `controllers/`、`turn.py` |
| 1b | 玩家输入（阶段二：一台设备一名玩家） | ✅ 已实现 | `net/controller.py`、`net/client.py` |
| 2 | 图形化 | ✅ 已完成 | `ui/`（pygame 单窗口四面板热座）、`viewmodel.py` |
| 3 | 通过局域网联机 | ✅ 已完成 | `net/server.py`、`net/client.py`、`net/link.py` |
| 4 | 数据同步使用 ACK 锁 | ✅ 已完成 | `net/acklock.py` |

## 1. 玩家输入

### 阶段一（单客户端 4 人，本地热座）✅

- [x] 抽出玩家输入接口 `PlayerController`：`choose_action` / `wants_chain` / `choose_chain` / `choose_discard`
- [x] `HumanController`：把「该你操作了」暴露成 `pending` 状态，由界面推入决策
- [x] `AIController`：可托管任意座位，用于单人试玩与自动对局
- [x] 四人共用一个窗口，点牌选择 → `Enter` 出牌 / `E` 结束回合；`--ai N` 可让 N 家托管
- [x] 任一玩家 `pending` 都会暂停驱动器（`TurnRunner`），保证多人输入不互相插队

### 阶段二（一台设备一名玩家，联机）✅

- [x] 客户端只操作一名玩家：自己的花色固定在下方，其余三家手牌只显示牌背
- [x] 决策打包成 `Intent`（出牌 / 结束回合 / 连锁 / 放弃连锁 / 弃牌）发回主机
- [x] 主机用 `NetworkController` 接收 `Intent`，与 `HumanController` 共用同一套 `GameMaster` 流程

## 2. 图形化 ✅

- [x] pygame 单窗口、四个玩家面板（当前行动玩家自动占据下方主面板）
- [x] 牌面绘制：花色/点数/红黑配色、牌背纹理、选中抬升、提示高亮
- [x] 中央出牌区 + 连锁栈结算预览 + 滚动对局日志 + 状态栏
- [x] 规则速查浮层（`H`）、暂停（`P`）、重开（`R`）、窗口缩放自适应
- [x] 中文字体自动探测（msyh / simhei / Noto CJK…）；无图形环境可跑 `--selftest`

## 3. 通过局域网联机 ✅

- [x] 主机 = 唯一权威：跑 `GameMaster`，按 12 FPS 广播状态快照
- [x] 客户端只渲染 + 收集输入，不跑游戏逻辑（不做本地预测，避免状态分歧）
- [x] `HELLO / WELCOME` 入座握手：可指定花色、房间满员拒绝、掉线自动转 AI 托管
- [x] 协议与传输解耦（`net/frames.py` 只做 JSON 编解码）；UDP 已实现，换 TCP 只需替换 `net/link.py`

启动方式：

```bash
# 主机（房主）
python net/server.py --port 45678 --ai 2 --target 30

# 客户端（每台设备一名玩家）
python net/client.py --host 192.168.1.10 --port 45678 --name 小明
```

## 4. 数据同步使用 ACK 锁 ✅

- [x] `net/acklock.py`：发送序号分配、待确认队列、累计确认、超时重传、重复包去重
- [x] 需要可靠的消息（`SNAPSHOT` / `INTENT`）都带序号并要求对端 ACK
- [x] 重传上限与丢弃统计（`dropped`），避免无限重传
- [x] 每个客户端一条独立序号空间（多端互不干扰），快照 `ack` 字段回传确认进度
- [x] 测试覆盖：序号分配 / 累计确认 / 超时重传 / 重复去重 / 放弃重传 / 四客户端端到端对局

## 后续可做

- [ ] 手动弃牌（见下节，已排期）
- [ ] 联机断线重连（现在掉线直接交 AI 托管）
- [ ] 客户端本地预测 + 回滚（降低操作延迟感）
- [ ] 观战模式（`viewer=None` 的上帝视角快照已具备，缺一个入口）
- [ ] 大小王 / 效果库扩展（`effects.py` 已留出 `Effect` 基类）

---

## 手动弃牌（待实现，暂不改动代码）

规则依据：RULES §4.5 弃牌、§7.2 手牌上限、§7.3 非法操作。
**当前行为**：`END_PHASE` 手牌超过 13 张时，`HumanController.choose_discard()`
按「非阵营花色 + 点数最小」自动挑牌直接弃掉，玩家没有选择权。

**目标行为**：该弃牌必须由玩家自己选，界面弹出选牌提示，选够张数才能确认。

### 涉及文件

| 文件 | 改动点 |
| --- | --- |
| `GameMaster.py` | `request_discard()` 需要支持「挂起等待」，而不是同步取结果 |
| `controllers/human.py` | 新增 `discard_queue` / `pending` 阶段 `choose_discard` 的等待逻辑（字段已预留） |
| `net/controller.py` | 已支持 `discard` 意图，需接上「等待 + 拒绝数量不符」两条路径 |
| `turn.py` | `TurnRunner.step()` 需要在一个「弃牌待输入」状态上暂停，而不是一条路走到底 |
| `viewmodel.py` | `TableInteraction` 增加 `choose_discard` 阶段 + `discard_uids` 选择集合 |
| `ui/render.py` / `ui/app.py` | 弃牌浮层：提示「请选择 N 张」，复用现有选牌高亮与确认/取消按钮 |
| `net/server.py` | 把 `pending_stage='choose_discard'` 与目标张数写进快照 |
| `effects.py` | `DiscardEffect` 触发时机不变，只改「怎么拿到牌」 |

### 实现要点

1. **不要阻塞 GameMaster**：现在的流程是 `resolve_chain()` → `DiscardEffect.apply()` → 同步问控制器要牌。
   改成「效果挂起 + 请求入队」：`request_discard` 生成一个 `PendingDiscard(player, number)`,
   放进 `gm.pending_discards`，由 `TurnRunner.step()` 在每帧检查——没有待处理就继续，
   有就把该玩家标记为等待输入并暂停。
2. **顺序要求**：四条让「其他玩家各弃 1 张」时可能同时产生多条待弃请求，
   必须按玩家顺序逐条结算，前一条没确认不能推进下一条。
3. **合法性校验**：张数必须恰好等于要求张数，且都在自己手牌里；
   不满足就拒绝并提示（RULES §7.3），不消耗资源、不改变状态。
4. **超时兜底**：掉线或长时间不响应的玩家，仍要按原启发式自动弃牌，
   否则对局会卡死（联机时沿用 `NetworkController` 的默认策略即可）。
5. **联机路径**：复用已有的 `intent_discard(uids)`；主机端 `NetworkController.apply_intent`
   里 `kind == 'discard'` 的分支已经把牌放进 `discard_queue`，接上等待状态即可。
6. **回归测试**：`tests/test_game.py` 里 `test_end_phase_discards_to_hand_limit`
   需要改写成「提交弃牌 → 检查手牌数」，并补一条「张数不对被拒绝」的用例。
