from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from Card import Card

class ZoneBase:
    """所有区域的基类，只作为 Card 对象的容器"""
    def __init__(self, owner=None):
        self.cards: List['Card'] = []
        self.owner = owner  # 所属玩家（抽牌堆/Field 为 None 或共享）

    def add(self, card: 'Card'):
        self.cards.append(card)

    def remove(self, card: 'Card'):
        if card in self.cards:
            self.cards.remove(card)

    def __len__(self):
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)

    def __repr__(self):
        return f"{self.__class__.__name__}({len(self.cards)} cards)"


class DrawPile(ZoneBase):
    pass


class Field(ZoneBase):
    pass


class Hand(ZoneBase):
    pass