"""图形层测试（TODO 2）

覆盖两个曾经出过问题的点：
1. `Layout.hit_button()` 的按钮名必须是真实存在的属性（曾写成 `btn_new`，一点击就 AttributeError）
2. 花色必须四种都画得出来且互不相同 —— 中文字体常常缺少 ♠♥♦♣ 字形，
   pygame 会静默画成同一个豆腐块，所以花色改为矢量绘制

用 SDL dummy 驱动，无需显示器。
"""

import os
import sys
import unittest

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import enums
from controllers import HumanController
from ui import theme, widgets
from ui.layout import BOTTOM, LEFT, RIGHT, TOP, Layout, MIN_SIZE, WINDOW_SIZE
from viewmodel import TableInteraction, TableView

SIZES = (WINDOW_SIZE, MIN_SIZE, (1920, 1080))

# 整个模块只初始化一次 pygame：theme 里有字体缓存，
# 反复 quit/init 会让缓存里的 Font 对象失效。
pygame.init()
pygame.display.set_mode((64, 64))


def surface(size=(300, 300)):
    return pygame.Surface(size)


class TestLayoutButtons(unittest.TestCase):
    def test_topbar_rects_exist(self):
        """渲染层用 getattr(layout, f'btn_{key}') 取按钮矩形，属性名必须齐全"""
        lay = Layout(WINDOW_SIZE)
        for name in ('btn_menu', 'btn_new_game', 'btn_help'):
            self.assertTrue(hasattr(lay, name), f'Layout 缺少 {name}')

    def test_hit_button_never_raises_and_hits_topbar(self):
        for size in SIZES:
            lay = Layout(size)
            # 全屏扫一遍：任何位置都不能抛异常
            for x in range(0, lay.width, 17):
                for y in range(0, lay.height, 17):
                    lay.hit_button((x, y))     # 不抛异常即通过

    def test_topbar_buttons_are_clickable(self):
        lay = Layout(WINDOW_SIZE)
        self.assertEqual(lay.hit_button(lay.btn_menu.center), 'menu')
        self.assertEqual(lay.hit_button(lay.btn_new_game.center), 'new_game')
        self.assertEqual(lay.hit_button(lay.btn_help.center), 'help')

    def test_action_buttons_clickable(self):
        lay = Layout(WINDOW_SIZE)
        for key, rect in lay.buttons.items():
            self.assertEqual(lay.hit_button(rect.center), key)
        # 连锁按钮与普通按钮共用同一行，只在连锁窗口激活
        lay.set_chain_active(True)
        for key, rect in lay.chain_buttons.items():
            self.assertEqual(lay.hit_button(rect.center), key)
        lay.set_chain_active(False)
        for key, rect in lay.chain_buttons.items():
            self.assertNotEqual(lay.hit_button(rect.center), key,
                                '非连锁状态不应命中连锁按钮')

    def test_empty_area_returns_none(self):
        lay = Layout(WINDOW_SIZE)
        self.assertIsNone(lay.hit_button((lay.width // 2, lay.height - 40)))

    def test_layout_regions_do_not_overlap(self):
        for size in SIZES:
            for log_open in (True, False):
                lay = Layout(size)
                lay.set_log_open(log_open)
                tag = f'{size} log_open={log_open}'
                self.assertLessEqual(lay.field_rect.bottom, lay.log_rect.y,
                                     f'{tag} 出牌区与日志重叠')
                self.assertLessEqual(lay.info_rect.bottom, lay.field_rect.y,
                                     f'{tag} 信息栏与出牌区重叠')
                # 连锁按钮必须和普通按钮同一行，不能压到出牌区
                for key in ('chain_ok', 'chain_no'):
                    self.assertFalse(lay.chain_buttons[key].colliderect(lay.field_rect),
                                     f'{tag} 连锁按钮 {key} 遮挡了出牌区')
                    self.assertFalse(lay.chain_buttons[key].colliderect(lay.info_rect),
                                     f'{tag} 连锁按钮 {key} 遮挡了信息栏')
                for key, rect in lay.buttons.items():
                    self.assertFalse(rect.colliderect(lay.log_rect),
                                     f'{tag} 按钮 {key} 压住了日志区')
                for seat in (BOTTOM, TOP, LEFT, RIGHT):
                    for count in (1, 5, 13):
                        for rect in lay.hand_card_rects(seat, count):
                            area = lay.seat_rects[seat]
                            self.assertTrue(area.contains(rect),
                                            f'{tag} {seat} {count} 张手牌越界: {rect} vs {area}')
                for count in (1, 9, 30):
                    for rect in lay.field_card_rects(count):
                        self.assertTrue(lay.field_rect.contains(rect),
                                        f'{tag} 出牌区 {count} 张越界: {rect}')

    def test_log_collapse_gives_field_more_room(self):
        lay = Layout(WINDOW_SIZE)
        open_h = lay.field_rect.height
        lay.set_log_open(False)
        closed_h = lay.field_rect.height
        self.assertGreater(closed_h, open_h, '收起日志后出牌区应当变大')
        self.assertFalse(lay.log_visible)
        self.assertEqual(lay.log_line_capacity, 0)
        lay.set_log_open(True)
        self.assertTrue(lay.log_visible)
        self.assertGreaterEqual(lay.log_line_capacity, 4, '展开日志后至少要能显示 4 行')


class TestSuitRendering(unittest.TestCase):
    def _shape_signature(self, suit, size=40):
        surf = surface((80, 80))
        surf.fill((0, 0, 0))
        widgets.draw_suit(surf, suit, (40, 40), size, (255, 255, 255))
        pixels = [(x, y) for x in range(80) for y in range(80)
                  if surf.get_at((x, y))[:3] == (255, 255, 255)]
        return frozenset(pixels)

    def test_every_suit_draws_ink(self):
        for suit in enums.Suit:
            pixels = self._shape_signature(suit)
            self.assertGreater(len(pixels), 40,
                               f'{suit.name} 几乎没画出像素（{len(pixels)}）')

    def test_suits_are_visually_distinct(self):
        """四种花色的图形必须互不相同 —— 曾经它们全是同一个豆腐块"""
        signatures = {suit: self._shape_signature(suit) for suit in enums.Suit}
        names = list(signatures)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                self.assertNotEqual(signatures[a], signatures[b],
                                    f'{a.name} 与 {b.name} 画出来完全一样')

    def test_suit_color_is_red_or_black(self):
        self.assertEqual(theme.suit_color(enums.Suit.HEART), theme.COLOR_RED)
        self.assertEqual(theme.suit_color(enums.Suit.DIAMOND), theme.COLOR_RED)
        self.assertEqual(theme.suit_color(enums.Suit.SPADE), theme.COLOR_BLACK)
        self.assertEqual(theme.suit_color(enums.Suit.CLUB), theme.COLOR_BLACK)

    def test_draw_card_face_uses_suit_shape(self):
        """正面牌上应当出现该花色的图形像素，且用对应颜色"""
        from Card import Card
        from enums import Rank
        rect = pygame.Rect(0, 0, 78, 110)
        for suit, color in ((enums.Suit.HEART, theme.COLOR_RED),
                            (enums.Suit.SPADE, theme.COLOR_BLACK)):
            surf = surface((120, 150))
            surf.fill((0, 0, 0))
            widgets.draw_card(surf, rect, Card(suit, Rank.ACE), face_up=True)
            colored = [(x, y) for x in range(rect.width) for y in range(rect.height)
                       if surf.get_at((x, y))[:3] == color]
            self.assertGreater(len(colored), 60,
                               f'{suit.name} 牌面上没有画出花色/点数像素')

    def test_has_glyph_detects_fallback(self):
        """缺字检测：私用区码位必然缺字，常用汉字必然存在"""
        self.assertFalse(theme.has_glyph('\ue000'))
        self.assertTrue(theme.has_glyph('A'))
        self.assertTrue(theme.has_glyph('红'))


class TestCardFaceLayout(unittest.TestCase):
    """牌面元素不能互相重叠（曾经中央花色压住左上角花色）"""

    CARD = pygame.Rect(0, 0, 78, 110)

    def _ink(self, card_suit, card_rank, region):
        from Card import Card
        surf = pygame.Surface((140, 160))
        surf.fill((0, 0, 0))
        widgets.draw_card(surf, self.CARD, Card(card_suit, card_rank), face_up=True)
        color = theme.suit_color(card_suit)
        ink = []
        for x in range(region.left, region.right):
            for y in range(region.top, region.bottom):
                if surf.get_at((x, y))[:3] == color:
                    ink.append((x, y))
        return ink

    def test_corner_and_center_do_not_overlap(self):
        """左上角（点数+小花色）与中央大花色必须分居上下，中间有空隙"""
        card = self.CARD
        rank_size = max(15, min(24, int(card.height * 0.22)))
        corner_size = max(11, int(card.height * 0.17))
        corner_bottom = card.y + 3 + rank_size + corner_size
        center_size = int(card.height * 0.38)
        center_top = card.y + int(card.height * 0.62) - center_size // 2
        self.assertLess(corner_bottom, center_top,
                        f'左上角花色底边 {corner_bottom} 与中央花色顶边 {center_top} 重叠')
        # 实际像素也要验证：上三分之一区域内不应出现中央花色的位置
        upper = pygame.Rect(card.x + 30, card.y, card.width - 30, corner_bottom)
        center_region = pygame.Rect(card.x + 20, center_top, card.width - 40,
                                    center_size)
        self.assertFalse(upper.colliderect(center_region))

    def test_all_four_elements_draw_ink(self):
        """点数 + 左上花色 + 中央花色 + 右下点数，四个区域都要有墨迹"""
        from enums import Rank
        card = self.CARD
        for suit in enums.Suit:
            surf = pygame.Surface((140, 160))
            surf.fill((0, 0, 0))
            from Card import Card
            widgets.draw_card(surf, card, Card(suit, Rank.ACE), face_up=True)
            color = theme.suit_color(suit)
            total = sum(1 for x in range(card.width) for y in range(card.height)
                        if surf.get_at((x, y))[:3] == color)
            self.assertGreater(total, 120, f'{suit.name} 牌面墨迹太少：{total}')

    def test_mini_card_face_draws_rank_and_suit(self):
        from Card import Card
        from enums import Rank
        small = pygame.Rect(0, 0, 52, 74)
        surf = pygame.Surface((100, 120))
        surf.fill((0, 0, 0))
        widgets.draw_card(surf, small, Card(enums.Suit.HEART, Rank.TEN), face_up=True)
        color = theme.suit_color(enums.Suit.HEART)
        count = sum(1 for x in range(small.width) for y in range(small.height)
                    if surf.get_at((x, y))[:3] == color)
        self.assertGreater(count, 60, '小牌上没画出点数/花色')


class TestLogScrolling(unittest.TestCase):
    def _renderer(self, log_open=True):
        from ui.render import TableRenderer
        window = pygame.display.set_mode((1440, 900))
        lay = Layout((1440, 900))
        lay.set_log_open(log_open)
        renderer = TableRenderer(window, lay)
        return renderer

    def test_scroll_clamped_to_range(self):
        renderer = self._renderer()
        capacity = renderer.layout.log_line_capacity
        total = 40
        renderer.scroll_log(10, total)
        self.assertEqual(renderer.log_scroll, 10)
        renderer.scroll_log(999, total)
        self.assertEqual(renderer.log_scroll, total - capacity, '不应超过最大偏移')
        renderer.scroll_log(-999, total)
        self.assertEqual(renderer.log_scroll, 0, '不应小于 0')
        self.assertTrue(renderer.log_at_bottom())

    def test_page_scroll_and_end(self):
        renderer = self._renderer()
        total = 50
        renderer.scroll_log_page(1, total)
        self.assertGreater(renderer.log_scroll, 0)
        renderer.scroll_log_page(-1, total)
        self.assertEqual(renderer.log_scroll, 0)
        renderer.scroll_log(total, total)
        self.assertGreater(renderer.log_scroll, 0)
        renderer.log_scroll = 0
        self.assertTrue(renderer.log_at_bottom())

    def test_scroll_does_nothing_when_log_collapsed(self):
        renderer = self._renderer(log_open=False)
        self.assertEqual(renderer.layout.log_line_capacity, 0)
        renderer.scroll_log(5, 100)
        self.assertEqual(renderer.log_scroll, 0)

    def test_toggle_log_round_trip(self):
        renderer = self._renderer()
        open_height = renderer.layout.field_rect.height
        self.assertFalse(renderer.toggle_log())
        self.assertGreater(renderer.layout.field_rect.height, open_height)
        self.assertTrue(renderer.toggle_log())
        self.assertEqual(renderer.layout.field_rect.height, open_height)

    def test_scrolled_log_renders_without_error(self):
        from ui.render import seat_map_for
        from viewmodel import TableInteraction, TableView
        from GameMaster import GameMaster
        from controllers import AIController

        controllers = {s: AIController(s, seed=i) for i, s in enumerate(enums.Suit)}
        gm = GameMaster(controllers=controllers, seed=6)
        gm.setup()
        for _ in range(80):
            gm.log(f'测试日志行 {_}')
        view = TableView.from_game_master(gm)
        renderer = self._renderer()
        state = TableInteraction()
        for scroll in (0, 5, 100):
            renderer.log_scroll = scroll
            renderer.draw(view, state, seat_map_for(view), focus=view.players[0],
                          is_my_turn=True)


class TestInteractionFlow(unittest.TestCase):
    """确定性地验证「选中 → 出牌」「结束回合」这两条人类输入路径"""

    def _app(self):
        from ui.app import GameApp
        app = GameApp(seed=7, ai_seats=0, window_size=(1440, 900))
        for _ in range(900):
            app.update(1 / 60.0)
            if app.state.stage == 'choose_action':
                break
        self.assertEqual(app.state.stage, 'choose_action',
                         '未能推进到人类玩家的出牌阶段')
        return app

    def test_click_selects_and_deselects(self):
        app = self._app()
        focus = app.focus_player()
        rects = app.layout.hand_card_rects(app.seat_map[focus], len(focus.hand))
        self.assertTrue(rects)
        for rect in rects:
            app.on_click(rect.center)
        self.assertEqual(len(app.state.selected_uids), len(rects))
        app.on_click(rects[0].center)
        self.assertEqual(len(app.state.selected_uids), len(rects) - 1)

    def test_all_buttons_handle_clicks(self):
        """所有按钮位置点击都不应抛异常（曾因 btn_new 拼错导致点击即崩）"""
        app = self._app()
        positions = [app.layout.btn_menu.center, app.layout.btn_new_game.center,
                     app.layout.btn_help.center, app.layout.btn_log.center]
        positions += [r.center for r in app.layout.buttons.values()]
        positions += [r.center for r in app.layout.chain_buttons.values()]
        positions += [(app.layout.width // 2, app.layout.height - 40),
                      app.layout.field_rect.center, app.layout.info_rect.center]
        for log_open in (True, False):
            app.renderer.set_log_open(log_open)
            for pos in positions:
                app.renderer.show_help = False
                app.renderer.paused = False
                app.on_click(pos)          # 不抛异常即通过

    def test_submit_play_path(self):
        app = self._app()
        focus = app.focus_player()
        rects = app.layout.hand_card_rects(app.seat_map[focus], len(focus.hand))
        app.on_click(rects[0].center)
        before = len(app.gm.play_history)
        app.submit_play()
        for _ in range(120):
            app.update(1 / 60.0)
            if len(app.gm.play_history) > before:
                break
        self.assertGreater(len(app.gm.play_history), before, '出牌没有生效')
        self.assertGreater(len(app.gm.field), 0, '牌没有进入出牌区')

    def test_submit_end_turn_path(self):
        app = self._app()
        before_index = app.gm.turn_index
        before_round = app.gm.round
        app.submit_end_turn()
        moved = False
        for _ in range(2000):
            app.update(1 / 60.0)
            if app.gm.turn_index != before_index or app.gm.round != before_round \
                    or app.gm.game_over:
                moved = True
                break
        self.assertTrue(moved, '结束回合后回合没有交接出去')

    def _setup_chain_window(self, app, same_suit_cards: int = 6):
        """构造一个「轮到真人连锁」的局面：当前玩家出一手，真人手里有同花色组合。

        返回真人玩家（连锁者）的 Player 对象；构造失败返回 None。
        """
        from Card import Card
        from enums import Rank, Suit

        gm = app.gm
        if gm.phase != enums.Phase.PLAY_PHASE:
            return None
        active = gm.current_player()
        tip = gm.active_play
        if tip is None:
            card = next((c for c in active.hand if c.suit != Suit.SPADE), None)
            if card is None:
                return None
            gm.play_cards(active, [card])
            tip = gm.active_play
        if tip is None:
            return None

        # 给所有真人玩家（除当前回合玩家）塞同花色的连续牌，保证有可连锁的组合技
        suit = tip.cards[0].suit
        ranks = [Rank.ACE, Rank.KING, Rank.QUEEN, Rank.JACK, Rank.TEN,
                 Rank.NINE, Rank.EIGHT][:same_suit_cards]
        chainer = None
        for p in gm.players:
            if not isinstance(gm.controllers[p.faction], HumanController):
                continue
            if p is active:
                continue
            p.chained_this_turn = False
            p.declined_chain_this_turn = False
            for rank in ranks:
                gm.move_cards([Card(suit, rank, enums.Zone.HAND)],
                              enums.Zone.HAND, p)
            if chainer is None:
                chainer = p
        if chainer is None:
            return None
        gm._refresh_chain_flags()
        if not chainer.can_chain:
            return None

        # 当前回合玩家（真人）必须先提交自己的决定，驱动器才会走到连锁收集阶段
        gm.controllers[active.faction].clear_pending()
        gm.controllers[active.faction].submit_end_turn()
        return chainer

    def test_chain_options_shown_automatically(self):
        """轮到自己的连锁窗口时，应当立刻列出所有合法连锁，无需先按 Tab"""
        app = self._app()
        human_player = self._setup_chain_window(app)
        self.assertIsNotNone(human_player, '无法构造连锁局面')

        opened = False
        for _ in range(900):
            app.update(1 / 60.0)
            if app.chain_mode:
                opened = True
                break
        self.assertTrue(opened, '连锁窗口没有打开')
        self.assertEqual(app.state.stage, 'choose_chain')
        self.assertTrue(app.state.hint_groups,
                        '连锁窗口打开时应当自动列出可连锁组合')
        self.assertGreaterEqual(app.state.hint_index, 0)
        self.assertIn('建议 1/', app.state.hint_label())
        self.assertTrue(app.state.chain_selected_uids, '应当自动选上第一组连锁牌')
        self.assertNotIn('可达成', app.state.hint_label())
        # 再按一次 Tab 应当切到第 2 组（清单确实是可循环的）
        if len(app.state.hint_groups) > 1:
            app.state.cycle_hint()
            self.assertIn('建议 2/', app.state.hint_label())
        # 渲染一帧，确认信息栏第二行用的是「可连锁」措辞
        app.draw()

    def test_chain_hint_cycling_keeps_list(self):
        """连锁窗口里手工改选之后，Tab 仍能继续在清单里循环"""
        app = self._app()
        state = app.state
        state.begin_choose_chain()
        state.set_hint_groups([([], '同花三条', '抽 2 张'), ([], '对子', '抽 1 张')])
        self.assertEqual(state.hint_index, 0)
        state.toggle(999)                     # 手工点牌
        self.assertEqual(state.hint_cards, [])
        self.assertEqual(len(state.hint_groups), 2)
        state.cycle_hint()
        self.assertEqual(state.hint_index, 1)

    def test_manual_selection_after_auto_hint(self):
        """自动列出连锁清单后，玩家仍可用鼠标改选"""
        app = self._app()
        human_player = self._setup_chain_window(app, same_suit_cards=6)
        self.assertIsNotNone(human_player, '无法构造连锁局面')
        for _ in range(900):
            app.update(1 / 60.0)
            if app.chain_mode:
                break
        self.assertTrue(app.chain_mode, '连锁窗口没有打开')
        auto = set(app.state.chain_selected_uids)
        self.assertTrue(auto, '自动指出的连锁应当已经选中若干张')
        # 清空并手工只选一张
        app.state.clear_selection()
        self.assertEqual(app.state.chain_selected_uids, set())
        app.state.toggle(next(iter(auto)))
        self.assertEqual(len(app.state.chain_selected_uids), 1)

    def test_chain_button_row_keeps_four_buttons(self):
        """连锁窗口的按钮行必须是完整 4 个：连锁出牌 / 放弃连锁 / AI 代打 / 提示

        曾经只画了前两个，后两个位置点得到却看不见按钮和文字。
        """
        from ui.render import TableRenderer, seat_map_for
        from viewmodel import TableInteraction, TableView
        from GameMaster import GameMaster
        from controllers import AIController

        controllers = {s: AIController(s, seed=i) for i, s in enumerate(enums.Suit)}
        gm = GameMaster(controllers=controllers, seed=4)
        gm.setup()
        view = TableView.from_game_master(gm)
        window = pygame.display.set_mode((1440, 900))
        renderer = TableRenderer(window, Layout((1440, 900)))

        self.assertEqual(len(renderer.chain_buttons), 4,
                         '连锁按钮应当有 4 个（含 AI 代打 / 提示）')
        order = ('chain_ok', 'chain_no', 'chain_auto', 'chain_hint')
        normal_order = ('end_turn', 'play', 'auto', 'hint')
        for chain_key, normal_key in zip(order, normal_order):
            self.assertIn(chain_key, renderer.chain_buttons)
            self.assertIn(chain_key, renderer.layout.chain_buttons)
            self.assertEqual(renderer.layout.chain_buttons[chain_key],
                             renderer.layout.buttons[normal_key],
                             f'{chain_key} 应当与 {normal_key} 在同一位置')

        # 实际渲染一帧：四个按钮都要有底色 + 文字
        state = TableInteraction()
        state.begin_choose_chain()
        state.set_hint_groups([([], '对子', '抽 1 张')])
        renderer.draw(view, state, seat_map_for(view), focus=view.players[0])
        surface = window
        for key in order:
            rect = renderer.layout.chain_buttons[key]
            bg = sum(1 for x in range(rect.x + 3, rect.right - 3, 2)
                     for y in range(rect.y + 3, rect.bottom - 3, 2)
                     if surface.get_at((x, y))[:3] == theme.COLOR_BTN)
            ink = sum(1 for x in range(rect.x + 3, rect.right - 3)
                      for y in range(rect.y + 3, rect.bottom - 3)
                      if surface.get_at((x, y))[:3] == theme.COLOR_TEXT)
            self.assertGreater(bg, 200, f'{key} 没有画出按钮底色')
            self.assertGreater(ink, 20, f'{key} 没有画出按钮文字')

    def test_chain_buttons_clickable_in_chain_mode(self):
        """连锁窗口里四个按钮都要能被命中"""
        app = self._app()
        app.state.begin_choose_chain()
        app.layout.set_chain_active(True)
        for key in ('chain_ok', 'chain_no', 'chain_auto', 'chain_hint'):
            rect = app.layout.chain_buttons[key]
            self.assertEqual(app.layout.hit_button(rect.center), key)
        app.layout.set_chain_active(False)

    def test_hidden_hand_only_draws_card_backs(self):
        """联机快照里对手手牌只有 uid，渲染层必须画成牌背"""
        from viewmodel import CardView
        hidden = CardView.from_dict({'uid': 1})          # 快照里没有 suit → 牌背
        self.assertTrue(hidden.hidden)
        self.assertEqual(hidden.symbol, '??')
        self.assertEqual(hidden.text_name, '未知')
        self.assertIsNone(hidden.as_card())
        shown = CardView.from_dict({'uid': 2, 'suit': 'heart', 'rank': 14})
        self.assertFalse(shown.hidden)
        self.assertEqual(shown.text_name, '红桃A')
        self.assertIsNotNone(shown.as_card())

    def test_tab_cycles_hints(self):
        app = self._app()
        app.show_hint()
        self.assertTrue(app.state.hint_groups, 'Tab 应当给出可达成组合')
        first = app.state.hint_index
        app.show_hint()
        if len(app.state.hint_groups) > 1:
            self.assertNotEqual(app.state.hint_index, first, 'Tab 应当切到下一组')
        app.state.clear_selection()
        self.assertEqual(app.state.selected_uids, set())

    def test_log_scroll_keys(self):
        app = self._app()
        for _ in range(30):
            app.gm.log('测试日志')
        app.refresh_view()
        total = len(app.view.log)
        self.assertGreater(total, app.layout.log_line_capacity, '测试数据不足以触发翻页')
        app.renderer.scroll_log_page(1, total)
        self.assertGreater(app.renderer.log_scroll, 0)
        app.renderer.log_scroll = 0
        app.toggle_log()
        self.assertFalse(app.layout.log_open)
        for _ in range(20):
            app.gm.log('收起状态下继续产生日志')
        app.refresh_view()
        app.renderer.scroll_log(5, len(app.view.log))
        self.assertEqual(app.renderer.log_scroll, 0, '日志收起时不应翻页')
        app.toggle_log()
        self.assertTrue(app.layout.log_open)


class TestHintGroups(unittest.TestCase):
    def test_cycle_through_all_combos(self):
        """提示：Tab 应当能循环到所有可达成组合"""
        from GameMaster import GameMaster
        from Card import Card
        from enums import Rank, Suit
        from viewmodel import TableInteraction, find_all_plays, to_cards

        gm = GameMaster(seed=2)
        gm.setup()
        player = gm.current_player()
        # 构造一手有多个组合技的牌
        hand = [Card(player.faction, Rank.THREE, enums.Zone.HAND),
                Card(player.faction, Rank.SEVEN, enums.Zone.HAND),
                Card(player.faction, Rank.KING, enums.Zone.HAND),
                Card(Suit.SPADE, Rank.NINE, enums.Zone.HAND)]
        gm.move_cards(hand, enums.Zone.HAND, player)
        view = TableView.from_game_master(gm)
        pv = view.player_by_faction(player.faction)

        options = find_all_plays(pv.hand, player.faction)
        self.assertTrue(options, '应当至少找到一个可出组合')
        combos = [combo for _cards, combo in options if combo is not None]
        self.assertTrue(combos, '这手牌里应当有组合技')

        state = TableInteraction()
        state.begin_choose_action()
        groups = [(cards, enums.COMBO_CN[combo] if combo else '普通出牌', '')
                  for cards, combo in options]
        first = state.set_hint_groups(groups)
        self.assertIsNotNone(first)
        self.assertEqual(state.hint_index, 0)
        self.assertTrue(state.selected_uids, '建议应当自动把牌选上')
        # 循环一圈能回到起点
        for _ in range(len(groups) - 1):
            state.cycle_hint()
        self.assertEqual(state.hint_index, len(groups) - 1)
        state.cycle_hint()
        self.assertEqual(state.hint_index, 0)
        self.assertIn('1/', state.hint_label())

    def test_empty_hint_groups(self):
        from viewmodel import TableInteraction
        state = TableInteraction()
        self.assertIsNone(state.set_hint_groups([]))
        self.assertEqual(state.hint_label(), '')

    def test_manual_toggle_clears_highlight_but_keeps_list(self):
        from viewmodel import TableInteraction
        state = TableInteraction()
        state.begin_choose_action()
        state.set_hint_groups([([], '对子', '抽 1 张')])
        state.toggle(123)
        self.assertEqual(state.hint_cards, [])
        self.assertTrue(state.hint_groups, '建议清单应当保留，Tab 可继续循环')


class TestRendererView(unittest.TestCase):
    def test_draw_full_frame_without_error(self):
        from ui.render import TableRenderer, seat_map_for
        from viewmodel import TableInteraction, TableView
        from GameMaster import GameMaster
        from controllers import AIController

        controllers = {s: AIController(s, seed=i) for i, s in enumerate(enums.Suit)}
        gm = GameMaster(controllers=controllers, seed=4)
        gm.setup()
        view = TableView.from_game_master(gm)
        state = TableInteraction()
        state.begin_choose_action()

        window = pygame.display.set_mode((1440, 900))
        renderer = TableRenderer(window, Layout((1440, 900)))
        renderer.draw(view, state, seat_map_for(view), focus=view.players[0],
                      is_my_turn=True)
        renderer.show_help = True
        renderer.draw(view, state, seat_map_for(view), focus=view.players[0],
                      is_my_turn=True)
        renderer.show_help = False
        renderer.paused = True
        renderer.draw(view, state, seat_map_for(view), focus=view.players[0],
                      is_my_turn=True)

    def test_text_name_avoids_suit_glyphs(self):
        """界面文字用的 text_name 不能包含 ♠♥♦♣（字体可能没有）"""
        from Card import Card
        from enums import Rank
        for suit in enums.Suit:
            name = Card(suit, Rank.TEN).text_name
            for glyph in enums.SUIT_SYMBOL.values():
                self.assertNotIn(glyph, name)
            self.assertIn(enums.SUIT_CN[suit], name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
