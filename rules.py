"""出牌规则引擎（RULES §5 / §6.1）

纯函数模块：不持有任何游戏状态，只负责判定「这手牌是什么组合技」、
「点数之和是多少」、「这一手能否连锁上一手」。GameMaster 负责调用它。
"""

from collections import Counter
from itertools import combinations

import enums

RANK_BASE = {r: int(r) for r in enums.Rank}
ACE_LOW = 1

FOUR_SEASONS_SUITS = set(enums.Suit)


# ---------------------------------------------------------------- 基础工具
def rank_values(cards) -> list:
    return [RANK_BASE[c.rank] for c in cards]


def points_sum(cards) -> int:
    """点数之和。A 记为 14（RULES §2.1）"""
    return sum(rank_values(cards))


def suits_of(cards) -> set:
    return {c.suit for c in cards}


def _sequences(size: int) -> set:
    """返回 size 张「连续点数」的所有合法点数集合。

    A 可作 14，也可作 1（即 A23 / A2345 这类小顺子），因此从 1 开始枚举。
    """
    return {
        frozenset(range(start, start + size))
        for start in range(ACE_LOW, enums.Rank.ACE - size + 2)
    }


_SEQ_CACHE: dict = {}


def is_straight(cards, size: int) -> bool:
    """size 张牌点数互不相同且连续（A 可当 1 或 14）"""
    if len(cards) != size:
        return False
    vals = rank_values(cards)
    if len(set(vals)) != size:
        return False
    if size not in _SEQ_CACHE:
        _SEQ_CACHE[size] = _sequences(size)
    if frozenset(vals) in _SEQ_CACHE[size]:
        return True
    # A 当 1：把 14 换成 1 再试一次（A23 / A2345）
    if enums.Rank.ACE.value in vals:
        low = frozenset(ACE_LOW if v == enums.Rank.ACE.value else v for v in vals)
        return low in _SEQ_CACHE[size]
    return False


# ---------------------------------------------------------------- 组合技判定
def _suit_group(cards, size: int) -> bool:
    return len(cards) == size and len(suits_of(cards)) == 1


def _rank_counts(cards) -> Counter:
    return Counter(RANK_BASE[c.rank] for c in cards)


def _same_rank(cards, size: int) -> bool:
    return len(cards) == size and len(_rank_counts(cards)) == 1


def _four_seasons(cards) -> bool:
    return len(cards) == 4 and suits_of(cards) == FOUR_SEASONS_SUITS


def detect_combo(cards) -> enums.ComboType | None:
    """判定这手牌属于哪种组合技，不属于任何组合技返回 None。

    判定顺序：先点数组合（对子/三条/四条/顺子），再花色组合
    （同花对子/同花三条/同花/四季）。四条（四种花色同点数）优先于四季，
    否则一手四条会被误判成四季。
    """
    cards = list(cards)
    n = len(cards)

    # 点数组合优先
    if n == 2 and _same_rank(cards, 2):
        return enums.ComboType.RANK_PAIR
    if n == 3 and _same_rank(cards, 3):
        return enums.ComboType.RANK_TRIPLE
    if n == 4 and _same_rank(cards, 4):
        return enums.ComboType.RANK_QUAD
    if n == 3 and is_straight(cards, 3):
        return enums.ComboType.STRAIGHT_3
    if n == 5 and is_straight(cards, 5):
        return enums.ComboType.STRAIGHT_5

    # 花色组合
    if n == 5 and _suit_group(cards, 5):
        return enums.ComboType.SUIT_FLUSH
    if n == 3 and _suit_group(cards, 3):
        return enums.ComboType.SUIT_TRIPLE
    if n == 2 and _suit_group(cards, 2):
        return enums.ComboType.SUIT_PAIR
    if n == 4 and _four_seasons(cards):
        return enums.ComboType.FOUR_SEASONS
    return None


def is_combo(cards) -> bool:
    return detect_combo(cards) is not None


def combo_label(cards) -> str:
    combo = detect_combo(cards)
    return enums.COMBO_CN[combo] if combo else '普通出牌'


def combo_effect_text(cards) -> str:
    combo = detect_combo(cards)
    return enums.COMBO_EFFECT_TEXT[combo] if combo else '无附加效果'


# ---------------------------------------------------------------- 连锁判定
def can_chain(chain_cards, prev_cards, prev_combo: enums.ComboType = None,
              chain_combo: enums.ComboType = None) -> bool:
    """能否用 chain_cards 连锁 prev_cards（RULES §5.3，四条满足其一即可）

    1. 花色相同：与上一手牌的花色组成相同组合
    2. 花色相反：与上一手牌的花色组成相反组合（红 vs 黑）
    3. 点数之和相同
    4. 点数之和更大
    """
    chain_cards = list(chain_cards)
    prev_cards = list(prev_cards)
    if not chain_cards or not prev_cards:
        return False

    if chain_combo is None:
        chain_combo = detect_combo(chain_cards)
    if prev_combo is None:
        prev_combo = detect_combo(prev_cards)

    # 上一手是组合技时，本手也必须是组合技
    if prev_combo is not None and chain_combo is None:
        return False

    # 条件 1：花色相同（连锁牌花色集合 ⊆ 上一手花色集合）
    prev_suits = suits_of(prev_cards)
    chain_suits = suits_of(chain_cards)
    if chain_suits and chain_suits <= prev_suits:
        return True

    # 条件 2：花色相反（红黑相对）
    if chain_suits and prev_suits:
        if all(enums.opposite_color(a, b)
               for a in chain_suits for b in prev_suits):
            return True

    # 条件 3 / 4：点数之和相同或更大
    if points_sum(chain_cards) >= points_sum(prev_cards):
        return True

    return False


def can_chain_detailed(chain_cards, prev_cards) -> tuple:
    """返回 (是否可连锁, 命中的条件文本)"""
    chain_cards = list(chain_cards)
    prev_cards = list(prev_cards)
    if not can_chain(chain_cards, prev_cards):
        return False, '不满足连锁条件'
    prev_suits = suits_of(prev_cards)
    chain_suits = suits_of(chain_cards)
    if chain_suits <= prev_suits:
        return True, '花色相同'
    if all(enums.opposite_color(a, b) for a in chain_suits for b in prev_suits):
        return True, '花色相反'
    if points_sum(chain_cards) == points_sum(prev_cards):
        return True, '点数之和相同'
    return True, '点数之和更大'


# ---------------------------------------------------------------- 打断判定
def is_interrupt(cards, actor_faction: enums.Suit, turn_faction: enums.Suit,
                 is_actor_turn: bool, prev_sum: int) -> bool:
    """RULES §6.1 打断：在他人回合打出「当前回合玩家阵营花色」的牌，
    且这些牌点数之和 > 上一手牌的点数之和。"""
    if is_actor_turn:
        return False
    if turn_faction is None or actor_faction is None:
        return False
    if turn_faction == actor_faction:
        return False
    faction_cards = [c for c in cards if c.suit == turn_faction]
    if not faction_cards:
        return False
    return points_sum(faction_cards) > prev_sum


# ---------------------------------------------------------------- 搜索辅助
def find_plays(hand, max_size: int = 5, require_combo: bool = False) -> list:
    """枚举手牌中所有可出的牌组（用于提示 / AI 决策）。

    返回列表元素为 (cards, combo_type)，按「组合技优先、张数多优先」排序。
    """
    hand = list(hand)
    results = []
    seen = set()
    sizes = [2, 3, 4, 5] if require_combo else [1, 2, 3, 4, 5]
    for size in sizes:
        if size > max_size or size > len(hand):
            continue
        for combo_cards in combinations(hand, size):
            key = tuple(sorted(c.uid for c in combo_cards))
            if key in seen:
                continue
            combo = detect_combo(combo_cards)
            if require_combo and combo is None:
                continue
            seen.add(key)
            results.append((list(combo_cards), combo))
    results.sort(key=lambda item: (item[1] is None, -len(item[0])))
    return results


def find_chains(hand, prev_cards, prev_combo=None) -> list:
    """枚举手牌中所有可连锁的牌组，返回 [(cards, combo_type), ...]"""
    if prev_combo is None:
        prev_combo = detect_combo(prev_cards)
    out = []
    for cards, combo in find_plays(hand, require_combo=prev_combo is not None):
        if can_chain(cards, prev_cards, prev_combo, combo):
            out.append((cards, combo))
    return out
