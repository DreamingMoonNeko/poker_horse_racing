from enum import Enum, IntEnum, StrEnum


# contains the suits of the cards
class Suit(StrEnum):
    HEART = 'heart'      # 红桃
    SPADE = 'spade'      # 黑桃
    DIAMOND = 'diamond'  # 方片
    CLUB = 'club'        # 梅花


# 花色颜色：红桃/方片为红，黑桃/梅花为黑。连锁条件「花色相反」依赖此分组。
SUIT_COLOR = {
    Suit.HEART: 'red',
    Suit.DIAMOND: 'red',
    Suit.SPADE: 'black',
    Suit.CLUB: 'black',
}

# 花色显示用符号
SUIT_SYMBOL = {
    Suit.HEART: '\u2665',
    Suit.DIAMOND: '\u2666',
    Suit.SPADE: '\u2660',
    Suit.CLUB: '\u2663',
}

SUIT_CN = {
    Suit.HEART: '红桃',
    Suit.DIAMOND: '方片',
    Suit.SPADE: '黑桃',
    Suit.CLUB: '梅花',
}


def suit_color(suit: 'Suit') -> str:
    return SUIT_COLOR[suit]


def opposite_color(a: 'Suit', b: 'Suit') -> bool:
    """两张牌花色颜色相反（红 vs 黑）"""
    return SUIT_COLOR[a] != SUIT_COLOR[b]


# 暂时没有大小王，将来特殊处理
# IntEnum支持值比较，通过更改枚举的值可以改变“谁更大”的规则
class Rank(IntEnum):
    # Ace is greater than King, so it equals to 14
    ACE = 14
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13


RANK_SYMBOL = {
    Rank.ACE: 'A',
    Rank.TWO: '2',
    Rank.THREE: '3',
    Rank.FOUR: '4',
    Rank.FIVE: '5',
    Rank.SIX: '6',
    Rank.SEVEN: '7',
    Rank.EIGHT: '8',
    Rank.NINE: '9',
    Rank.TEN: '10',
    Rank.JACK: 'J',
    Rank.QUEEN: 'Q',
    Rank.KING: 'K',
}


class Zone(Enum):
    DRAW_PILE = 'draw_pile'
    FIELD = 'field'
    HAND = 'hand'


# 用IntEnum让phase按值循环遍历
class Phase(IntEnum):
    DRAW_PHASE = 0
    PLAY_PHASE = 1
    END_PHASE = 2


class ComboType(Enum):
    """组合技类型（RULES §5.2 / §6.2）"""

    # 花色组合
    SUIT_PAIR = 'suit_pair'        # 同花色 2 张 · 对子
    SUIT_TRIPLE = 'suit_triple'    # 同花色 3 张 · 三条
    SUIT_FLUSH = 'suit_flush'      # 同花色 5 张 · 同花
    FOUR_SEASONS = 'four_seasons'  # 四花色各 1 张 · 四季
    # 点数组合
    RANK_PAIR = 'rank_pair'        # 同点数 2 张 · 对子
    RANK_TRIPLE = 'rank_triple'    # 同点数 3 张 · 三条
    RANK_QUAD = 'rank_quad'        # 同点数 4 张 · 四条
    STRAIGHT_3 = 'straight_3'      # 连续 3 张 · 顺子
    STRAIGHT_5 = 'straight_5'      # 连续 5 张 · 长顺


# 组合技展示名
COMBO_CN = {
    ComboType.SUIT_PAIR: '同花对子',
    ComboType.SUIT_TRIPLE: '同花三条',
    ComboType.SUIT_FLUSH: '同花',
    ComboType.FOUR_SEASONS: '四季',
    ComboType.RANK_PAIR: '对子',
    ComboType.RANK_TRIPLE: '三条',
    ComboType.RANK_QUAD: '四条',
    ComboType.STRAIGHT_3: '顺子',
    ComboType.STRAIGHT_5: '长顺',
}

# 组合技效果文本（用于界面提示）
COMBO_EFFECT_TEXT = {
    ComboType.SUIT_PAIR: '抽 1 张',
    ComboType.SUIT_TRIPLE: '抽 2 张，+1 分',
    ComboType.SUIT_FLUSH: '抽 3 张，+3 分',
    ComboType.FOUR_SEASONS: '全体各抽 1 张，自己 +2 分',
    ComboType.RANK_PAIR: '抽 1 张',
    ComboType.RANK_TRIPLE: '抽 2 张，+1 分',
    ComboType.RANK_QUAD: '抽 3 张，+3 分，其他玩家各弃 1 张',
    ComboType.STRAIGHT_3: '抽 2 张',
    ComboType.STRAIGHT_5: '抽 4 张，+3 分',
}
