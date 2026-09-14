from typing import TYPE_CHECKING

from enums import Suit
from zones import Hand

if TYPE_CHECKING:  # pragma: no cover
    from Card import Card
    from GameMaster import GameMaster


class Player:
    def __init__(self, faction: Suit, name: str = None):
        self.faction = faction
        self.name = name or f"{faction.name}"
        self.hand = Hand(owner=self)
        self.field = None  # 由 GameMaster 注入（共享 Field 或每人独立）
        self.my_turn = False
        self.can_chain = False
        self.score = 0
        self.chained_this_turn = False  # 每回合每人最多连锁 1 次（RULES §5.3）
        self.declined_chain_this_turn = False  # 本回合是否已放弃连锁（避免反复询问）
    # ---------- 手牌查询 ----------
    @property
    def hand_size(self) -> int:
        return len(self.hand)

    def owns(self, card: 'Card') -> bool:
        return card in self.hand.cards

    # ---------- 行为（统一委托给 GameMaster） ----------
    def draw_cards(self, gm: 'GameMaster', number: int = 1):
        """
        通知 GameMaster 帮自己抽牌。
        实际逻辑在 GameMaster.move_cards 中完成。
        """
        return gm.draw_cards(self, number)

    def play_cards(self, gm: 'GameMaster', cards: list):
        """委托 GameMaster 出牌"""
        return gm.play_cards(self, cards)

    def skip(self, gm: 'GameMaster'):
        return gm.skip_turn(self)

    # ---------- 回合状态 ----------
    def begin_turn(self):
        self.my_turn = True
        self.chained_this_turn = False
        self.declined_chain_this_turn = False
        self.can_chain = False

    def end_turn(self):
        self.my_turn = False
        self.can_chain = False

    # ---------- 快照 ----------
    def to_dict(self, reveal_hand: bool = True) -> dict:
        return {
            'name': self.name,
            'faction': str(self.faction),
            'score': self.score,
            'my_turn': self.my_turn,
            'can_chain': self.can_chain,
            'hand_size': len(self.hand),
            'hand': [c.to_dict(reveal=reveal_hand) for c in self.hand],
        }

    def __repr__(self):
        return f"Player({self.faction.name}, hand={len(self.hand)}, score={self.score})"
