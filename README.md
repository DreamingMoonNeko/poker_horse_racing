# POKER_HORSE_RACING 项目 README

一个基于 Python 的卡牌对战游戏服务端雏形，采用 Server-Client 架构（当前实现服务端逻辑），核心设计遵循“单一数据源”和“状态与渲染分离”原则。

## 目录

- [项目简介](#项目简介)
- [架构总览](#架构总览)
- [目录结构](#目录结构)
- [核心模块说明](#核心模块说明)
- [关键技术要点](#关键技术要点)
- [游戏流程](#游戏流程)
- [运行方式](#运行方式)
- [后续扩展方向](#后续扩展方向)
- [关键文件速查表](#关键文件速查表)
- [总结](#总结)

## 项目简介

本项目是一个回合制卡牌对战游戏的服务端逻辑实现。四名玩家各代表一种花色（红桃 / 黑桃 / 方片 / 梅花），通过抽牌、出牌、连锁等操作进行对战。

当前阶段：完成基础数据结构与游戏主循环的搭建，尚未实现完整的出牌规则与连锁结算。

设计目标：

- 服务端统一管理所有游戏状态，客户端只做渲染
- 卡牌的移动、抽牌、洗牌等行为全部由 GameMaster 集中控制
- 为后续连锁（Chain）机制、效果（Effect）系统预留扩展点

## 架构总览

```text
┌─────────────────────────────────────────────────┐
│                   Server 端                      │
│                                                  │
│  ┌────────────────────────────────────────┐     │
│  │            GameMaster                   │     │
│  │  ── 游戏逻辑核心 ──                      │     │
│  │  · round / phase / turn_order           │     │
│  │  · players[] / chain_stack              │     │
│  │  · draw_pile / field                    │     │
│  │  · move_cards / draw_cards / shuffle    │     │
│  └───────────────┬────────────────────────┘     │
│                  │ 管理                          │
│       ┌──────────┼──────────┐                   │
│       ▼          ▼          ▼                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│  │ Player  │ │  Zones  │ │  Card   │            │
│  │ ×4      │ │ DrawPile│ │ suit    │            │
│  │ hand    │ │ Field   │ │ rank    │            │
│  │ my_turn │ │ Hand    │ │ zone    │            │
│  │ can_chain│ │        │ │ uid     │            │
│  └─────────┘ └─────────┘ └─────────┘            │
│                                                  │
└─────────────────────────────────────────────────┘
                       │
                       │ 状态快照（未来）
                       ▼
              ┌─────────────────┐
              │   Client 端      │
              │  只渲染自己的     │
              │  手牌 + Field    │
              │  其他渲染为牌背   │
              └─────────────────┘
```

## 目录结构

```text
project/
├── main.py           # 测试入口 / 程序启动点
├── GameMaster.py     # 游戏逻辑核心（服务端）
├── Player.py         # 玩家对象
├── Card.py           # 卡牌对象
├── enums.py          # 枚举定义（Suit / Rank / Zone / Phase）
├── zones.py          # 区域容器（DrawPile / Field / Hand）
└── README.md         # 项目说明文档
```

## 核心模块说明

### enums.py — 枚举定义

| 枚举 | 类型 | 用途 | 位置 |
| --- | --- | --- | --- |
| Suit | StrEnum | 花色：HEART / SPADE / DIAMOND / CLUB | enums.py |
| Rank | IntEnum | 点数：ACE=14, TWO~KING，支持大小比较 | enums.py |
| Zone | Enum | 区域标识：DRAW_PILE / FIELD / HAND | enums.py |
| Phase | IntEnum | 阶段：DRAW_PHASE=0 / PLAY_PHASE=1 / END_PHASE=2 | enums.py |

要点：

- `Rank` 使用 `IntEnum` 是为了让点数可以直接比较大小（如 `Rank.ACE > Rank.KING`）
- `Phase` 使用 `IntEnum` 是为了能用 `(phase + 1) % len(Phase)` 循环推进
- `Zone` 不存容器类对象，只作逻辑标识，实际容器由 `GameMaster` 持有

### Card.py — 卡牌对象

```python
class Card:
    _id_counter = 0          # 全局自增 ID

    def __init__(self, suit, rank, zone=None):
        self.suit = suit     # Suit 枚举
        self.rank = rank     # Rank 枚举
        self.zone = zone     # Zone 枚举（逻辑位置）
        self.uid = ...       # 唯一 ID，用于区分同花色同点数的牌
```

职责：

- 保存卡牌的花色 / 点数 / 所属区域
- 提供 `change_zone()` 更新逻辑位置
- 实现 `__eq__` / `__hash__`（基于 `uid`），使其可作为集合元素与列表成员判断

不负责：

- 不管理自己属于哪个容器列表（由 Zone 容器和 GameMaster 维护）
- 不处理可见性（由客户端根据 `zone` 判断渲染方式）

### zones.py — 区域容器

```python
class ZoneBase:
    def __init__(self, owner=None):
        self.cards = []      # 装 Card 对象的列表
        self.owner = owner   # 所属玩家（HAND 时非空）

class DrawPile(ZoneBase): ...   # 抽牌堆（全局唯一）
class Field(ZoneBase):    ...   # 出牌区
class Hand(ZoneBase):     ...   # 手牌区（每个玩家一个）
```

职责：

- 只作为 `Card` 对象的容器，提供 `add` / `remove` / `__iter__` / `__len__`
- 记录 `owner`（手牌区需要知道自己属于哪个玩家）

不负责：

- 不做任何游戏规则判断
- 不主动移动卡牌（移动逻辑全部在 `GameMaster`）

### Player.py — 玩家对象

```python
class Player:
    def __init__(self, faction: Suit):
        self.faction = faction      # 所属花色
        self.hand = Hand(owner=self) # 手牌区
        self.my_turn = False        # 是否当前回合
        self.can_chain = False      # 是否能发动连锁

    def draw_cards(self, gm, number=1):
        gm.draw_cards(self, number)   # 委托给 GM 处理
```

职责：

- 持有自己的手牌容器
- 记录回合状态 `my_turn` 与连锁状态 `can_chain`
- 抽牌时委托给 `GameMaster`（不自己操作数据）

### GameMaster.py — 游戏逻辑核心

属性：

| 属性 | 说明 |
| --- | --- |
| round | 当前轮数 |
| phase | 当前阶段（Phase 枚举） |
| players | 四个 Player 对象 |
| turn_order | `{索引: Player}` 出手顺序映射 |
| turn_index | 当前出手玩家在 `turn_order` 中的索引 |
| chain_stack | 连锁效果栈（预留） |
| draw_pile | 全局抽牌堆 |
| field | 全局出牌区 |

方法分类：

| 类别 | 方法 | 说明 |
| --- | --- | --- |
| 初始化 | `setup()` | 创建玩家、洗牌、发初始手牌 |
| 流程控制 | `next_round()` / `next_turn()` / `next_phase()` | 推进游戏节奏 |
| 卡牌移动 | `move_cards()` / `_find_zone_of()` / `_get_zone()` | 统一移动接口 |
| 抽牌洗牌 | `draw_cards()` / `shuffle_draw_pile()` | 抽牌堆操作 |
| 连锁（预留） | `append_chain()` / `resolve_chain()` | 后进先出结算 |
| 胜负 | `declare_victory()` | 宣布胜利 |

## 关键技术要点

### 1. 单一数据源（Single Source of Truth）

所有卡牌移动逻辑集中在 `GameMaster.move_cards()`：

```python
def move_cards(self, cards, to_zone, to_player=None):
    target = self._get_zone(to_zone, to_player)
    for card in cards:
        src = self._find_zone_of(card)   # 找到源容器
        if src:
            src.remove(card)             # 从源移除
        target.add(card)                 # 加入目标
        card.change_zone(to_zone)        # 同步逻辑位置
```

位置：`GameMaster.py → move_cards / _find_zone_of / _get_zone`

为什么这样设计：

- `Player` 和 `Zone` 不知道彼此的存在，避免循环依赖
- 所有状态变更走同一入口，便于加日志、加规则校验、加连锁触发

### 2. 逻辑位置 vs 物理容器

| 概念 | 存储位置 | 用途 |
| --- | --- | --- |
| 逻辑位置 | `Card.zone` | 客户端渲染、连锁判定、规则校验 |
| 物理容器 | `Zone.cards` 列表 | 服务端遍历、移动、洗牌 |

位置：`Card.py`（`self.zone`）+ `zones.py`（`self.cards`）

两者必须由 `move_cards()` 保证同步，避免出现“牌说自己在手牌，但手牌列表里没有”的不一致。

### 3. 状态与渲染分离

服务端不处理任何可见性逻辑，只维护 `Card.zone`：

- 客户端渲染时：只渲染自己的 `Hand` 和 `Field` 中的卡牌牌面
- 其他区域（对手手牌、抽牌堆）一律渲染为牌背

位置：设计约定，未来在客户端实现；服务端只需保证 `Card.zone` 正确

### 4. 委托模式（Player → GameMaster）

玩家不自己操作数据，而是通知 `GM` 代为执行：

```python
# Player.py
def draw_cards(self, gm, number=1):
    gm.draw_cards(self, number)   # 委托
```

位置：`Player.py → draw_cards`

好处：所有状态变更集中，避免玩家绕过 `GM` 直接改数据。

### 5. 枚举值设计

| 枚举 | 类型选择 | 原因 |
| --- | --- | --- |
| Suit | StrEnum | 花色是字符串标识，便于日志与序列化 |
| Rank | IntEnum | 需要比较大小（ACE=14 > KING=13） |
| Phase | IntEnum | 需要循环推进 `(phase + 1) % len(Phase)` |
| Zone | 普通 Enum | 只需唯一标识，不需比较或运算 |

位置：`enums.py`

### 6. 连锁机制预留（Chain）

用列表模拟栈，后进先出结算：

```python
def append_chain(self, chain_effect):
    self.chain_stack.append(chain_effect)

def resolve_chain(self):
    while self.chain_stack:
        effect = self.chain_stack.pop()
        effect.resolve(self)
```

位置：`GameMaster.py → chain_stack / append_chain / resolve_chain`

后续扩展需新增：

- `ChainEffect` 基类（含 `resolve(gm)` 方法）
- `effect_library` 效果库
- `is_chain_able()` 遍历所有玩家手牌判断能否发动

### 7. 避免循环导入

```text
Card.py     → 只依赖 enums
Player.py   → 依赖 enums / zones，用 TYPE_CHECKING 延迟导入 Card
GameMaster  → 作为顶层协调者，导入所有模块
```

位置：`Player.py` 中的 `if TYPE_CHECKING: from Card import Card`

## 游戏流程

```text
setup()
  │
  ├─ 创建 4 名玩家（四种花色）
  ├─ 随机打乱出手顺序 → turn_order
  ├─ 生成 52 张牌 → draw_pile
  ├─ shuffle_draw_pile()
  └─ 每人发 5 张 → draw_cards(player, 5)

主循环（每回合）：
  │
  ├─ DRAW_PHASE  ：draw_cards(current_player, 1)
  ├─ PLAY_PHASE  ：出牌 / 连锁（待实现）
  ├─ END_PHASE   ：结算 / 清理
  │
  └─ next_turn()
        ├─ 若回到 0 号玩家 → round += 1
        ├─ 更新 my_turn 标志
        └─ phase 重置为 DRAW_PHASE
```

## 运行方式

```bash
# 直接运行测试入口
python main.py
```

预期输出：

```text
=== 第 1 轮，Player(SPADE, hand=5) 的回合 ===
抽牌堆剩余: 32
HEART: [Card(3 of HEART), ...]
SPADE: [Card(ACE of SPADE), ...]
...
```

## 后续扩展方向

| 优先级 | 方向 | 涉及文件 | 说明 |
| --- | --- | --- | --- |
| 🔴 高 | 出牌逻辑 | `GameMaster.py` | `play_card()`: 校验阶段 / 回合 / 手牌，移动卡牌到 `Field` |
| 🔴 高 | 规则校验 | `GameMaster.py` | 出牌前检查合法性，非法操作抛异常 |
| 🟡 中 | 连锁系统 | 新增 `ChainEffect.py` | 定义效果基类、触发时机、`is_chain_able()` 实现 |
| 🟡 中 | 状态序列化 | `Player.py` / `Card.py` | `to_dict()` 输出客户端可见快照 |
| 🟢 低 | 胜负判定 | `GameMaster.py` | 血量 / 牌库耗尽 / 特定组合 |
| 🟢 低 | 网络层 | 新增 `server.py` | `asyncio` / `websockets` 包装 `GM` |

## 关键文件速查表

| 我想…… | 看这个文件 | 关键位置 |
| --- | --- | --- |
| 改卡牌属性 | `Card.py` | `__init__` |
| 改区域容器 | `zones.py` | `ZoneBase` |
| 加玩家行为 | `Player.py` | 委托给 GM 的方法 |
| 改游戏流程 | `GameMaster.py` | `next_turn` / `next_phase` |
| 改卡牌移动规则 | `GameMaster.py` | `move_cards` |
| 加新枚举 | `enums.py` | 对应类 |
| 加连锁效果 | `GameMaster.py` | `chain_stack` / `resolve_chain` |

## 总结

本项目当前处于基础框架搭建阶段，核心设计已成型：

- ✅ 数据结构清晰（`Card` / `Zone` / `Player` / `GameMaster` 职责分明）
- ✅ 单一数据源原则（所有移动走 `move_cards`）
- ✅ 状态与渲染分离（服务端只管 `Card.zone`）
- ✅ 枚举类型选型合理（`IntEnum` / `StrEnum` 各取所需）
- ⏳ 出牌逻辑与连锁系统待实现

下一步优先实现 `play_card()` 与 `is_chain_able()`，即可进入可玩的最小闭环。

文档随项目迭代更新，建议配合代码注释一起阅读。
