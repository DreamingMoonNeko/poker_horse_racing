import enums

class Card:
    _id_counter = 0

    def __init__(self, suit: enums.Suit, rank: enums.Rank, zone: enums.Zone = None):
        self.suit = suit
        self.rank = rank
        self.zone = zone
        Card._id_counter += 1
        self.uid = Card._id_counter

    def update(self, zone: enums.Zone):
        self.zone = zone

    def change_zone(self, zone: enums.Zone):
        self.zone = zone

    def __repr__(self):
        return f"Card({self.rank.name} of {self.suit.name})"

    def __eq__(self, other):
        return isinstance(other, Card) and self.uid == other.uid

    def __hash__(self):
        return hash(self.uid)

    """
    the attributes of a card contains its suit and rank, and the zone it is in
    关于zone的用法：四个玩家的手牌区加上抽牌堆和出牌区，一共6个zone
    每个zone都是一个容器，实质是只装Card对象的列表
    当一张卡发生移动时，比如说从抽牌堆移动到A手中，需要更改card的zone属性，然后移除抽牌堆的该对象，往A手中再添加该对象
    还有一点，我需要根据卡牌所处的位置更改其可见性，不过这个行为不需要由卡牌本身实现：
    玩家客户端渲染各自的卡牌时，只渲染自己手牌和Field中卡牌的牌面即可，其他牌全部渲染为牌背
    """