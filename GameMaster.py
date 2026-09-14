from random import shuffle, sample
import enums
from zones import DrawPile, Field, Hand
from Card import Card
from Player import Player


class GameMaster:
    def __init__(self):
        self.round = 0
        self.players: list[Player] = []
        self.turn_order: dict[int, Player] = {}
        self.turn_index = 0
        self.phase = enums.Phase.END_PHASE
        self.chain_stack = []

        # 全局区域
        self.draw_pile = DrawPile()
        self.field = Field()  # 若每人独立 Field，改为放在 Player 里

    # ---------- 初始化 ----------
    def setup(self):
        """创建 4 名玩家、初始化 52 张牌、洗牌、发初始手牌"""
        # 1. 创建玩家（用四种花色代表四家）
        self.players = [Player(suit) for suit in enums.Suit]

        # 2. 随机决定出手顺序
        order = sample(self.players, len(self.players))
        self.turn_order = {i: p for i, p in enumerate(order)}

        # 3. 生成 52 张牌入抽牌堆
        for suit in enums.Suit:
            for rank in enums.Rank:
                card = Card(suit, rank, enums.Zone.DRAW_PILE)
                self.draw_pile.add(card)

        # 4. 洗牌
        self.shuffle_draw_pile()

        # 5. 每人发 5 张
        for p in self.players:
            self.draw_cards(p, 5)

        self.round = 1
        self.phase = enums.Phase.DRAW_PHASE
        self.turn_order[0].my_turn = True

    # ---------- 流程控制 ----------
    def next_round(self):
        self.round += 1
        self.turn_index = 0
        self._update_turn_flag()

    def next_turn(self):
        """轮到下一位玩家"""
        self.turn_order[self.turn_index].my_turn = False
        self.turn_index = (self.turn_index + 1) % len(self.turn_order)
        # 转回 0 号玩家则回合 +1
        if self.turn_index == 0:
            self.round += 1
        self._update_turn_flag()
        self.phase = enums.Phase.DRAW_PHASE  # 新回合从抽牌阶段开始

    def _update_turn_flag(self):
        for p in self.players:
            p.my_turn = False
        self.turn_order[self.turn_index].my_turn = True

    def next_phase(self):
        self.phase = enums.Phase((self.phase + 1) % len(enums.Phase))

    def current_player(self) -> Player:
        return self.turn_order[self.turn_index]

    # ---------- 卡牌移动 ----------
    def _get_zone(self, zone: enums.Zone, player: Player = None):
        """根据 Zone 枚举和玩家找到实际容器"""
        if zone == enums.Zone.DRAW_PILE:
            return self.draw_pile
        if zone == enums.Zone.FIELD:
            return self.field
        if zone == enums.Zone.HAND:
            if player is None:
                raise ValueError("HAND 区域需要指定玩家")
            return player.hand
        raise ValueError(f"未知区域: {zone}")

    def move_cards(self, cards: list[Card], to_zone: enums.Zone,
                   to_player: Player = None):
        """从卡牌当前所在区域移动到目标区域"""
        target = self._get_zone(to_zone, to_player)
        for card in cards:
            # 找到源区域
            src = self._find_zone_of(card)
            if src is not None:
                src.remove(card)
            # 加入目标区域
            target.add(card)
            card.change_zone(to_zone)

    def _find_zone_of(self, card: Card):
        """在所有区域中查找卡牌所在容器"""
        if card in self.draw_pile.cards:
            return self.draw_pile
        if card in self.field.cards:
            return self.field
        for p in self.players:
            if card in p.hand.cards:
                return p.hand
        return None

    # ---------- 抽牌 ----------
    def draw_cards(self, player: Player, number: int = 1):
        """从抽牌堆顶部抽 number 张牌到玩家手牌"""
        n = min(number, len(self.draw_pile))
        if n < number:
            print(f"抽牌堆不足，仅抽到 {n} 张")
        drawn = self.draw_pile.cards[-n:] if n > 0 else []
        self.move_cards(drawn, enums.Zone.HAND, player)

    def shuffle_draw_pile(self):
        shuffle(self.draw_pile.cards)

    # ---------- 连锁（预留） ----------
    def append_chain(self, chain_effect):
        self.chain_stack.append(chain_effect)

    def resolve_chain(self):
        """后进先出结算"""
        while self.chain_stack:
            effect = self.chain_stack.pop()
            effect.resolve(self)

    # ---------- 胜负 ----------
    def declare_victory(self, player: Player):
        print(f"{player.faction.name} 玩家胜利！")