"""pygame 客户端主程序（TODO 1 + TODO 2）

阶段一（本地热座）：同一个客户端里给 4 名玩家各挂一个 HumanController，
界面把「正在行动的玩家」放到下方主面板，鼠标点牌即可出牌；其余 3 家可以
随时改成 AI 托管（--ai 3）。

渲染与交互全部走 ui.render + ui.view，因此联机客户端（net/client.py）
可以复用同一套界面。
"""

import sys

import pygame

import enums
from GameMaster import GameError, GameMaster
from controllers import AIController, HumanController
from turn import TurnRunner
from ui import layout as ui_layout
from ui import theme
from ui.layout import Layout
from ui.render import TableRenderer, seat_map_for
from viewmodel import (TableInteraction, TableView, chain_preview, find_all_chains,
                       find_all_plays, selected_cards)

FPS = 60
AI_STEP_INTERVAL = 0.55
RESOLVE_DELAY = 0.45


class GameApp:
    def __init__(self, seed=None, ai_seats: int = 0, window_size=ui_layout.WINDOW_SIZE,
                 title='Poker Horse Racing · 扑克赛马'):
        pygame.init()
        pygame.display.set_caption(title)
        # 允许在窗口小于屏幕时自动缩小，避免 Windows 因 DPI 缩放而把窗口裁掉
        try:
            pygame.display.set_allow_screensaver(True)
        except Exception:
            pass
        self.window = pygame.display.set_mode(window_size, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        # 以「真正拿到的窗口尺寸」为准：高 DPI 缩放下系统可能把窗口改小，
        # 如果还按请求的尺寸排版，下面的按钮行就会被裁到窗口外（点得到但看不见）
        self.layout = Layout(self._actual_window_size(window_size))
        self.renderer = TableRenderer(self.window, self.layout)
        self.state = TableInteraction()
        self.running = True
        self.seed = seed
        self.ai_seats = ai_seats
        self.mode = 'local'
        self.viewer = None          # 本地热座 = 上帝视角

        self.gm = None
        self.runner = None
        self.view = None
        self.seat_map = {}
        self.ai_timer = 0.0
        self._advisor_cache = None
        self._hint_key = None
        self.turn_counters = {}

        self.new_game(seed=self.seed)

    def _actual_window_size(self, requested=None):
        """返回窗口真实可绘制尺寸（必要时同步窗口表面）"""
        size = None
        try:
            window_size = pygame.display.get_window_size()
            if window_size and window_size[0] > 1 and window_size[1] > 1:
                size = (int(window_size[0]), int(window_size[1]))
        except Exception:
            size = None
        if size is None:
            surface = pygame.display.get_surface()
            size = surface.get_size() if surface else requested
        surface = pygame.display.get_surface()
        # 窗口尺寸与可绘制表面不一致时（DPI 缩放），按较小的那个排版，
        # 并把窗口表面同步过去，保证「排得下」和「画得出」是同一套坐标
        if surface is not None and surface.get_size() != size:
            try:
                self.window = pygame.display.set_mode(size, pygame.RESIZABLE)
            except Exception:
                size = surface.get_size()
        if requested is not None and size is None:
            size = requested
        return size or ui_layout.WINDOW_SIZE

    # ================================================================ 对局
    def new_game(self, seed=None):
        self.seed = seed
        ai_count = max(0, min(4, self.ai_seats))
        controllers = {}
        for i, suit in enumerate(enums.Suit):
            if i < ai_count:
                controllers[suit] = AIController(
                    suit, name=f'{enums.SUIT_CN[suit]}AI',
                    seed=None if seed is None else seed * 31 + i)
            else:
                controllers[suit] = HumanController(suit)
        self.gm = GameMaster(controllers=controllers, seed=seed)
        self.gm.setup()
        self.runner = TurnRunner(self.gm)
        self.state.reset()
        self.ai_timer = 0.0
        self.turn_counters = {}
        self._hint_key = None
        self.renderer.set_log_open(True)
        self.renderer.paused = False
        self.renderer.show_help = False
        self.renderer.set_status('新对局开始！点击「规则 H」查看玩法。')
        self.renderer.flash('新对局开始', 2.0)
        self.refresh_view()

    def refresh_view(self):
        self.view = TableView.from_game_master(
            self.gm, viewer=self.viewer, mode=self.mode,
            ack_map={})
        self.seat_map = seat_map_for(self.view, self.focus_player().name)

    # ================================================================ 主循环
    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()

    # ================================================================ 输入
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.VIDEORESIZE:
                # 以真实窗口尺寸排版（event.w/h 在 DPI 缩放下可能与实际不一致）
                size = (max(ui_layout.MIN_SIZE[0], event.w),
                        max(ui_layout.MIN_SIZE[1], event.h))
                self.window = pygame.display.set_mode(size, pygame.RESIZABLE)
                real = self._actual_window_size(size)
                if real != size:
                    self.window = pygame.display.set_mode(real, pygame.RESIZABLE)
                self.renderer.resize(self.window, real)
                self.layout = self.renderer.layout
            elif event.type == pygame.KEYDOWN:
                self.on_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.on_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                # 滚轮翻日志（pygame 2 在部分平台用 button 4/5 表示滚轮）
                self.on_wheel(1 if event.button == 4 else -1)
            elif event.type == pygame.MOUSEWHEEL:
                self.on_wheel(event.y)
            elif event.type == pygame.MOUSEMOTION:
                for button in list(self.renderer.buttons.values()) \
                        + list(self.renderer.chain_buttons.values()):
                    button.hover = button.rect.collidepoint(event.pos)

    def on_wheel(self, direction: int):
        """direction > 0 = 向上滚 = 往回看更早的日志"""
        if self.renderer.show_help or not self.layout.log_visible:
            return
        total = len(self.view.log) if self.view else 0
        self.renderer.scroll_log(direction * 3, total)

    def on_key(self, event):
        key = event.key
        total_log = len(self.view.log) if self.view else 0
        if key == pygame.K_ESCAPE:
            if self.renderer.show_help:
                self.renderer.show_help = False
            elif self.state.stage == 'choose_chain':
                self.cancel_chain()
            else:
                self.running = False
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.submit_play()
        elif key == pygame.K_e:
            self.submit_end_turn()
        elif key == pygame.K_a:
            self.auto_play()
        elif key == pygame.K_r:
            self.new_game(seed=self.seed)
        elif key in (pygame.K_h, pygame.K_F1):
            self.renderer.show_help = not self.renderer.show_help
        elif key == pygame.K_p:
            self.renderer.paused = not self.renderer.paused
        elif key == pygame.K_l:
            self.toggle_log()
        elif key == pygame.K_BACKSPACE:
            self.state.clear_selection()
            self.state.hint_cards = []
        elif key == pygame.K_TAB:
            self.show_hint()
        # ---- 日志翻页 ----
        elif key == pygame.K_PAGEUP:
            self.renderer.scroll_log_page(1, total_log)
        elif key == pygame.K_PAGEDOWN:
            self.renderer.scroll_log_page(-1, total_log)
        elif key == pygame.K_HOME:
            self.renderer.scroll_log(total_log, total_log)
        elif key == pygame.K_END:
            self.renderer.log_scroll = 0
        elif key == pygame.K_UP:
            self.renderer.scroll_log(1, total_log)
        elif key == pygame.K_DOWN:
            self.renderer.scroll_log(-1, total_log)

    def toggle_log(self):
        opened = self.renderer.toggle_log()
        self.renderer.flash('日志已' + ('展开' if opened else '收起'), 1.4)

    def on_click(self, pos):
        if self.renderer.show_help:
            self.renderer.show_help = False
            return
        button = self.layout.hit_button(pos)
        if button:
            self.on_button(button)
            return
        if self.state.stage not in ('choose_action', 'choose_chain'):
            return
        focus = self.focus_player()          # PlayerView（界面数据模型）
        seat = self.seat_map.get(focus)
        if seat is None:
            return
        rects = self.layout.hand_card_rects(seat, len(focus.hand))
        idx = self.layout.hit_card(seat, rects, pos)
        if idx is None:
            return
        self.state.toggle(focus.hand[idx].uid)

    def on_button(self, name):
        if name == 'new_game':
            self.new_game(seed=self.seed)
        elif name == 'help':
            self.renderer.show_help = True
        elif name == 'menu':
            self.renderer.paused = not self.renderer.paused
        elif name == 'end_turn':
            self.submit_end_turn()
        elif name == 'play':
            self.submit_play()
        elif name == 'auto':
            self.auto_play()
        elif name == 'hint':
            self.show_hint()
        elif name == 'toggle_log':
            self.toggle_log()
        elif name == 'chain_ok':
            self.submit_chain()
        elif name == 'chain_no':
            self.cancel_chain()
        elif name == 'chain_hint':
            self.show_hint()
        elif name == 'chain_auto':
            self.auto_play()

    def auto_play(self):
        """AI 代打当前这一步。

        自己回合 → 让 AI 选一手牌打出或结束回合；
        连锁窗口 → 让 AI 在合法连锁里挑一个，实在没有就放弃连锁。
        """
        if self.state.stage == 'choose_chain':
            return self._auto_chain()
        player = self._active_player()
        controller = self._controller(player)
        if not isinstance(controller, HumanController):
            return
        if self.gm.phase != enums.Phase.PLAY_PHASE or not player.my_turn:
            self.renderer.flash('现在不是出牌阶段', 2.4)
            return
        action = self._advisor().choose_action(self.gm, player)
        controller.clear_pending()
        if action.kind == 'play':
            controller.submit_cards(action.cards)
            self.renderer.flash(f'AI 代打：出 {len(action.cards)} 张', 1.6)
        else:
            controller.submit_end_turn()
            self.renderer.flash('AI 代打：结束回合', 1.6)
        self.state.applied_action()

    def _auto_chain(self):
        """连锁窗口的 AI 代打：优先挑收益最高的合法连锁，挑不出就放弃"""
        player = self._chaining_player()
        if player is None:
            return
        controller = self._controller(player)
        if not isinstance(controller, HumanController):
            return
        groups = self._chain_hint_groups()
        if not groups:
            controller.clear_pending()
            controller.submit_decline_chain()
            self.state.applied_chain()
            self.renderer.flash('AI 代打：没有可连锁的组合，已放弃连锁', 2.2)
            return
        # 用建议清单排序后的第一组（组合技优先、张数多优先）
        cards, name, effect = groups[0]
        uids = {c.uid for c in cards}
        real = [c for c in player.hand if c.uid in uids]
        controller.clear_pending()
        controller.submit_chain(real)
        self.state.applied_chain()
        # 提示要覆盖住「自动列出建议」的那条 flash，否则玩家看不到 AI 做了什么
        self.renderer.flash(f'AI 代打：连锁 {name}（{len(real)} 张）{effect}', 2.6)

    # ================================================================ 查询
    def _controller(self, player):
        return self.gm.controllers.get(player.faction)

    def _active_player(self):
        return self.current_player()

    def current_player(self):
        return self.gm.current_player()

    def focus_player(self):
        """下方主面板显示谁：正在等待输入的玩家优先，否则是当前回合玩家（返回 PlayerView）"""
        target = None
        for player in self.gm.players:
            controller = self._controller(player)
            if getattr(controller, 'pending', None):
                target = player
                break
        if target is None:
            target = self.gm.current_player()
        return self.view.player_by_faction(target.faction)

    def _chaining_player(self):
        for player in self.gm.players:
            controller = self._controller(player)
            if getattr(controller, 'pending', None) \
                    and controller.pending.get('stage') == 'choose_chain':
                return player
        return None

    def _human_pending_stage(self):
        for player in self.gm.players:
            controller = self._controller(player)
            if isinstance(controller, HumanController) and getattr(controller, 'pending', None):
                return controller.pending.get('stage')
        return None

    def _human_waiting(self) -> bool:
        """是否应当暂停驱动器、等真人玩家操作。

        规则很关键（写错过一次，会导致连锁阶段被整个跳过）：
        - 等待「连锁选择」的玩家 → 必须阻塞，等他把连锁栈定下来
        - 等待「自己出牌」的当前回合玩家 → 阻塞（这是他的回合）
        - 等待「自己出牌」的非当前回合玩家 → 不阻塞：那只是某一帧里的短暂状态，
          阻塞它会让连锁阶段永远走不到
        - 已经排队但还没执行的决策不算等待，否则提交后要等别人行动才推进
        """
        gm = self.gm
        active_faction = gm.current_player().faction
        for player in gm.players:
            controller = self._controller(player)
            if not isinstance(controller, HumanController):
                continue
            pending = getattr(controller, 'pending', None)
            if not pending or self._has_queued_decision(controller):
                continue
            stage = pending.get('stage')
            if stage == 'choose_chain':
                return True
            if stage == 'choose_action' and player.faction == active_faction:
                return True
        return False

    @staticmethod
    def _has_queued_decision(controller) -> bool:
        return bool(controller.action_queue or controller.chain_queue)

    def human_active(self) -> bool:
        controller = self._controller(self._active_player())
        return isinstance(controller, HumanController)

    # ---------------------------------------------------------------- 兼容属性
    @property
    def chain_mode(self) -> bool:
        return self.state.stage == 'choose_chain'

    @property
    def selected_uids(self):
        return self.state.selected_uids

    @property
    def chain_selected_uids(self):
        return self.state.chain_selected_uids

    @property
    def hint_cards(self):
        return self.state.hint_cards

    @property
    def status(self):
        return self.renderer.status

    def _selected_cards(self):
        player = self._active_player()
        return selected_cards(self._player_view(player), self.state.selected_uids)

    def _chain_cards(self):
        player = self._chaining_player()
        if player is None:
            return []
        return selected_cards(self._player_view(player), self.state.chain_selected_uids)

    def _player_view(self, player):
        for pv in self.view.players:
            if pv.faction == player.faction:
                return pv
        return None

    def _chain_options(self):
        """当前连锁玩家的所有合法连锁组合 [(CardView 列表, 组合名), ...]"""
        player = self._chaining_player()
        if player is None or self.view.previous is None:
            return []
        pv = self._player_view(player)
        if pv is None:
            return []
        return [(cards, enums.COMBO_CN[combo] if combo else '普通出牌')
                for cards, combo in find_all_chains(pv.hand, self.view.previous)]

    def show_hint(self):
        """提示：列出当前所有可达成 / 可连锁的组合；重复按 Tab 在这些组合间循环"""
        player = self._chaining_player()
        if player is not None:
            key = ('chain', self._chaintip_key())
            groups = self._chain_hint_groups() if self._hint_key != key else None
            if groups is not None and not groups:
                self.state.message = '没有可用的连锁组合'
                self.renderer.flash(self.state.message, 2.4)
                return
            self._apply_hint(groups, key, '没有可用的连锁组合')
            return

        active = self._active_player()
        if not isinstance(self._controller(active), HumanController):
            self.renderer.flash('当前玩家由 AI 控制', 2.0)
            return
        if self.gm.phase != enums.Phase.PLAY_PHASE or not active.my_turn:
            self.renderer.flash('现在不是出牌阶段', 2.0)
            return
        key = ('play', tuple(sorted(c.uid for c in active.hand)))
        groups = self._play_hint_groups(active) if self._hint_key != key else None
        self._apply_hint(groups, key, '手牌里没有可出的牌')

    def _chaintip_key(self):
        """连锁提示的「同一局面」指纹：手牌组合没变就不重建清单"""
        player = self._chaining_player()
        prev = self.view.previous
        hand = tuple(sorted(c.uid for c in player.hand)) if player else ()
        prev_cards = tuple(c.uid for c in prev.cards) if prev else ()
        return (prev_cards, hand)

    def _apply_hint(self, groups, key, empty_message):
        if groups is not None:
            if not groups:
                self.state.message = empty_message
                self.renderer.flash(empty_message, 2.4)
                return
            self._hint_key = key
            self.state.set_hint_groups(groups)
        else:
            if self.state.cycle_hint() is None:
                self.state.message = empty_message
                self.renderer.flash(empty_message, 2.4)
                return
        label = self.state.hint_label()
        self.state.message = label
        self.renderer.flash(label, 3.0)

    def _play_hint_groups(self, player):
        """把「本手可打出的所有组合」转成界面用的建议清单"""
        pv = self._player_view(player)
        if pv is None:
            return []
        groups = []
        for cards, combo in find_all_plays(pv.hand, player.faction):
            name = enums.COMBO_CN[combo] if combo else '普通出牌'
            effect = enums.COMBO_EFFECT_TEXT[combo] if combo else '无附加效果'
            groups.append((cards, name, effect))
        return groups

    def _chain_hint_groups(self):
        """把「本次可连锁的所有组合」转成界面用的建议清单"""
        player = self._chaining_player()
        if player is None or self.view.previous is None:
            return []
        pv = self._player_view(player)
        if pv is None:
            return []
        groups = []
        for cards, combo in find_all_chains(pv.hand, self.view.previous):
            name = enums.COMBO_CN[combo] if combo else '普通出牌'
            effect = enums.COMBO_EFFECT_TEXT[combo] if combo else '无附加效果'
            groups.append((cards, name, effect))
        return groups

    # ================================================================ 提交输入
    def submit_play(self):
        if self.state.stage == 'choose_chain':
            self.submit_chain()
            return
        player = self._active_player()
        controller = self._controller(player)
        if not isinstance(controller, HumanController):
            self.renderer.flash('当前玩家由 AI 控制', 2.0)
            return
        if self.gm.phase != enums.Phase.PLAY_PHASE or not player.my_turn:
            self.renderer.flash('现在不是你的出牌阶段', 2.4)
            return
        cards = self._selected_cards()
        if not cards:
            self.state.message = '请先点击手牌选择要出的牌'
            self.renderer.flash(self.state.message, 2.4)
            return
        # CardView → 真实 Card（用于本地校验）
        real = [c for c in player.hand if c.uid in self.state.selected_uids]
        try:
            self.gm.validate_play(player, real)
        except GameError as exc:
            self.state.message = f'不能这样出牌：{exc}'
            self.renderer.flash(self.state.message, 3.0)
            return
        controller.clear_pending()
        controller.submit_cards(real)
        self.state.applied_action()
        self.renderer.flash(f'{player.name} 出牌 {len(real)} 张', 1.5)

    def submit_end_turn(self):
        if self.state.stage == 'choose_chain':
            self.cancel_chain()
            return
        player = self._active_player()
        controller = self._controller(player)
        if not isinstance(controller, HumanController):
            self.renderer.flash('当前玩家由 AI 控制', 2.0)
            return
        if self.gm.phase != enums.Phase.PLAY_PHASE or not player.my_turn:
            self.renderer.flash('现在不是你的出牌阶段', 2.4)
            return
        controller.clear_pending()
        controller.submit_end_turn()
        self.state.applied_action()
        self.renderer.flash(f'{player.name} 结束回合', 1.5)

    def submit_chain(self):
        player = self._chaining_player()
        if player is None:
            self.state.to_idle()
            return
        controller = self._controller(player)
        cards = self._chain_cards()
        if not cards:
            self.state.message = '请选择连锁用的牌，或点击「放弃连锁」'
            self.renderer.flash(self.state.message, 2.4)
            return
        ok, why = chain_preview(cards, self.view.previous)
        if not ok:
            self.state.message = f'不满足连锁条件：{why}'
            self.renderer.flash(self.state.message, 3.0)
            return
        real = [c for c in player.hand if c.uid in self.state.chain_selected_uids]
        controller.clear_pending()
        controller.submit_chain(real)
        self.state.applied_chain()
        self.renderer.flash(f'{player.name} 发动连锁', 1.5)

    def cancel_chain(self):
        player = self._chaining_player()
        if player is None:
            self.state.to_idle()
            return
        controller = self._controller(player)
        controller.clear_pending()
        controller.submit_decline_chain()
        self.state.applied_chain()

    def _advisor(self):
        if self._advisor_cache is None:
            self._advisor_cache = AIController(None, name='advisor', seed=2024)
        return self._advisor_cache

    # ================================================================ 更新
    def update(self, dt):
        if self.renderer.toast_timer > 0:
            self.renderer.toast_timer = max(0.0, self.renderer.toast_timer - dt)

        # 每一步之后刷新视图与输入状态
        self.refresh_view()
        self._sync_interaction_state()

        # 对局结束
        if self.gm.game_over:
            if self.view.winner_name:
                self.renderer.set_status(
                    f'🏆 {self.view.winner_name} 获胜！按 R 重新开始')
            return

        if self.renderer.paused or self.renderer.show_help:
            return

        if self._human_waiting():
            self.ai_timer = 0.0
            return

        self.ai_timer += dt
        interval = RESOLVE_DELAY if self.gm.chain_open else AI_STEP_INTERVAL
        if self.ai_timer < interval:
            return
        self.ai_timer = 0.0
        self.advance()

    def _sync_interaction_state(self):
        """让输入状态机跟随 GameMaster / 控制器的等待状态"""
        stage = self._human_pending_stage()
        if stage == 'choose_chain':
            if self.state.stage != 'choose_chain':
                self.state.begin_choose_chain()
                # 轮到自己连锁时立刻把「所有合法连锁」摆出来，
                # 不用先按 Tab 才知道能连什么（列出即高亮第一组，Tab 继续循环）
                self._refresh_chain_hints()
        elif stage == 'choose_action':
            if self.state.stage != 'choose_action':
                self.state.begin_choose_action()
        else:
            if self.state.stage != 'idle':
                self.state.to_idle()

    def _refresh_chain_hints(self) -> bool:
        """连锁窗口刚打开时自动列出所有可连锁组合。返回是否有可用组合。

        这里刻意不弹 toast：清单已经在信息栏第二行显示，
        抢用 toast 会把「AI 代打做了什么」之类的提示盖掉。
        """
        groups = self._chain_hint_groups()
        if not groups:
            self.state.message = '没有可用的连锁组合（按 Esc 放弃连锁）'
            return False
        self._hint_key = ('chain', self._chaintip_key())
        first = self.state.set_hint_groups(groups)
        self.state.message = self.state.hint_label()
        return first is not None

    def advance(self):
        result = self.runner.step()
        stage = result.get('stage')
        if stage == 'illegal':
            self.renderer.flash(result.get('text', ''), 3.0)
        elif stage in ('played', 'chain', 'turn_end', 'resolved', 'drew'):
            self.renderer.flash(result.get('text', ''), 1.6)
        if self.gm.game_over:
            self.renderer.set_status(
                f'🏆 {self.view.winner_name} 获胜！按 R 重新开始')

    # ================================================================ 绘制
    def draw(self):
        focus = self.focus_player()
        is_focus_human = isinstance(self._controller(focus), HumanController)
        self.renderer.draw(self.view, self.state, self.seat_map, focus=focus,
                           is_my_turn=is_focus_human and focus.my_turn,
                           clickable=is_focus_human)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if '--diag' in argv:
        return run_diagnostics(argv)
    if '--shot' in argv:
        return run_screenshot(argv)
    ai_seats = 0
    seed = None
    if '--ai' in argv:
        idx = argv.index('--ai')
        try:
            ai_seats = int(argv[idx + 1])
        except (IndexError, ValueError):
            ai_seats = 3
    if '--seed' in argv:
        idx = argv.index('--seed')
        try:
            seed = int(argv[idx + 1])
        except (IndexError, ValueError):
            seed = None
    app = GameApp(seed=seed, ai_seats=ai_seats)
    app.run()
    return 0


def run_screenshot(argv=None, out_dir='shots') -> int:
    """--shot：把几个关键界面截图存成 PNG，便于肉眼核对排版。

    会在真实窗口里渲染（能直接看到最终效果），保存后立即退出。
    """
    import os

    import enums
    from Card import Card
    from controllers import HumanController
    from enums import Rank, Suit

    argv = list(argv or [])
    app = GameApp(seed=7, ai_seats=0)
    os.makedirs(out_dir, exist_ok=True)
    saved = []

    def snap(name):
        app.draw()
        pygame.display.flip()
        path = os.path.join(out_dir, f'{name}.png')
        pygame.image.save(app.window, path)
        saved.append(path)

    # 1. 出牌阶段（带提示）
    for _ in range(900):
        app.update(1 / 60.0)
        if app.state.stage == 'choose_action':
            break
    app.show_hint()
    snap('01_play_phase')

    # 2. 连锁窗口（自动列出全部合法连锁）
    gm = app.gm
    active = gm.current_player()
    if gm.active_play is None:
        card = next((c for c in active.hand if c.suit != Suit.SPADE), None)
        if card is not None:
            gm.play_cards(active, [card])
    if gm.active_play is not None:
        suit = gm.active_play.cards[0].suit
        for p in gm.players:
            if p is active or not isinstance(gm.controllers[p.faction], HumanController):
                continue
            p.chained_this_turn = False
            p.declined_chain_this_turn = False
            for rank in (Rank.ACE, Rank.KING, Rank.QUEEN, Rank.JACK, Rank.TEN, Rank.NINE):
                gm.move_cards([Card(suit, rank, enums.Zone.HAND)], enums.Zone.HAND, p)
        gm._refresh_chain_flags()
        gm.controllers[active.faction].clear_pending()
        gm.controllers[active.faction].submit_end_turn()
        for _ in range(900):
            app.update(1 / 60.0)
            if app.chain_mode:
                break
        if app.chain_mode:
            snap('02_chain_window')

    # 3. 收起日志
    app.renderer.toggle_log()
    snap('03_log_hidden')
    app.renderer.toggle_log()

    # 4. 规则浮层
    app.renderer.show_help = True
    snap('04_help')
    app.renderer.show_help = False

    pygame.quit()
    for path in saved:
        print('saved', path)
    return 0


def run_diagnostics(argv=None, window_size=ui_layout.WINDOW_SIZE) -> int:
    """--diag：打印窗口/DPI/布局的关键尺寸，用来排查「按钮点得到但看不见」。

    不进入主循环，只在真实显示环境里创建一次窗口并输出诊断信息。
    """
    argv = list(argv or [])
    if '--seed' in argv:
        idx = argv.index('--seed')
        try:
            seed = int(argv[idx + 1])
        except (IndexError, ValueError):
            seed = None
    else:
        seed = None

    app = GameApp(seed=seed, ai_seats=3, window_size=window_size)
    info = pygame.display.Info()
    surface = pygame.display.get_surface()
    print('=== 显示诊断 ===')
    print(f'请求窗口尺寸      : {window_size}')
    print(f'SDL 窗口尺寸      : {pygame.display.get_window_size()}')
    print(f'可绘制表面尺寸    : {surface.get_size() if surface else None}')
    print(f'当前显示驱动      : {pygame.display.get_driver()}')
    print(f'桌面分辨率        : {info.current_w} x {info.current_h}')
    print(f'布局使用尺寸      : {app.layout.width} x {app.layout.height}')
    print(f'渲染目标尺寸      : {app.window.get_size()}')
    print('--- 关键区域（应全部落在布局尺寸内）---')
    rects = {'信息栏': app.layout.info_rect, '出牌区': app.layout.field_rect,
             '日志': app.layout.log_rect}
    rects.update({f'按钮[{k}]': v for k, v in app.layout.buttons.items()})
    rects.update({f'连锁按钮[{k}]': v for k, v in app.layout.chain_buttons.items()})
    ok = True
    for name, rect in rects.items():
        inside = app.layout.screen.contains(rect)
        ok = ok and inside
        flag = '' if inside else '   ← 超出可绘制区域！'
        print(f'  {name:18s} {tuple(rect)}{flag}')
    print(f'按钮行 y={app.layout.buttons_top}，'
          f'窗口高度={app.layout.height}，'
          f'底部状态栏 y={app.layout.height - 26}')
    if app.layout.buttons_top + 34 > app.layout.height:
        print('  ★ 按钮行被挤到窗口底部之外：窗口太矮，请把窗口拉高或改用更小的缩放')
        ok = False
    # 实际画一帧，确认按钮位置真的出现了按钮底色
    app.draw()
    from ui import theme as _theme
    for name, rect in list(app.layout.buttons.items()):
        px = app.window.get_at(rect.center)[:3]
        print(f'  画面像素 @按钮[{name}] {px}')
    print('=== 诊断结果:', '正常' if ok else '发现问题（见上方 ★）', '===')
    pygame.quit()
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
