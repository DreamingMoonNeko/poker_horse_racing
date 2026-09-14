"""卡牌效果与连锁栈（RULES §4.4 / §6）

连锁采用「后进先出」结算：每次出牌把若干 Effect 依次压栈，
resolve 时从栈顶弹出，因此最后一手的效果最先结算。
"""

import enums


class Effect:
    """效果基类：GameMaster.resolve_chain 只要求实现 resolve(gm)"""

    kind = 'effect'
    label = '效果'

    def __init__(self, owner=None, source_cards=None):
        self.owner = owner
        self.source_cards = list(source_cards or [])
        self.resolved = False
        self.negated = False   # 被【打断】无效化
        self.detail = ''       # 结算后的描述，用于回放/日志
        self.turn_stamp = 0    # 压栈时的轮次，用于日志

    # -- 结算 --------------------------------------------------------
    def resolve(self, gm):
        if self.resolved or self.negated:
            return []
        self.resolved = True
        return self.apply(gm)

    def apply(self, gm) -> list:
        """由子类实现，返回给 UI 播放的动画事件列表"""
        return []

    # -- 无效化 ------------------------------------------------------
    def negate(self, gm):
        if self.resolved:
            return False
        self.negated = True
        self.detail = f'{self.label} 被打断'
        gm.log(f'{self.owner.name} 的【{self.label}】被无效化')
        return True

    def __repr__(self):
        flag = ' (negated)' if self.negated else ''
        return f'<{self.__class__.__name__} {self.owner.name if self.owner else "-"}{flag}>'


class DrawEffect(Effect):
    """抽牌效果"""

    kind = 'draw'

    def __init__(self, player, number: int, source_cards=None):
        super().__init__(owner=player, source_cards=source_cards)
        self.number = number
        self.label = f'抽 {number} 张'

    def apply(self, gm):
        drawn = gm.draw_cards(self.owner, self.number)
        self.detail = f'{self.owner.name} 抽 {len(drawn)} 张'
        gm.log(self.detail)
        return [{'type': 'draw', 'player': self.owner, 'cards': drawn}]


class ScoreEffect(Effect):
    """加分效果（RULES §6.1 加分 / §6.2 组合技加分）"""

    kind = 'score'

    def __init__(self, player, amount: int, reason: str = '基础加分', source_cards=None):
        super().__init__(owner=player, source_cards=source_cards)
        self.amount = amount
        self.reason = reason
        self.label = f'{reason} +{amount}'

    def apply(self, gm):
        if self.amount <= 0:
            self.resolved = True
            return []
        self.owner.score += self.amount
        self.detail = f'{self.owner.name} {self.reason} +{self.amount} 分（共 {self.owner.score}）'
        gm.log(self.detail)
        return [{'type': 'score', 'player': self.owner, 'amount': self.amount}]


class DiscardEffect(Effect):
    """弃牌效果：目标玩家弃掉若干张手牌（弃牌进入 FIELD）"""

    kind = 'discard'

    def __init__(self, player, number: int = 1, source_cards=None):
        super().__init__(owner=player, source_cards=source_cards)
        self.number = number
        self.label = f'弃 {number} 张'

    def apply(self, gm):
        picked = gm.request_discard(self.owner, self.number)
        self.detail = f'{self.owner.name} 弃 {len(picked)} 张'
        gm.log(self.detail)
        return [{'type': 'discard', 'player': self.owner, 'cards': picked}]


class InterruptEffect(Effect):
    """打断效果（RULES §6.1）：无效化连锁栈中上一个基础效果。

    优先级最高，因此它在一次出牌中总是最先压栈 → 最后结算之前先被弹出。
    """

    kind = 'interrupt'
    label = '打断'

    def __init__(self, owner, source_cards=None, prev_sum: int = 0):
        super().__init__(owner=owner, source_cards=source_cards)
        self.prev_sum = prev_sum

    def apply(self, gm):
        victim = gm.find_interrupt_target(self.owner)
        if victim is None:
            self.detail = f'{self.owner.name} 打断失败（无可无效化的效果）'
            gm.log(self.detail)
            return [{'type': 'interrupt', 'player': self.owner, 'target': None}]
        victim.negate(gm)
        self.detail = f'{self.owner.name} 打断 {victim.owner.name} 的【{victim.label}】'
        return [{'type': 'interrupt', 'player': self.owner, 'target': victim.owner}]


class ChainPlay:
    """一次出牌（当前回合玩家的主动出牌，或他人的连锁宣言）"""

    def __init__(self, player, cards, combo, is_chain: bool = False, chain_of=None):
        self.player = player
        self.cards = list(cards)
        self.combo = combo
        self.is_chain = is_chain
        self.chain_of = chain_of          # 它所连锁的那一手
        self.sum = sum(int(c.rank) for c in self.cards)
        self.effects: list[Effect] = []   # 本次出牌产生的全部效果

    @property
    def label(self):
        name = enums.COMBO_CN[self.combo] if self.combo is not None else '普通出牌'
        return ('连锁·' if self.is_chain else '') + name

    def to_dict(self) -> dict:
        return {
            'player': self.player.name,
            'faction': str(self.player.faction),
            'cards': [c.to_dict() for c in self.cards],
            'combo': str(self.combo) if self.combo else None,
            'combo_cn': enums.COMBO_CN[self.combo] if self.combo else '普通出牌',
            'is_chain': self.is_chain,
            'sum': self.sum,
            'label': self.label,
        }

    def __repr__(self):
        return f'<ChainPlay {self.player.name} {self.label} {len(self.cards)}张>'


# ---------------------------------------------------------------- 效果工厂
COMBO_EFFECTS = {
    enums.ComboType.SUIT_PAIR: (1, 0, 0, False),
    enums.ComboType.SUIT_TRIPLE: (2, 1, 0, False),
    enums.ComboType.SUIT_FLUSH: (3, 3, 0, False),
    enums.ComboType.FOUR_SEASONS: (0, 2, 0, False),
    enums.ComboType.RANK_PAIR: (1, 0, 0, False),
    enums.ComboType.RANK_TRIPLE: (2, 1, 0, False),
    enums.ComboType.RANK_QUAD: (3, 3, 0, True),
    enums.ComboType.STRAIGHT_3: (2, 0, 0, False),
    enums.ComboType.STRAIGHT_5: (4, 3, 0, False),
}


def build_combo_effects(combo: enums.ComboType, owner, cards, gm) -> list:
    """按 RULES §6.2 生成一个组合技的全部效果，返回 (effects, 描述列表)"""
    draw_n, score_n, _, others_discard = COMBO_EFFECTS[combo]
    name = enums.COMBO_CN[combo]
    out = []

    # 四条：其他玩家各弃 1 张
    if others_discard:
        for p in gm.players:
            if p is not owner:
                out.append(DiscardEffect(p, 1, source_cards=cards))

    if combo == enums.ComboType.FOUR_SEASONS:
        # 四季：全体玩家各抽 1 张（含自己）
        for p in gm.players:
            out.append(DrawEffect(p, 1, source_cards=cards))
    elif draw_n:
        out.append(DrawEffect(owner, draw_n, source_cards=cards))

    if score_n:
        out.append(ScoreEffect(owner, score_n, reason=f'组合技·{name}', source_cards=cards))

    return out


def combo_effect_summary(combo: enums.ComboType) -> list:
    """返回组合技效果的文本列表（供 UI 提示）"""
    draw_n, score_n, _, others_discard = COMBO_EFFECTS[combo]
    out = []
    if combo == enums.ComboType.FOUR_SEASONS:
        out.append('全体玩家各抽 1 张')
    elif draw_n:
        out.append(f'抽 {draw_n} 张')
    if score_n:
        out.append(f'+{score_n} 分')
    if others_discard:
        out.append('其他玩家各弃 1 张')
    return out
