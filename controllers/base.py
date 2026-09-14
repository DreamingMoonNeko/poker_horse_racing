"""玩家输入抽象层

GameMaster 只通过 PlayerController 接口获取玩家决策，因此：
- 阶段一（TODO 1）：同一个客户端里给 4 名玩家各挂一个 HumanController（本地热座）
- 阶段二（TODO 2/3）：换成 NetworkController，决策改为从 socket 读取
- AI 控制器则用于演示 / 自动对局

所有 PlayerController 必须实现的方法：
    choose_action(gm, player)   -> Action             # 当前回合玩家：出牌 / 结束回合
    wants_chain(gm, player)     -> bool               # 是否要连锁
    choose_chain(gm, player)    -> (cards, combo)     # 连锁选牌
    choose_discard(gm, player, number) -> [cards]     # 弃牌选择
    notify(gm, event)                                 # 通知（UI 刷新 / 反馈）
"""

from dataclasses import dataclass, field

import enums


@dataclass
class Action:
    """当前回合玩家的决策结果"""

    kind: str                     # 'play' | 'end' | 'skip'
    cards: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @staticmethod
    def play(cards, **meta) -> 'Action':
        return Action('play', list(cards), meta)

    @staticmethod
    def end() -> 'Action':
        return Action('end')

    @staticmethod
    def skip() -> 'Action':
        return Action('skip')

    def __repr__(self):
        if self.kind == 'play':
            return f'Action(play, {[c.short_name() for c in self.cards]})'
        return f'Action({self.kind})'


class PlayerController:
    """控制器基类。默认实现全部拒绝行动，子类按需覆盖。"""

    kind = 'base'

    def __init__(self, faction: enums.Suit = None, name: str = None):
        self.faction = faction
        self.name = name or (faction.name if faction else 'controller')
        # 供 UI 渲染的等待状态：{'stage': ..., 'prompt': ...}
        self.pending: dict | None = None

    # ---------- 决策 ----------
    def choose_action(self, gm, player) -> Action:
        raise NotImplementedError

    def wants_chain(self, gm, player) -> bool:
        return False

    def choose_chain(self, gm, player):
        return None, None

    def choose_discard(self, gm, player, number: int) -> list:
        """默认弃牌策略：优先弃掉最右侧（通常是最后抽到）的牌"""
        return list(player.hand.cards[-number:]) if number > 0 else []

    # ---------- 通知 ----------
    def notify(self, gm, event: dict):
        """接收 GameMaster 抛出的事件（出牌、抽牌、结算、结束）"""

    # ---------- 生命周期 ----------
    def is_waiting(self) -> bool:
        """是否正卡在等待玩家输入（AI 永远返回 False）"""
        return False

    def clear_pending(self):
        self.pending = None

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.name}>'
