"""网络玩家控制器（TODO 1 阶段二）

一个客户端设备只需要实现「一名玩家」的输入：客户端把玩家决策打包成
Intent 发给主机，主机的 NetworkController 收到后填入队列，
GameMaster 像对待 HumanController 一样向它索取决策。

这样阶段一（本地热座）和阶段二（联机）共用同一套 GameMaster 流程。
"""

import enums
import rules
from controllers.base import Action, PlayerController


class NetworkController(PlayerController):
    kind = 'network'

    def __init__(self, faction: enums.Suit = None, peer=None, name: str = None):
        super().__init__(faction, name or (peer.name if peer else 'remote'))
        self.peer = peer
        self.action_queue: list = []
        self.chain_queue: list = []
        self.discard_queue: list = []
        self.pending: dict | None = None
        self.last_intent: dict | None = None

    # ------------------------------------------------------------ 主机侧：填入决策
    def apply_intent(self, gm, player, data: dict) -> tuple:
        """把客户端发来的 Intent 转成控制器决策。返回 (是否采纳, 说明)"""
        kind = str(data.get('kind', '')).lower()
        uids = list(data.get('uids') or [])
        cards = self._resolve(player, uids)
        self.last_intent = dict(data)

        if kind == 'play':
            if not cards:
                return False, '没有选中任何牌'
            return True, self._queue_play(gm, player, cards)
        if kind == 'end_turn':
            self.action_queue.append(Action.end())
            self._clear_pending('choose_action')
            return True, '结束回合'
        if kind == 'skip':
            self.action_queue.append(Action.skip())
            self._clear_pending('choose_action')
            return True, '跳过'
        if kind == 'chain':
            if not cards:
                return False, '没有选中任何牌'
            self.chain_queue.append(cards)
            self._clear_pending('choose_chain')
            return True, '连锁'
        if kind == 'decline_chain':
            self.chain_queue.append(None)
            self._clear_pending('choose_chain')
            # 走正式放弃路径，保证「本回合不再询问」的语义与本地一致
            gm.declare_chain(player, None)
            return True, '放弃连锁'
        if kind == 'discard':
            self.discard_queue.append(cards)
            self._clear_pending('discard')
            return True, '弃牌'
        return False, f'未知指令：{kind}'

    def _queue_play(self, gm, player, cards) -> str:
        """区分「当前回合玩家的主动出牌」和「连锁宣言」"""
        if player.my_turn:
            self.action_queue.append(Action.play(cards))
            self._clear_pending('choose_action')
            return '出牌'
        self.chain_queue.append(cards)
        self._clear_pending('choose_chain')
        return '连锁'

    def _clear_pending(self, stage: str = None):
        if stage is None or (self.pending and self.pending.get('stage') == stage):
            self.pending = None

    def _resolve(self, player, uids) -> list:
        wanted = set(uids)
        return [c for c in player.hand if c.uid in wanted]

    # ------------------------------------------------------------ GameMaster 侧：索取决策
    def choose_action(self, gm, player) -> Action:
        if self.action_queue:
            self.pending = None
            return self.action_queue.pop(0)
        self.pending = {'stage': 'choose_action',
                        'prompt': f'{player.name}：等待远程玩家出牌…'}
        return None

    def wants_chain(self, gm, player) -> bool:
        if self.chain_queue:
            return True
        if player.chained_this_turn or not player.can_chain:
            return False
        self.pending = {'stage': 'ask_chain', 'prompt': f'{player.name}：连锁窗口'}
        return True

    def choose_chain(self, gm, player):
        if self.chain_queue:
            cards = self.chain_queue.pop(0)
            self.pending = None
            if not cards:
                return None, None
            return list(cards), None
        self.pending = {'stage': 'choose_chain',
                        'prompt': f'{player.name}：等待远程玩家连锁…'}
        return None, None

    def choose_discard(self, gm, player, number: int) -> list:
        if self.discard_queue:
            picked = self.discard_queue.pop(0)
            return picked[:number]
        # 远程玩家没及时回应时自动弃最没用的牌，保证流程不中断
        ordered = sorted(player.hand,
                         key=lambda c: (c.suit == player.faction, int(c.rank)))
        return ordered[:number]

    def is_waiting(self) -> bool:
        return self.pending is not None

    # ------------------------------------------------------------ 快照辅助
    def pending_state(self) -> dict | None:
        return dict(self.pending) if self.pending else None

    def __repr__(self):
        return f'<NetworkController {self.name} pending={bool(self.pending)}>'


# ---------------------------------------------------------------- Intent 构造
def intent_play(uids) -> dict:
    return {'kind': 'play', 'uids': list(uids)}


def intent_end_turn() -> dict:
    return {'kind': 'end_turn'}


def intent_skip() -> dict:
    return {'kind': 'skip'}


def intent_chain(uids) -> dict:
    return {'kind': 'chain', 'uids': list(uids)}


def intent_decline_chain() -> dict:
    return {'kind': 'decline_chain'}


def intent_discard(uids) -> dict:
    return {'kind': 'discard', 'uids': list(uids)}


# 客户端可以本地先做一次合法性预检，减少无效往返（最终仍由主机把关）
def local_validate_play(hand, uids, is_my_turn: bool) -> tuple:
    wanted = set(uids)
    cards = [c for c in hand if c.uid in wanted]
    if not cards:
        return False, '没有选中任何牌'
    if len(cards) != len(wanted):
        return False, '选中的牌不在手牌里'
    return True, ''
