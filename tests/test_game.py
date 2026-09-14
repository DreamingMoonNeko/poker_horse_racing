"""规则与核心流程测试

运行：.venv\\Scripts\\python.exe -m unittest discover -s tests -v
（只需要标准库，未安装 pygame 也能跑）
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enums
import rules
from Card import Card
from GameMaster import GameError, GameMaster
from controllers import AIController
from controllers.base import Action, PlayerController
from turn import TurnRunner

H, S, D, C = enums.Suit.HEART, enums.Suit.SPADE, enums.Suit.DIAMOND, enums.Suit.CLUB
R = enums.Rank


def cards(*pairs):
    """cards((H, R.THREE), (S, R.THREE)) → [Card, Card]"""
    return [Card(suit, rank, enums.Zone.HAND) for suit, rank in pairs]


def suits_of(card_list):
    return [c.suit for c in card_list]


# ---------------------------------------------------------------- 组合技判定
class TestComboDetection(unittest.TestCase):
    def test_suit_pair(self):
        self.assertEqual(rules.detect_combo(cards((H, R.THREE), (H, R.SEVEN))),
                         enums.ComboType.SUIT_PAIR)

    def test_suit_triple(self):
        self.assertEqual(rules.detect_combo(cards((D, R.TWO), (D, R.FIVE), (D, R.KING))),
                         enums.ComboType.SUIT_TRIPLE)

    def test_suit_flush(self):
        hand = cards((C, R.TWO), (C, R.FOUR), (C, R.SIX), (C, R.NINE), (C, R.JACK))
        self.assertEqual(rules.detect_combo(hand), enums.ComboType.SUIT_FLUSH)

    def test_four_seasons(self):
        hand = cards((H, R.THREE), (S, R.SEVEN), (D, R.KING), (C, R.ACE))
        self.assertEqual(rules.detect_combo(hand), enums.ComboType.FOUR_SEASONS)

    def test_rank_pair_triple_quad(self):
        self.assertEqual(rules.detect_combo(cards((H, R.THREE), (S, R.THREE))),
                         enums.ComboType.RANK_PAIR)
        self.assertEqual(rules.detect_combo(cards((H, R.THREE), (S, R.THREE), (D, R.THREE))),
                         enums.ComboType.RANK_TRIPLE)
        self.assertEqual(rules.detect_combo(cards((H, R.THREE), (S, R.THREE),
                                                  (D, R.THREE), (C, R.THREE))),
                         enums.ComboType.RANK_QUAD)

    def test_straight(self):
        self.assertEqual(rules.detect_combo(cards((H, R.THREE), (S, R.FOUR), (D, R.FIVE))),
                         enums.ComboType.STRAIGHT_3)
        hand = cards((H, R.THREE), (S, R.FOUR), (D, R.FIVE), (C, R.SIX), (H, R.SEVEN))
        self.assertEqual(rules.detect_combo(hand), enums.ComboType.STRAIGHT_5)

    def test_straight_with_ace_low(self):
        """A 可以当 1，A23 也是顺子"""
        self.assertEqual(rules.detect_combo(cards((H, R.ACE), (S, R.TWO), (D, R.THREE))),
                         enums.ComboType.STRAIGHT_3)
        self.assertEqual(rules.detect_combo(cards((H, R.ACE), (S, R.TWO), (D, R.THREE),
                                                  (C, R.FOUR), (H, R.FIVE))),
                         enums.ComboType.STRAIGHT_5)

    def test_straight_with_ace_high(self):
        self.assertEqual(rules.detect_combo(cards((H, R.QUEEN), (S, R.KING), (D, R.ACE))),
                         enums.ComboType.STRAIGHT_3)

    def test_not_straight_when_gap(self):
        self.assertIsNone(rules.detect_combo(cards((H, R.THREE), (S, R.FIVE), (D, R.SIX))))

    def test_single_card_is_not_combo(self):
        self.assertIsNone(rules.detect_combo(cards((H, R.THREE))))
        self.assertFalse(rules.is_combo(cards((H, R.THREE))))

    def test_mixed_junk_is_not_combo(self):
        hand = cards((H, R.THREE), (S, R.SEVEN), (D, R.KING))
        self.assertIsNone(rules.detect_combo(hand))

    def test_points_sum_counts_ace_as_14(self):
        self.assertEqual(rules.points_sum(cards((H, R.THREE), (S, R.SEVEN))), 10)
        self.assertEqual(rules.points_sum(cards((H, R.ACE), (S, R.TWO))), 16)


# ---------------------------------------------------------------- 连锁条件
class TestChainConditions(unittest.TestCase):
    def test_same_suit(self):
        prev = cards((H, R.THREE), (H, R.SEVEN))
        chain = cards((H, R.FIVE), (H, R.NINE))
        ok, why = rules.can_chain_detailed(chain, prev)
        self.assertTrue(ok)
        self.assertEqual(why, '花色相同')

    def test_opposite_color(self):
        prev = cards((H, R.THREE))
        chain = cards((S, R.TWO))
        ok, why = rules.can_chain_detailed(chain, prev)
        self.assertTrue(ok)
        self.assertEqual(why, '花色相反')

    def test_equal_sum(self):
        prev = cards((H, R.THREE), (H, R.SEVEN))      # 10 分
        chain = cards((S, R.FIVE), (C, R.FIVE))       # 10 分（点数对子）
        self.assertEqual(rules.points_sum(chain), rules.points_sum(prev))
        ok, _ = rules.can_chain_detailed(chain, prev)
        self.assertTrue(ok)

    def test_equal_sum_single_cards(self):
        prev = cards((H, R.TEN))                      # 10 分
        chain = cards((S, R.KING))                    # 13 分，黑对红 → 花色相反
        ok, why = rules.can_chain_detailed(chain, prev)
        self.assertTrue(ok)
        self.assertEqual(why, '花色相反')

    def test_greater_sum(self):
        prev = cards((H, R.THREE))                    # 3
        chain = cards((H, R.FOUR))                    # 4
        ok, why = rules.can_chain_detailed(chain, prev)
        self.assertTrue(ok)
        self.assertIn(why, ('花色相同', '点数之和更大'))

    def test_rejects_smaller_irrelevant_combo(self):
        prev = cards((H, R.KING), (H, R.QUEEN))       # 25
        chain = cards((S, R.TWO), (C, R.THREE))       # 5，花色不相关
        ok, _ = rules.can_chain_detailed(chain, prev)
        self.assertFalse(ok)

    def test_combo_requires_combo(self):
        """上一手是组合技时，连锁也必须是组合技"""
        prev = cards((H, R.THREE), (H, R.SEVEN))
        chain = [Card(H, R.TWO, enums.Zone.HAND)]     # 单张，点数更小
        self.assertFalse(rules.can_chain(chain, prev))
        # 单张 A（14）符合「点数之和更大」但上一手是组合技 → 仍拒绝
        chain_ace = [Card(H, R.ACE, enums.Zone.HAND)]
        self.assertFalse(rules.can_chain(chain_ace, prev))

    def test_find_chains_on_hand(self):
        hand = cards((H, R.FIVE), (H, R.NINE), (S, R.TWO), (C, R.KING))
        prev = cards((H, R.THREE), (H, R.SEVEN))
        options = rules.find_chains(hand, prev)
        self.assertTrue(options)
        for option_cards, combo in options:
            self.assertTrue(rules.can_chain(option_cards, prev))
            self.assertIsNotNone(combo)


# ---------------------------------------------------------------- 打断判定
class TestInterrupt(unittest.TestCase):
    def test_interrupt_requires_other_turn(self):
        # 黑桃玩家在红桃玩家回合打出红桃牌，点数之和更大
        played = cards((H, R.KING), (H, R.QUEEN))
        self.assertTrue(rules.is_interrupt(played, S, H, False, prev_sum=3))
        # 自己回合不算打断
        self.assertFalse(rules.is_interrupt(played, S, H, True, prev_sum=3))
        # 打的是自己的阵营花色不算打断
        self.assertFalse(rules.is_interrupt(cards((S, R.KING)), S, H, False, prev_sum=3))
        # 点数之和不够大不算打断
        self.assertFalse(rules.is_interrupt(cards((H, R.TWO)), S, H, False, prev_sum=25))


# ---------------------------------------------------------------- 对局流程
class Dummy(PlayerController):
    """可编程控制器：按剧本返回行动"""

    kind = 'dummy'

    def __init__(self, faction, script=None):
        super().__init__(faction)
        self.script = list(script or [])
        self.chain_script = []
        self.discards = []
        self.calls = []

    def choose_action(self, gm, player):
        self.calls.append('action')
        if self.script:
            return self.script.pop(0)
        return Action.end()

    def wants_chain(self, gm, player):
        return bool(self.chain_script) and not player.chained_this_turn

    def choose_chain(self, gm, player):
        if self.chain_script:
            return self.chain_script.pop(0), None
        return None, None

    def choose_discard(self, gm, player, number):
        picked = list(player.hand)[:number]
        self.discards.append(picked)
        return picked


def make_gm(script_by_suit=None, seed=5, target=30):
    script_by_suit = script_by_suit or {}
    controllers = {}
    for suit in enums.Suit:
        controllers[suit] = Dummy(suit, script_by_suit.get(suit, []))
    gm = GameMaster(controllers=controllers, seed=seed, target_score=target)
    gm.setup()
    return gm


class TestGameFlow(unittest.TestCase):
    def test_setup_deals_seven_cards(self):
        gm = make_gm()
        for p in gm.players:
            self.assertEqual(len(p.hand), 7)
        self.assertEqual(len(gm.draw_pile), 52 - 28)
        self.assertEqual(gm.round, 1)
        self.assertEqual(gm.phase, enums.Phase.DRAW_PHASE)
        self.assertTrue(gm.current_player().my_turn)

    def test_begin_turn_draws_two_and_moves_to_play(self):
        gm = make_gm()
        player = gm.current_player()
        before = len(player.hand)
        drawn = gm.begin_turn_draw()
        self.assertEqual(len(drawn), 2)
        self.assertEqual(len(player.hand), before + 2)
        self.assertEqual(gm.phase, enums.Phase.PLAY_PHASE)

    def test_deck_exhaustion_recycles_field(self):
        gm = make_gm()
        player = gm.current_player()
        # 把抽牌堆的牌全部塞进 FIELD，模拟牌库耗尽
        moved = 0
        while gm.draw_pile.cards:
            card = gm.draw_pile.draw_many(1)[0]
            gm.field.add(card)
            card.change_zone(enums.Zone.FIELD)
            moved += 1
        self.assertEqual(len(gm.draw_pile), 0)
        self.assertEqual(len(gm.field), moved)
        drawn = gm.draw_cards(player, 3)
        # 抽牌堆空了 → 把 FIELD 洗回抽牌堆 → 重新抽到 3 张
        self.assertEqual(len(drawn), 3)
        self.assertEqual(len(gm.field), 0)
        self.assertEqual(len(gm.draw_pile), moved - 3)
        self.assertTrue(any('洗回抽牌堆' in line for line in gm.events))

    def test_both_piles_empty_draws_nothing(self):
        gm = make_gm()
        player = gm.current_player()
        gm.field.clear()
        gm.draw_pile.cards.clear()
        self.assertEqual(gm.draw_cards(player, 5), [])

    def test_play_requires_play_phase(self):
        gm = make_gm()
        player = gm.current_player()
        gm.phase = enums.Phase.DRAW_PHASE
        with self.assertRaises(GameError):
            gm.play_cards(player, list(player.hand)[:1])

    def test_play_rejects_cards_not_in_hand(self):
        gm = make_gm()
        gm.begin_turn_draw()
        player = gm.current_player()
        foreign = Card(H, R.TWO, enums.Zone.HAND)
        with self.assertRaises(GameError):
            gm.play_cards(player, [foreign])

    def test_non_active_player_must_chain(self):
        gm = make_gm()
        gm.begin_turn_draw()
        other = [p for p in gm.players if p is not gm.current_player()][0]
        with self.assertRaises(GameError):
            gm.play_cards(other, list(other.hand)[:1])

    def test_faction_card_scores(self):
        gm = make_gm()
        gm.begin_turn_draw()
        player = gm.current_player()
        # 不假设发牌一定给到阵营花色，自己塞一张进去
        faction_cards = [c for c in player.hand if c.suit == player.faction]
        if not faction_cards:
            extra = Card(player.faction, R.FIVE, enums.Zone.HAND)
            gm.move_cards([extra], enums.Zone.HAND, player)
            faction_cards = [extra]
        gm.play_cards(player, [faction_cards[0]])
        gm.resolve_chain()
        self.assertEqual(player.score, 1)

    def test_off_faction_card_scores_nothing(self):
        gm = make_gm()
        gm.begin_turn_draw()
        player = gm.current_player()
        off = [c for c in player.hand if c.suit != player.faction][0]
        gm.play_cards(player, [off])
        gm.resolve_chain()
        self.assertEqual(player.score, 0)

    def test_combo_pair_draws_card(self):
        gm = make_gm()
        gm.begin_turn_draw()
        player = gm.current_player()
        # 手动构造一对同点数的牌放进手牌
        pair = [Card(S, R.FIVE, enums.Zone.HAND), Card(D, R.FIVE, enums.Zone.HAND)]
        gm.move_cards(pair, enums.Zone.HAND, player)
        before = len(player.hand)
        gm.play_cards(player, pair)
        gm.resolve_chain()
        # 出掉 2 张 → 抽 1 张
        self.assertEqual(len(player.hand), before - 2 + 1)

    def test_chain_is_lifo_and_resolves_all_effects(self):
        """先出牌者先入栈、后出牌者后入栈，结算时后者先结算"""
        order = []

        class Recorder(AIController):
            def apply(self, *a, **k):  # pragma: no cover - 占位
                pass

        gm = make_gm()
        gm.begin_turn_draw()
        active = gm.current_player()
        other = [p for p in gm.players if p is not active][0]

        # 双方各打一张，用同花色保证可以连锁
        card_a = Card(active.faction, R.THREE, enums.Zone.HAND)
        gm.move_cards([card_a], enums.Zone.HAND, active)
        card_b = Card(active.faction, R.FOUR, enums.Zone.HAND)
        gm.move_cards([card_b], enums.Zone.HAND, other)

        gm.play_cards(active, [card_a])
        self.assertTrue(gm.chain_open)
        gm.play_cards(other, [card_b])
        self.assertEqual(len(gm.chain_stack), 2)

        # 手动标记结算顺序
        stack_before = list(gm.chain_stack)
        gm.resolve_chain()
        self.assertEqual(gm.chain_stack, [])
        # 栈顶（后入栈的连锁）应当先被结算：它是 other 的那一手
        self.assertIs(stack_before[-1].owner, other)
        # 每个效果都被结算（resolve）或被无效化（negate），不留悬挂
        self.assertTrue(all(e.resolved or e.negated for e in stack_before))
        self.assertTrue(other.chained_this_turn)

    def test_interrupt_negates_previous_score(self):
        gm = make_gm()
        gm.begin_turn_draw()
        active = gm.current_player()          # 回合玩家
        other = [p for p in gm.players if p is not active][0]

        # 回合玩家打出 2 张阵营花色 → 应得 2 分
        a1 = Card(active.faction, R.TWO, enums.Zone.HAND)
        a2 = Card(active.faction, R.THREE, enums.Zone.HAND)
        gm.move_cards([a1, a2], enums.Zone.HAND, active)
        gm.play_cards(active, [a1, a2])

        # 对手打出回合玩家阵营花色的大牌 → 触发打断
        b1 = Card(active.faction, R.KING, enums.Zone.HAND)
        b2 = Card(active.faction, R.QUEEN, enums.Zone.HAND)
        gm.move_cards([b1, b2], enums.Zone.HAND, other)
        prev_sum = gm.active_play.sum
        self.assertGreater(rules.points_sum([b1, b2]), prev_sum)
        gm.play_cards(other, [b1, b2])

        self.assertTrue(any(e.kind == 'interrupt' for e in gm.chain_stack))
        gm.resolve_chain()
        # 加分被打断 → 回合玩家 0 分
        self.assertEqual(active.score, 0)

    def test_scores_only_on_own_turn(self):
        """连锁别人时打自己的阵营花色不加分（只有自己回合才加分）"""
        gm = make_gm()
        gm.begin_turn_draw()
        active = gm.current_player()
        other = [p for p in gm.players if p is not active][0]

        a1 = Card(active.faction, R.TWO, enums.Zone.HAND)
        gm.move_cards([a1], enums.Zone.HAND, active)
        gm.play_cards(active, [a1])

        b1 = Card(other.faction, R.KING, enums.Zone.HAND)
        gm.move_cards([b1], enums.Zone.HAND, other)
        gm.play_cards(other, [b1])
        gm.resolve_chain()
        self.assertEqual(other.score, 0)

    def test_chain_limited_once_per_turn(self):
        gm = make_gm()
        gm.begin_turn_draw()
        active = gm.current_player()
        other = [p for p in gm.players if p is not active][0]

        a1 = Card(active.faction, R.TWO, enums.Zone.HAND)
        gm.move_cards([a1], enums.Zone.HAND, active)
        gm.play_cards(active, [a1])

        b1 = Card(active.faction, R.FOUR, enums.Zone.HAND)
        gm.move_cards([b1], enums.Zone.HAND, other)
        gm.play_cards(other, [b1])
        gm.resolve_chain()
        self.assertTrue(other.chained_this_turn)

        # 同一个回合内再次连锁应被拒绝
        a2 = Card(active.faction, R.SIX, enums.Zone.HAND)
        gm.move_cards([a2], enums.Zone.HAND, active)
        gm.active_play = None
        gm.chain_open = False
        gm.play_cards(active, [a2])
        b2 = Card(active.faction, R.SEVEN, enums.Zone.HAND)
        gm.move_cards([b2], enums.Zone.HAND, other)
        with self.assertRaises(GameError):
            gm.play_cards(other, [b2])

    def test_end_phase_discards_to_hand_limit(self):
        gm = make_gm()
        player = gm.current_player()
        # 强行把手牌堆到 16 张
        extra = [Card(H, R.TWO, enums.Zone.HAND) for _ in range(20)]
        gm.move_cards(extra, enums.Zone.HAND, player)
        self.assertGreater(len(player.hand), 13)
        gm._run_end_phase()
        self.assertLessEqual(len(player.hand), 13)

    def test_victory_at_target_score(self):
        gm = make_gm(target=3)
        gm.begin_turn_draw()
        player = gm.current_player()
        player.score = 3
        gm.check_victory()
        self.assertTrue(gm.game_over)
        self.assertIs(gm.winner, player)

    def test_card_count_conserved_through_full_game(self):
        controllers = {s: AIController(s, seed=i) for i, s in enumerate(enums.Suit)}
        gm = GameMaster(controllers=controllers, seed=99, target_score=30)
        gm.setup()
        runner = TurnRunner(gm)
        steps = 0
        while not gm.game_over and steps < 8000:
            runner.step()
            steps += 1
            total = len(gm.draw_pile) + len(gm.field) + sum(len(p.hand) for p in gm.players)
            self.assertEqual(total, 52, f'第 {steps} 步卡牌总数不守恒：{total}')
        self.assertTrue(gm.game_over, 'AI 对局应当在步数上限内结束')

    def test_draw_when_piles_exhausted_does_not_loop(self):
        gm = make_gm()
        player = gm.current_player()
        gm.field.clear()
        gm.draw_pile.cards.clear()
        self.assertEqual(gm.draw_cards(player, 5), [])


# ---------------------------------------------------------------- 回合驱动器
class TestTurnRunner(unittest.TestCase):
    def test_ai_full_game_reaches_victory(self):
        for seed in (1, 2, 3):
            controllers = {s: AIController(s, seed=seed * 10 + i)
                           for i, s in enumerate(enums.Suit)}
            gm = GameMaster(controllers=controllers, seed=seed, target_score=30)
            gm.setup()
            runner = TurnRunner(gm)
            steps = 0
            while not gm.game_over and steps < 8000:
                runner.step()
                steps += 1
            self.assertTrue(gm.game_over, f'seed={seed} 未能结束对局')
            self.assertIsNotNone(gm.winner)
            self.assertGreaterEqual(gm.winner.score, 30)

    def test_human_waiting_pauses_runner(self):
        from controllers import HumanController
        controllers = {s: HumanController(s) for s in enums.Suit}
        gm = GameMaster(controllers=controllers, seed=4)
        gm.setup()
        runner = TurnRunner(gm)
        runner.step()   # 抽牌阶段
        result = runner.step()   # 出牌阶段 → 等待人类输入
        self.assertEqual(result['stage'], 'waiting')
        self.assertTrue(runner.is_waiting_for_input())

        # 提交决策后应当继续推进
        human = controllers[gm.current_player().faction]
        human.submit_end_turn()
        result = runner.step()
        self.assertIn(result['stage'], ('turn_end', 'drew', 'played'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
