# POKER_HORSE_RACING 项目 README

基于 Python + pygame 的四人卡牌对战游戏（扑克赛马）。采用 Server-Client 架构与「单一数据源 + 状态与渲染分离」设计，已实现**完整规则、本地热座图形界面、局域网联机、ACK 锁同步**。

## 目录

- [项目简介](#项目简介)
- [快速开始](#快速开始)
- [架构总览](#架构总览)
- [目录结构](#目录结构)
- [核心模块说明](#核心模块说明)
- [联机协议](#联机协议)
- [ACK 锁（数据同步）](#ack-锁数据同步)
- [关键技术要点](#关键技术要点)
- [游戏流程](#游戏流程)
- [测试与自检](#测试与自检)
- [后续扩展方向](#后续扩展方向)
- [关键文件速查表](#关键文件速查表)

## 项目简介

四名玩家各代表一种花色（红桃 / 黑桃 / 方片 / 梅花），通过出牌、组合技与连锁积累分数，率先到达目标分数（默认 30）者获胜。

设计目标（均已落地）：

- **单一数据源**：所有卡牌移动只走 `GameMaster.move_cards()`
- **状态与渲染分离**：服务端只维护 `Card.zone` 与 `Player` 状态，可见性由渲染层根据「有没有牌面」自行决定
- **输入与逻辑解耦**：`GameMaster` 只通过 `PlayerController` 接口取决策，因此本地热座、AI、远程玩家可以混用
- **传输与协议解耦**：`net/frames.py` 只做消息编解码，换 UDP/TCP 不影响上层

## 快速开始

```bash
# 0. 准备环境（项目自带 .venv，Python 3.13）
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 1. 单人试玩：3 家 AI，你操作 1 家
.venv\Scripts\python.exe main.py --ai 3

# 2. 本地热座：一个窗口操作 4 名玩家
.venv\Scripts\python.exe main.py

# 3. 全 AI 自动演示（无窗口）
.venv\Scripts\python.exe main.py --cli --seed 3

# 4. 局域网联机
.venv\Scripts\python.exe net\server.py --port 45678 --ai 2   # 主机
.venv\Scripts\python.exe net\client.py --host 192.168.1.10   # 其他设备
```

图形界面操作：

| 操作 | 说明 |
| --- | --- |
| 鼠标点牌 | 选中 / 取消（选中会向上抬起） |
| `Enter` / 空格 | 出牌 |
| `E` | 结束回合 |
| `A` | 让 AI 代打当前这一步 |
| `Tab` | 提示：列出**所有**可达成 / 可连锁的组合，反复按可在组合间循环切换 |
| `Backspace` | 清空选择 |
| 滚轮 / `PgUp` `PgDn` / `↑` `↓` | 翻阅对局日志（往回看更早的记录） |
| `Home` / `End` | 跳到日志最早 / 最新 |
| `L` | 收起 / 展开日志面板（收起后出牌区变大） |
| `P` / `R` / `H` | 暂停 / 重开 / 规则速查 |
| `Esc` | 关闭浮层，或在连锁窗口放弃连锁 |

> **轮到自己的连锁窗口时会自动列出全部合法连锁**（信息栏第二行显示
> `可连锁 N 种：1/N 组合名 …`），第一组会自动选上、直接按 `Enter` 就能连锁；
> 想换一种就按 `Tab` 循环。自己回合里则是 `可达成 N 种：…`。
>
> 连锁窗口的按钮行与出牌阶段一一对应，**始终是完整四个**：
> `连锁出牌 (Enter)` / `放弃连锁 (Esc)` / `AI 代打 (A)` / `提示·切换 (Tab)`。
> 其中「AI 代打」在连锁窗口里会自动挑一个收益最高的合法连锁，挑不出就代为放弃。

> 本地热座为了便于演示，四家手牌都可见（`viewer=None` 的上帝视角）。
> 想体验「只看得到自己的手牌」，请用联机模式（`net/server.py` + `net/client.py`），
> 客户端拿到的快照里对手手牌只有数量、没有牌面。

## 架构总览

```text
┌──────────────────────────── 主机 / 本地进程 ────────────────────────────┐
│                                                                        │
│  GameMaster（权威状态，单一数据源）                                      │
│    round / phase / players / chain_stack / draw_pile / field            │
│    ├── rules.py      组合技与连锁判定（纯函数）                          │
│    ├── effects.py    Effect / ScoreEffect / InterruptEffect / ChainPlay  │
│    └── zones.py      DrawPile / Field / Hand                            │
│                                                                        │
│  TurnRunner（驱动器）：把 GameMaster 的流程与 PlayerController 的输入连起来 │
│                                                                        │
│  PlayerController（输入抽象）                                            │
│    ├── HumanController     本地热座（阶段一：4 名玩家一个窗口）            │
│    ├── AIController        托管 / 演示                                  │
│    └── NetworkController   远程玩家（阶段二：一台设备一名玩家）            │
│                                                                        │
│  TableView（viewmodel.py）：界面数据模型 + 输入状态机                     │
│    viewer=None → 上帝视角（本地热座）                                     │
│    viewer=某玩家 → 只有他的手牌有牌面，其余只给 uid（渲染成牌背）           │
└───────────────┬────────────────────────────────────────────────────────┘
                │ ui/render.py + ui/layout.py + ui/theme.py + ui/widgets.py
                ▼
        ┌───────────────────┐        ┌────────────────────────────────┐
        │  本地 pygame 窗口  │        │  联机：net/server.py 广播快照    │
        │  四个玩家面板       │        │  net/acklock.py 保证可靠送达     │
        └───────────────────┘        │  net/client.py 渲染 + 收集输入   │
                                     └────────────────────────────────┘
```

## 目录结构

```text
project/
├── main.py                # 入口：图形客户端 / --cli / --selftest
├── GameMaster.py          # 游戏逻辑核心（权威状态）
├── rules.py               # 出牌规则引擎：组合技判定、连锁条件、打断判定（纯函数）
├── effects.py             # 效果与连锁栈：Effect / ScoreEffect / DrawEffect / InterruptEffect / ChainPlay
├── turn.py                # TurnRunner 回合驱动器（非阻塞 step()，供 GUI 每帧调用）
├── Player.py              # 玩家对象（手牌 / 分数 / 回合与连锁状态）
├── Card.py                # 卡牌对象（含 to_dict / from_dict 序列化）
├── zones.py               # 区域容器（DrawPile / Field / Hand）
├── enums.py               # 枚举（Suit / Rank / Zone / Phase / ComboType + 中文名表）
├── viewmodel.py           # 界面数据模型 TableView + 输入状态机 TableInteraction（不依赖 pygame）
├── selftest.py            # 无窗口自检：驱动图形层并模拟点击
├── requirements.txt       # 运行依赖（pygame）
│
├── controllers/           # 玩家输入层（TODO 1）
│   ├── base.py            #   PlayerController 接口 + Action
│   ├── human.py           #   HumanController（本地热座）
│   └── ai.py              #   AIController（托管 / 演示）
│
├── ui/                    # pygame 图形层（TODO 2）
│   ├── app.py             #   GameApp 主循环 + 输入分发
│   ├── render.py          #   TableRenderer：只依赖 TableView
│   ├── layout.py          #   四面板布局、手牌矩形、命中测试
│   ├── theme.py           #   配色 + 中文字体探测 + 缺字检测
│   └── widgets.py         #   卡牌 / 按钮 / 面板绘制（花色为矢量绘制）
│
├── net/                   # 局域网联机（TODO 3 + TODO 4）
│   ├── frames.py          #   消息定义与 JSON 编解码
│   ├── acklock.py         #   ACK 锁：序号 / 确认 / 重传 / 去重
│   ├── link.py            #   UDP 连接（UdpLink / Peer / ClientLink）
│   ├── controller.py      #   NetworkController + Intent 构造
│   ├── server.py          #   主机：GameMaster + 快照广播
│   └── client.py          #   客户端：收快照渲染 + 发 Intent
│
├── tests/
│   ├── test_game.py       # 规则与流程测试
│   ├── test_ui.py         # 图形层测试（布局几何、按钮命中、花色绘制）
│   └── test_net.py        # 协议 / ACK 锁 / 端到端联机测试
```

## 核心模块说明

### enums.py — 枚举定义

| 枚举 | 类型 | 用途 |
| --- | --- | --- |
| `Suit` | StrEnum | 花色：HEART / SPADE / DIAMOND / CLUB |
| `Rank` | IntEnum | 点数：ACE=14, TWO~KING，支持大小比较 |
| `Zone` | Enum | 区域标识：DRAW_PILE / FIELD / HAND |
| `Phase` | IntEnum | 阶段：DRAW=0 / PLAY=1 / END=2，可 `(phase+1)%3` 循环 |
| `ComboType` | Enum | 9 种组合技（同花对子/三条/同花/四季/对子/三条/四条/顺子/长顺） |

另外提供 `SUIT_COLOR`、`SUIT_SYMBOL`、`SUIT_CN`、`RANK_SYMBOL`、`COMBO_CN`、`COMBO_EFFECT_TEXT` 等展示用映射表 —— 渲染层直接用，避免到处硬编码。

### rules.py — 出牌规则引擎（纯函数）

| 函数 | 作用 |
| --- | --- |
| `detect_combo(cards)` | 判定组合技。先点数组合（对子/三条/四条/顺子），再花色组合（同花对子/三条/同花/四季）—— 四条优先于四季，否则一手四条会被误判 |
| `is_straight(cards, size)` | 连续判定，A 可当 1（A23 / A2345）也可当 14 |
| `points_sum(cards)` | 点数之和，A 记 14 |
| `can_chain / can_chain_detailed` | 连锁四条件：花色相同 / 花色相反（红黑）/ 点数之和相同 / 点数之和更大 |
| `is_interrupt(...)` | 打断判定：他人回合打出「当前回合玩家阵营花色」且点数之和更大 |
| `find_plays / find_chains` | 枚举手牌中所有可出 / 可连锁的牌组（供提示与 AI 使用） |

### effects.py — 效果与连锁栈

- `Effect` 基类：`resolve(gm)`，带 `resolved` / `negated` 状态
- `ScoreEffect`（加分）、`DrawEffect`（抽牌）、`DiscardEffect`（弃牌）、`InterruptEffect`（打断）
- `ChainPlay`：一次出牌（含连锁），记录牌组、组合技、效果列表、点数之和
- 压栈顺序即 LIFO 结算顺序：**打断 → 基础加分 → 组合技效果**

### GameMaster.py — 游戏逻辑核心

| 类别 | 方法 | 说明 |
| --- | --- | --- |
| 初始化 | `setup()` | 4 名玩家、洗牌、每人 7 张、随机出手顺序 |
| 流程 | `begin_turn_draw / skip_turn / end_turn / next_turn / next_phase` | 抽 2 张 → 出牌 → 结束阶段清场 |
| 出牌 | `validate_play / play_cards / declare_chain` | 合法性校验集中在 `validate_play` |
| 移动 | `move_cards / _find_zone_of / _get_zone` | 单一数据源 |
| 抽牌 | `draw_cards / _recycle_to_draw_pile` | 牌库耗尽时按 §7.1 洗回 |
| 连锁 | `append_chain / resolve_chain / find_interrupt_target` | LIFO 结算 |
| 弃牌 | `request_discard` | 委托给控制器选择 |
| 胜负 | `check_victory / declare_victory` | 达到目标分数即结束 |
| 快照 | `to_snapshot / is_hand_visible_to` | 可见性判定 |

### turn.py — 回合驱动器

`TurnRunner.step()` 每次只推进一步（抽牌 / 等待输入 / 连锁 / 结算 / 换人），
遇到「需要玩家输入」就返回。图形界面每帧调用一次，因此界面永远不卡。

### viewmodel.py — 界面数据模型

- `TableView`：一帧界面需要的全部数据（玩家、出牌、连锁栈、日志、阶段…），可从 `GameMaster` 或字典构造
- `from_game_master(gm, viewer)`：`viewer=None` 为上帝视角；指定 `viewer` 时只暴露他的手牌牌面
- `best_play / find_all_plays / find_all_chains / find_chain_options`：提示与 AI 建议
  （`find_all_plays` 会按「组合技优先、张数多、含阵营花色」排序，供 Tab 循环选择）
- `TableInteraction`：输入状态机（`idle / choose_action / choose_chain`）+ 选中集合 + 组合技建议清单

## 联机协议

消息都是 JSON，一条消息一帧（UDP 数据报）：

| 类型 | 方向 | 说明 |
| --- | --- | --- |
| `HELLO` | C → S | 请求入座，可指定花色 |
| `WELCOME` | S → C | 入座确认（花色、玩家列表、目标分数） |
| `SNAPSHOT` | S → C | 状态快照，**带序号需要 ACK** |
| `INTENT` | C → S | 玩家决策（play / end_turn / chain / decline_chain / discard），**带序号需要 ACK** |
| `EVENT` | S → C | 提示（入座失败 / 房间已满 / 指令被拒 / 对局结束） |
| `PING`/`PONG` | 双向 | 保活与 RTT |
| `BYE` | 双向 | 主动退出 |

时序：

```text
客户端                                 主机
  │  HELLO ─────────────────────────────►│  校验版本 / 找空位 → 落座
  │  ◄───────────────────────── WELCOME  │
  │  ◄──────── SNAPSHOT(seq=7) ──────────│
  │  ─────── ACK(ack=7) ────────────────►│  释放待确认队列
  │  ─────── INTENT(seq=1) ─────────────►│  交给 NetworkController
  │  ◄────── ACK(ack=1) ─────────────────│  指令被采纳 / 拒绝
  │  ◄──────── SNAPSHOT(seq=8) ──────────│
```

快照里 `pending_stage` 由主机告诉客户端「现在轮到你怎么操作」，客户端据此切换输入状态 ——
客户端不需要自己推断游戏规则，减少两端逻辑不一致的风险。

## ACK 锁（数据同步）

`net/acklock.py` 用应用层机制解决「UDP 会丢包」的问题，而不是换成 TCP：

```text
发送侧 AckLock
  build(msg)      → 分配 seq，登记进 pending 表
  on_sent(seq)    → 记录发送时刻
  due_for_retransmit(now) → 超时（默认 300ms）未确认的帧
  on_retransmit(entry)    → 重发；超过 max_attempts 则放弃并计入 dropped
  ack(seq)        → 收到对端确认，删除 seq 及之前的所有待确认帧（累计确认）

接收侧 AckLock
  is_duplicate(seq) → seq ≤ last_acked 说明重复，丢弃但补发 ACK
  mark_received(seq) → 新消息，交给上层处理
  make_ack_frame()   → 纯 ACK 帧（seq=0，不会被 ACK，避免无限递归）
```

要点：

- **每个方向一条独立序号空间**，主机侧每个客户端一条 `AckLock`，多端互不干扰
- **累计确认**：收到 `ack=N` 表示 `1..N` 全部到达，省掉逐条确认的开销
- **重复包必须补 ACK**：否则对端会一直重传（`ClientLink.receive` 里做这件事）
- **幂等**：重复的 `INTENT` 不会被重复执行，重复的 `SNAPSHOT` 直接丢掉（`seq` 更小的快照也会被丢弃）
- **可观测**：`lock.status()` 输出 `sent / acked / retransmit / dropped / pending`，联机界面状态栏直接显示 `待确认 N`
- **有上限**：`max_attempts` 之后放弃并计数，避免对端彻底失联时无限重传

## 关键技术要点

### 1. 单一数据源（Single Source of Truth）

所有卡牌移动集中在 `GameMaster.move_cards()`：

```python
def move_cards(self, cards, to_zone, to_player=None):
    target = self._get_zone(to_zone, to_player)
    for card in cards:
        src = self._find_zone_of(card)   # 找到源容器
        if src is not None:
            src.remove(card)
        if card not in target.cards:
            target.add(card)
        card.change_zone(to_zone)        # 同步逻辑位置
```

### 2. 逻辑位置 vs 物理容器

| 概念 | 存储位置 | 用途 |
| --- | --- | --- |
| 逻辑位置 | `Card.zone` | 客户端渲染、连锁判定、规则校验 |
| 物理容器 | `Zone.cards` | 服务端遍历、移动、洗牌 |

两者必须由 `move_cards()` 保证同步。

### 3. 状态与渲染分离

`GameMaster` 完全不处理可见性，只提供 `is_hand_visible_to(player, viewer)`；
`TableView.from_game_master` 据此决定「给牌面」还是「只给 uid」。
渲染层看到「有数量没牌面」就画牌背 —— 联机快照因此天然不会泄露对手手牌。

### 4. 委托模式（Player → GameMaster）

`Player` 不自己改数据，只把请求转给 `GameMaster`；`GameMaster` 又把「要什么决策」转给 `PlayerController`。
两个方向的委托让三方（数据 / 规则 / 输入）互不侵入。

### 5. 枚举值设计

| 枚举 | 类型选择 | 原因 |
| --- | --- | --- |
| `Suit` | StrEnum | 花色是字符串标识，便于日志与 JSON 序列化 |
| `Rank` | IntEnum | 需要比较大小（ACE=14 > KING=13） |
| `Phase` | IntEnum | 需要循环推进 `(phase + 1) % len(Phase)` |
| `Zone` / `ComboType` | 普通 Enum | 只需唯一标识 |

### 6. 连锁机制（LIFO）

用列表模拟栈，后进先出结算：

```python
def resolve_chain(self):
    while self.chain_stack and not self.game_over:
        effect = self.chain_stack.pop()
        events.extend(effect.resolve(self) or [])
        self.check_victory()
```

打断的实现：`InterruptEffect.apply()` 从栈顶往下找「其他玩家持有、尚未结算的加分效果」并 `negate()` 它。
因为打断按规则先入栈，所以它一定在后入栈的连锁之前被弹出、并且在那个加分效果之前结算。

### 7. 字体缺字陷阱（花色必须自己画）

很多中文字体（用到的 `msyh.ttc` 就是）**并不包含 ♠♥♦♣（U+2660~U+2663）**。
`font.render('♠')` 不会报错，`font.metrics()` 也返回"有宽度"，但实际画出来的是
一个统一的「豆腐块」——结果就是四种花色看起来一模一样。

因此：

- 牌面上的花色由 `ui/widgets.py → draw_suit()` 用几何图形（圆 / 多边形）绘制，完全不依赖字体
- 界面上的日志、提示、上一手信息统一用 `Card.text_name` / `CardView.text_name`（形如「红桃A」），不用 ♠♥♦♣ 字符
- `ui/theme.py → has_glyph(ch)` 可检测某个字符是否真的缺字（拿私用区码位的渲染结果做指纹对比），
  供需要的地方做兜底
- `tests/test_ui.py` 会断言「四种花色画出来的像素集合互不相同」，防止这类问题回归

### 8. 避免循环导入

```text
Card.py      → enums
rules.py     → enums（纯函数，不依赖任何状态）
zones.py     → （运行时）Card / enums
Player.py    → enums / zones，TYPE_CHECKING 延迟导入 Card
effects.py   → enums
GameMaster   → 顶层协调者，导入以上全部
viewmodel.py → enums / rules / effects（不依赖 pygame，主机与客户端共用）
ui/*.py      → pygame + viewmodel
net/*.py     → 标准库 + viewmodel + controllers
```

### 9. 界面交互的三个坑

- **提示要「可循环」而不是「只给一个」**：`TableInteraction.set_hint_groups()` 保存
  全部可达成组合，`cycle_hint()` 负责 Tab 循环。手工点牌只清掉高亮、保留清单，
  这样玩家还能继续用 Tab 切换候选。连锁窗口一打开就自动列清单
  （`_sync_interaction_state` → `_refresh_chain_hints`），不必先按 Tab。
- **「放弃连锁」必须是本回合的终态**：`Player.declined_chain_this_turn` 记录这个决定。
  否则同一回合里别人每出一张牌都会再弹一次连锁询问，玩家会被反复打扰。
- **`_human_waiting()` 的判定必须区分「等谁」**：只阻塞两种情况 ——
  等连锁选择的玩家，以及等自己出牌的**当前回合**玩家。
  如果连「非当前回合玩家等自己出牌」也一起阻塞，连锁收集阶段会被整个跳过，
  表现为连锁窗口永远不出现（实现时确实踩过这个坑）。

## 游戏流程

```text
setup()
  ├─ 创建 4 名玩家（四种花色），绑定各自的 PlayerController
  ├─ 随机打乱出手顺序 → turn_order
  ├─ 生成 52 张牌 → draw_pile → shuffle
  └─ 按出手顺序每人发 7 张

每个回合（TurnRunner.step 驱动）：
  ├─ DRAW_PHASE ：当前玩家抽 2 张（牌库不足则洗回 FIELD）
  ├─ PLAY_PHASE ：当前玩家出牌（校验 → 移动 → 生成效果）
  │                └─ 开放连锁窗口 → 其他玩家可连锁（每人每回合 1 次）
  │                └─ resolve_chain()：LIFO 结算全部效果
  ├─ END_PHASE  ：FIELD 洗回抽牌库 → 手牌上限 13 → 胜负判定
  └─ next_turn()：回到 0 号玩家则 round += 1
```

## 测试与自检

```bash
# 单元测试（规则 / 流程 / 协议 / ACK 锁 / 端到端联机），61 个用例
.venv\Scripts\python.exe -m unittest discover -s tests

# 图形层无窗口自检：跑 1500 帧并模拟「点牌 → 出牌 → 连锁 → 结束回合」
.venv\Scripts\python.exe main.py --selftest

# 纯文本自走一局，打印完整日志
.venv\Scripts\python.exe main.py --cli --seed 3
```

自检覆盖的关键点：图形层不崩、卡牌总数守恒（52）、出牌 / 连锁 / 加分链路生效、重开不残留状态、
联机快照不泄露对手手牌、ACK 锁确实完成过确认。

## 后续扩展方向

| 优先级 | 方向 | 涉及文件 | 说明 |
| --- | --- | --- | --- |
| 🔴 高 | 手动弃牌 | `GameMaster.request_discard` / `turn.py` | 目前超限时按「最没用的牌优先」自动弃；待改为玩家交互选牌，方案见 [TODO.md](TODO.md#手动弃牌待实现暂不改动代码) |
| 🟡 中 | 断线重连 | `net/server.py` / `net/client.py` | 现在掉线直接转 AI 托管 |
| 🟡 中 | 本地预测 + 回滚 | `net/client.py` | 降低联机操作延迟感 |
| 🟡 中 | 观战模式 | `net/server.py` | `viewer=None` 的上帝视角快照已具备 |
| 🟢 低 | 大小王 / 效果库 | `enums.py` / `effects.py` | `Effect` 基类已留出扩展点 |
| 🟢 低 | 传输换成 TCP | `net/link.py` | 协议层已经与传输解耦 |

## 关键文件速查表

| 我想…… | 看这个文件 | 关键位置 |
| --- | --- | --- |
| 改卡牌属性 / 序列化 | `Card.py` | `to_dict` / `from_dict` / `as_card` |
| 改区域容器 | `zones.py` | `ZoneBase` / `DrawPile.draw_many` |
| 加玩家行为 | `Player.py` | 委托给 GM 的方法 |
| 改游戏流程 | `GameMaster.py` | `begin_turn_draw` / `end_turn` / `_run_end_phase` |
| 改组合技或连锁规则 | `rules.py` | `detect_combo` / `can_chain` / `is_interrupt` |
| 加卡牌效果 | `effects.py` | `Effect` 子类 + `COMBO_EFFECTS` |
| 加新枚举 / 文案 | `enums.py` | 对应类与映射表 |
| 改界面数据 | `viewmodel.py` | `TableView` / `TableInteraction` |
| 改界面外观 | `ui/theme.py` / `ui/render.py` | `TableRenderer` 各 `draw_*` |
| 改玩家输入方式 | `controllers/` | `PlayerController` 子类 |
| 改联机协议 | `net/frames.py` | `Frame` / `MsgType` |
| 改可靠传输策略 | `net/acklock.py` | `AckLock` |
| 把联机换成 TCP | `net/link.py` | `UdpLink` / `ClientLink` |

## 总结

- ✅ 数据结构清晰，职责分明（`Card` / `Zone` / `Player` / `GameMaster`）
- ✅ 单一数据源 + 状态与渲染分离，联机快照天然不泄露对手手牌
- ✅ 完整规则：组合技、连锁（LIFO）、打断、加分、牌库耗尽、手牌上限、胜负判定
- ✅ 本地热座图形界面（pygame），同一套界面复用到联机客户端
- ✅ 局域网联机（主机权威 + 快照广播），入座握手 / 掉线托管 / 房间满员处理齐全
- ✅ ACK 锁保证快照与指令可靠送达（序号 / 累计确认 / 超时重传 / 去重 / 上限）
- ✅ 61 个单元测试 + 无窗口图形自检，关键路径都有回归保护

文档随项目迭代更新，建议配合代码注释一起阅读。
