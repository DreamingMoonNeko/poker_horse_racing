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

    # ---------- 展示 ----------
    @property
    def color(self) -> str:
        return enums.suit_color(self.suit)

    @property
    def symbol(self) -> str:
        """形如 ♥A 的短名"""
        return f"{enums.SUIT_SYMBOL[self.suit]}{enums.RANK_SYMBOL[self.rank]}"

    @property
    def name(self) -> str:
        """形如 红桃A 的中文名"""
        return f"{enums.SUIT_CN[self.suit]}{enums.RANK_SYMBOL[self.rank]}"

    def short_name(self) -> str:
        """形如 ♥A。仅用于控制台/调试；界面文字请用 text_name，
        因为很多中文字体没有 ♠♥♦♣ 字形（会显示成豆腐块）。"""
        return self.symbol

    @property
    def text_name(self) -> str:
        """形如 红桃A —— 只用必然存在的字符，界面日志安全"""
        return f"{enums.SUIT_CN[self.suit]}{enums.RANK_SYMBOL[self.rank]}"

    def __repr__(self):
        return f"Card({self.rank.name} of {self.suit.name})"

    def __eq__(self, other):
        return isinstance(other, Card) and self.uid == other.uid

    def __hash__(self):
        return hash(self.uid)

    # ---------- 序列化（网络同步 / 状态快照用） ----------
    def to_dict(self, reveal: bool = True) -> dict:
        """reveal=False 时只输出 uid，用于隐藏对手手牌"""
        data = {'uid': self.uid}
        if reveal:
            data['suit'] = str(self.suit)
            data['rank'] = int(self.rank)
            data['zone'] = self.zone.value if self.zone is not None else None
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Card':
        """从快照恢复卡牌，并沿用其 uid 以保证多端一致"""
        card = cls(enums.Suit(data['suit']), enums.Rank(data['rank']),
                   enums.Zone(data['zone']) if data.get('zone') else None)
        card.uid = data['uid']
        Card._id_counter = max(Card._id_counter, card.uid)
        return card

    """
    the attributes of a card contains its suit and rank, and the zone it is in
    关于zone的用法：四个玩家的手牌区加上抽牌堆和出牌区，一共6个zone
    每个zone都是一个容器，实质是只装Card对象的列表
    当一张卡发生移动时，比如说从抽牌堆移动到A手中，需要更改card的zone属性，然后移除抽牌堆的该对象，往A手中再添加该对象
    还有一点，我需要根据卡牌所处的位置更改其可见性，不过这个行为不需要由卡牌本身实现：
    玩家客户端渲染各自的卡牌时，只渲染自己手牌和Field中卡牌的牌面即可，其他牌全部渲染为牌背
    """
