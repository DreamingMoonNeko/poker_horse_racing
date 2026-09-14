from typing import List, TYPE_CHECKING
from enums import Suit
from zones import Hand

if TYPE_CHECKING:
    from Card import Card

class Player:
    def __init__(self, faction: Suit):
        self.faction = faction
        self.hand = Hand(owner=self)
        self.field = None  # 由 GameMaster 注入（共享 Field 或每人独立）
        self.my_turn = False
        self.can_chain = False

    def draw_cards(self, gm, number: int = 1):
        """
        通知 GameMaster 帮自己抽牌。
        实际逻辑在 GameMaster.move_cards 中完成。
        """
        gm.draw_cards(self, number)

    def __repr__(self):
        return f"Player({self.faction.name}, hand={len(self.hand)})"