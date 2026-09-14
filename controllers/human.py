"""人类玩家控制器（TODO 1：玩家输入）

同一个客户端里为 4 名玩家各创建一个 HumanController，即「本地热座」模式：
当前行动的那名玩家占据窗口主面板，其余玩家保留视角面板，键盘/鼠标切换。

控制器本身不做规则判断（规则由 GameMaster 把关），只负责：
- 把「该你操作了」暴露成 pending 状态给 UI
- 接收 UI 通过 submit_* 推入的决策
"""

import enums
from controllers.base import Action, PlayerController


class HumanController(PlayerController):
    kind = 'human'

    def __init__(self, faction: enums.Suit = None, name: str = None):
        super().__init__(faction, name or f'{enums.SUIT_CN.get(faction, "玩家")}')
        self.action_queue: list = []
        self.chain_queue: list = []
        self.discard_queue: list = []
        self.declined_chain = False       # 本回合是否已放弃过连锁
        self.decline_discard = False

    # ------------------------------------------------------------ 输入接口（UI 调用）
    def submit_action(self, action: Action):
        self.action_queue.append(action)

    def submit_cards(self, cards):
        """当前回合玩家点击「出牌」"""
        self.submit_action(Action.play(cards))

    def submit_end_turn(self):
        self.submit_action(Action.end())

    def submit_chain(self, cards):
        """连锁选牌确认"""
        self.chain_queue.append(list(cards))

    def submit_decline_chain(self):
        """放弃连锁（压入 None 表示放弃）"""
        self.chain_queue.append(None)
        # 记下「本回合已放弃连锁」：否则同一回合里别人再出牌时会反复弹窗问你要不要连锁
        self.declined_chain = True

    def submit_discard(self, cards):
        self.discard_queue.append(list(cards))

    def cancel_pending(self):
        """取消当前待输入状态（用于界面上的「返回」）"""
        self.clear_pending()

    def is_waiting(self) -> bool:
        return self.pending is not None

    # ------------------------------------------------------------ 决策实现
    def choose_action(self, gm, player) -> Action:
        if self.action_queue:
            self.clear_pending()
            return self.action_queue.pop(0)
        self.pending = {
            'stage': 'choose_action',
            'prompt': f'{player.name}：选择要出的牌，或结束回合',
            'can_skip': True,
        }
        return None

    def wants_chain(self, gm, player) -> bool:
        # 已经排队了「连锁 / 放弃连锁」的决定 → 直接放行
        if self.chain_queue:
            return True
        if player.chained_this_turn or not player.can_chain:
            return False
        if self.declined_chain:
            return False
        if self.pending and self.pending.get('stage') == 'choose_chain':
            # 已经弹着连锁选牌面板，别覆盖玩家的当前选择
            return True
        self.pending = {
            'stage': 'ask_chain',
            'prompt': f'{player.name}：是否发动连锁？',
        }
        return True

    def choose_chain(self, gm, player):
        if self.chain_queue:
            decided = self.chain_queue.pop(0)
            self.clear_pending()
            if not decided:
                # 走 GameMaster 的正式放弃路径，让「本回合不再询问」对 AI/联机同样生效
                gm.declare_chain(player, None)
                self.declined_chain = True
                return None, None
            return list(decided), None
        self.pending = {
            'stage': 'choose_chain',
            'prompt': f'{player.name}：选择连锁的牌',
        }
        return None, None

    def choose_discard(self, gm, player, number: int) -> list:
        if self.discard_queue:
            return self.discard_queue.pop(0)
        # 未指定时按「最没用的牌优先」自动弃牌，保证流程不中断
        ordered = sorted(player.hand,
                         key=lambda c: (c.suit == player.faction, int(c.rank)))
        return ordered[:number]
