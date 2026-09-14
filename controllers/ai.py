"""AI 控制器：用于演示与自动对局（也可当作联机前的占位对手）"""

import random
from itertools import combinations

import enums
import rules
from controllers.base import Action, PlayerController
from effects import COMBO_EFFECTS


class AIController(PlayerController):
    kind = 'ai'

    def __init__(self, faction: enums.Suit = None, name: str = None, seed: int = None,
                 think: bool = True):
        super().__init__(faction, name or 'AI')
        self.rng = random.Random(seed)
        self.think = think  # 仅作标记：UI 可据此显示「AI 思考中」

    # ------------------------------------------------------------ 工具
    def _keep_score(self, card, player) -> int:
        """牌对自己的价值：阵营花色更值得留在手里（可用于加分）"""
        return 2 if card.suit == player.faction else 0

    def _evaluate(self, gm, player, cards, combo) -> int:
        """给一手牌打分，越高越优先出"""
        score = 0
        faction_cards = [c for c in cards if c.suit == player.faction]
        score += 10 * len(faction_cards)              # 阵营花色加分
        if combo is not None:
            score += 14                               # 组合技优先
            draw_n, score_n, _, _ = COMBO_EFFECTS[combo]
            score += 3 * draw_n + 5 * score_n
        # 出牌越少越好，避免一次丢掉太多资源
        score -= 3 * len(cards)
        # 不要拆散可能凑成组合的牌
        score -= sum(self._keep_score(c, player) for c in cards if c.suit != player.faction)
        return score

    def _candidates(self, gm, player, as_chain: bool):
        hand = list(player.hand)
        prev = gm.pending_previous_play() if as_chain else None
        prev_combo = prev['combo'] if prev else None
        require_combo = bool(prev_combo) if as_chain else False
        sizes = [2, 3, 4, 5] if require_combo else [1, 2, 3, 4, 5]
        out = []
        for size in sizes:
            if size > len(hand):
                continue
            for cards in combinations(hand, size):
                cards = list(cards)
                combo = rules.detect_combo(cards)
                if as_chain:
                    if not rules.can_chain(cards, prev['cards'], prev_combo, combo):
                        continue
                out.append((cards, combo))
        return out

    # ------------------------------------------------------------ 决策
    def choose_action(self, gm, player) -> Action:
        """当前回合：挑选期望值最高的一手牌；没有值得出的牌就结束回合"""
        candidates = self._candidates(gm, player, as_chain=False)
        if not candidates:
            return Action.end()

        scored = [(self._evaluate(gm, player, cards, combo), cards, combo)
                  for cards, combo in candidates]
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_cards, best_combo = scored[0]

        # 只有阵营花色牌 / 组合技才值得出，否则保留手牌
        has_faction = any(c.suit == player.faction for c in best_cards)
        if best_combo is None and not has_faction:
            # 完全出不了有用的牌时，偶尔换掉一张最没用的（避免完全不作为）
            if self.rng.random() < 0.5:
                return Action.end()
        return Action.play(best_cards, combo=best_combo, reason='AI 出牌')

    def wants_chain(self, gm, player) -> bool:
        prev = gm.pending_previous_play()
        if prev is None or player.chained_this_turn:
            return False
        options = self._chain_options(gm, player)
        return bool(options)

    def _chain_options(self, gm, player):
        prev = gm.pending_previous_play()
        if prev is None:
            return []
        out = []
        for cards, combo in self._candidates(gm, player, as_chain=True):
            # 连锁只做「有收益」的事：组合技（抽牌/加分）或打断当前回合玩家
            beneficial = combo is not None
            if not beneficial:
                beneficial = rules.is_interrupt(
                    cards, player.faction, gm.current_player().faction,
                    player.my_turn, prev['sum'])
            if beneficial:
                out.append((cards, combo))
        out.sort(key=lambda item: self._evaluate(gm, player, item[0], item[1]), reverse=True)
        return out

    def choose_chain(self, gm, player):
        options = self._chain_options(gm, player)
        if not options:
            return None, None
        cards, combo = options[0]
        return cards, combo

    def choose_discard(self, gm, player, number: int) -> list:
        """弃牌：优先弃掉非阵营花色中点数最小的牌"""
        ordered = sorted(player.hand, key=lambda c: (c.suit == player.faction, int(c.rank)))
        return ordered[:number]

    def notify(self, gm, event: dict):
        pass
