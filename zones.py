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

    def extend(self, cards):
        self.cards.extend(cards)

    def remove(self, card: 'Card'):
        if card in self.cards:
            self.cards.remove(card)

    def clear(self) -> list:
        """清空区域并返回被清出的牌（用于洗回抽牌堆）"""
        out = list(self.cards)
        self.cards.clear()
        return out

    def __contains__(self, card: 'Card'):
        return card in self.cards

    def __len__(self):
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)

    def __getitem__(self, index):
        return self.cards[index]

    def __repr__(self):
        return f"{self.__class__.__name__}({len(self.cards)} cards)"


class DrawPile(ZoneBase):
    """抽牌堆。约定列表尾部为牌堆顶部（顶部抽牌）"""

    def draw_many(self, number: int) -> list:
        """从顶部抽出至多 number 张牌（仅从容器移除，不负责改 zone）"""
        n = max(0, min(number, len(self.cards)))
        if n == 0:
            return []
        taken = self.cards[-n:]
        del self.cards[-n:]
        return taken

    def peek(self, number: int = 1) -> list:
        return self.cards[-number:]


class Field(ZoneBase):
    pass


class Hand(ZoneBase):
    pass


def build_deck() -> list:
    """生成一副 52 张牌（不含大小王），未洗牌，zone 为 DRAW_PILE"""
    from Card import Card
    from enums import Rank, Suit, Zone
    return [Card(suit, rank, Zone.DRAW_PILE) for suit in Suit for rank in Rank]
