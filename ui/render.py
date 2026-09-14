"""牌桌渲染器（TODO 2：图形化）

只依赖 TableView / TableInteraction，不依赖 GameMaster，
因此本地热座与局域网客户端可以共用同一套渲染。
"""

import pygame

import enums
from ui import layout as ui_layout
from ui import theme
from ui import widgets
from ui.layout import BOTTOM, LEFT, RIGHT, TOP, Layout
from viewmodel import TableInteraction, TableView, to_cards

HELP_LINES = [
    ('目标：率先累计到目标分数（默认 30 分）者获胜。', True),
    ('', False),
    ('每个回合：抽牌阶段抽 2 张 → 出牌阶段出牌或结束回合 → 结束阶段清场结算。', False),
    ('加分：自己回合打出自己阵营花色的牌，每张 +1 分。', False),
    ('', False),
    ('组合技：', True),
    ('  同花色 2/3/5 张 = 同花对子 / 同花三条 / 同花', False),
    ('  四花色各 1 张 = 四季；同点数 2/3/4 张 = 对子 / 三条 / 四条', False),
    ('  连续 3/5 张 = 顺子 / 长顺（A 可以当 1 或 14）', False),
    ('  组合技附带抽牌与加分；四条还会让其他玩家各弃 1 张。', False),
    ('', False),
    ('连锁（LIFO 后进先出）：他人出牌后，若你的手牌满足', False),
    ('  ①花色相同 ②花色相反（红黑）③点数之和相同 ④点数之和更大', False),
    ('即可发动连锁，每回合每人最多连锁 1 次。', False),
    ('打断：在他人回合打出「当前回合玩家阵营花色」且点数之和更大，', False),
    ('      可无效化连锁栈中上一个加分效果。', False),
    ('', False),
    ('操作：鼠标点牌选择 → Enter 出牌 / E 结束回合 / A AI 代打 /', True),
    ('      H 帮助 / R 重开 / P 暂停 / Backspace 清空选择。', True),
]


class TableRenderer:
    def __init__(self, window, layout: Layout):
        self.window = window
        self.layout = layout
        self.frame = 0
        self.toast = ''
        self.toast_timer = 0.0
        self.status = ''
        self.buttons = {}
        self.chain_buttons = {}
        self.show_help = False
        self.paused = False
        self.log_scroll = 0          # 日志向后翻阅的行数（0 = 最新）
        self.log_anywhere = True     # 滚轮在窗口任意位置都能翻日志
        self.rebuild_buttons()

    # ------------------------------------------------------------ 初始化
    def resize(self, window, size):
        self.window = window
        self.layout.resize(size)
        self.log_scroll = 0
        self.rebuild_buttons()

    def rebuild_buttons(self):
        self.buttons = {
            'end_turn': widgets.Button(self.layout.buttons['end_turn'], '结束回合 (E)', 'end_turn'),
            'play': widgets.Button(self.layout.buttons['play'], '出牌 (Enter)', 'play'),
            'auto': widgets.Button(self.layout.buttons['auto'], 'AI 代打 (A)', 'auto'),
            'hint': widgets.Button(self.layout.buttons['hint'], '提示/切换 (Tab)', 'hint'),
        }
        # 连锁窗口的按钮行与出牌阶段一一对应，始终是整行四个按钮
        self.chain_buttons = {
            'chain_ok': widgets.Button(self.layout.chain_buttons['chain_ok'],
                                       '连锁出牌 (Enter)', 'chain_ok'),
            'chain_no': widgets.Button(self.layout.chain_buttons['chain_no'],
                                       '放弃连锁 (Esc)', 'chain_no'),
            'chain_auto': widgets.Button(self.layout.chain_buttons['chain_auto'],
                                         'AI 代打 (A)', 'chain_auto'),
            'chain_hint': widgets.Button(self.layout.chain_buttons['chain_hint'],
                                         '提示/切换 (Tab)', 'chain_hint'),
        }

    def flash(self, msg: str, seconds: float = 2.4):
        self.toast = msg
        self.toast_timer = seconds

    def set_status(self, msg: str):
        self.status = msg

    # ------------------------------------------------------------ 日志翻页
    def set_log_open(self, opened: bool):
        self.layout.set_log_open(opened)
        self.log_scroll = 0
        self.rebuild_buttons()

    def toggle_log(self):
        self.set_log_open(not self.layout.log_open)
        return self.layout.log_open

    def scroll_log(self, delta_lines: int, total_lines: int) -> int:
        """delta_lines > 0 表示往回翻（看更早的日志）。返回新的偏移量。"""
        if not self.layout.log_visible:
            self.log_scroll = 0
            return 0
        capacity = self.layout.log_line_capacity
        max_offset = max(0, total_lines - capacity)
        self.log_scroll = max(0, min(max_offset, self.log_scroll + delta_lines))
        return self.log_scroll

    def scroll_log_page(self, direction: int, total_lines: int) -> int:
        capacity = max(1, self.layout.log_line_capacity)
        return self.scroll_log(direction * max(1, capacity - 1), total_lines)

    def log_at_bottom(self) -> bool:
        return self.log_scroll == 0

    # ------------------------------------------------------------ 主绘制
    def draw(self, view: TableView, state: TableInteraction, seat_map: dict,
             focus=None, is_my_turn: bool = False, clickable: bool = True):
        self.frame += 1
        surface = self.window
        surface.fill(theme.COLOR_BG)
        self.draw_background(surface)
        self.draw_topbar(surface, view)
        self.draw_center(surface, view, state)
        for player, seat in seat_map.items():
            self.draw_seat(surface, view, state, player, seat, focus)
        self.draw_status(surface, view)
        # 连锁窗口复用同一行按钮：前两个换成连锁操作，后两个仍是 AI 代打 / 提示
        self.layout.set_chain_active(state.stage == 'choose_chain')
        if state.stage == 'choose_chain':
            self.update_chain_button_states(clickable)
            for button in self.chain_buttons.values():
                button.draw(surface)
        else:
            self.update_button_states(state, is_my_turn, clickable)
            for button in self.buttons.values():
                button.draw(surface)
        self.draw_toast(surface)
        if self.show_help:
            self.draw_help(surface)
        if self.paused and not self.show_help:
            self.draw_pause(surface)

    def update_button_states(self, state: TableInteraction, is_my_turn: bool, clickable: bool):
        self.buttons['play'].enabled = clickable and is_my_turn and state.stage == 'choose_action'
        self.buttons['end_turn'].enabled = clickable and is_my_turn and state.stage == 'choose_action'
        self.buttons['hint'].enabled = clickable and state.stage in ('choose_action', 'choose_chain')
        self.buttons['auto'].enabled = clickable and is_my_turn and state.stage == 'choose_action'

    def update_chain_button_states(self, clickable: bool):
        for button in self.chain_buttons.values():
            button.enabled = clickable

    # ------------------------------------------------------------ 背景 / 顶栏
    def draw_background(self, surface):
        pygame.draw.rect(surface, theme.COLOR_FELT, self.layout.center, border_radius=16)
        for i in range(0, self.layout.center.width, 46):
            pygame.draw.line(surface, theme.COLOR_FELT_LIGHT,
                             (self.layout.center.x + i, self.layout.center.y),
                             (self.layout.center.x + i, self.layout.center.bottom), 1)
        for j in range(0, self.layout.center.height, 46):
            pygame.draw.line(surface, theme.COLOR_FELT_LIGHT,
                             (self.layout.center.x, self.layout.center.y + j),
                             (self.layout.center.right, self.layout.center.y + j), 1)
        pygame.draw.rect(surface, theme.COLOR_FELT_DARK, self.layout.center, 3, border_radius=16)

    def draw_topbar(self, surface, view: TableView):
        widgets.rounded(surface, self.layout.topbar, theme.COLOR_PANEL, 0)
        widgets.text(surface, 'POKER HORSE RACING · 扑克赛马',
                     (self.layout.width // 2, 20), 21, theme.COLOR_GOLD,
                     bold=True, center=True)
        mode = '本地热座' if view.mode == 'local' else '局域网对局'
        info = (f'{mode} · 第 {view.round} 轮 · {view.phase_cn} · 轮到 {view.turn_name}'
                f' · 牌堆 {view.draw_pile} · 目标 {view.target_score} 分')
        widgets.text(surface, info, (self.layout.width // 2, 41), 15,
                     theme.COLOR_TEXT_DIM, center=True)
        labels = (('menu', '暂停 P'), ('new_game', '重开 R'), ('help', '规则 H'),
                  ('log', ('收起日志 L' if self.layout.log_open else '展开日志 L')))
        for key, label in labels:
            rect = getattr(self.layout, f'btn_{key}')
            active = key == 'log' and not self.layout.log_open
            widgets.rounded(surface, rect,
                            theme.COLOR_BTN_ACTIVE if active else theme.COLOR_BTN, 6)
            widgets.text(surface, label, rect.center, 15,
                         (24, 28, 32) if active else theme.COLOR_TEXT, center=True)

    # ------------------------------------------------------------ 中央
    def draw_center(self, surface, view: TableView, state: TableInteraction):
        self.draw_info_bar(surface, view, state)

        pygame.draw.rect(surface, (16, 52, 38), self.layout.field_rect, border_radius=10)
        pygame.draw.rect(surface, theme.COLOR_FELT_DARK, self.layout.field_rect, 2,
                         border_radius=10)
        widgets.text(surface, '出牌区 FIELD',
                     (self.layout.field_rect.x + 10, self.layout.field_rect.y + 6),
                     14, theme.COLOR_TEXT_DIM)
        cards = []
        for play in view.plays:
            cards.extend(play.cards)
        rects = self.layout.field_card_rects(len(cards))
        highlight = theme.COLOR_BORDER_CHAIN if self.frame % 60 < 30 else theme.COLOR_GOLD
        for card, card_rect in zip(cards, rects):
            widgets.draw_card(surface, card_rect, _as_card(card), highlight=highlight)

        if view.chain_stack:
            names = [f'{item["owner"]}·{item["label"]}' for item in reversed(view.chain_stack)]
            widgets.text(surface, '连锁栈（自顶向下结算）：' + ' → '.join(names[:6]),
                         (self.layout.field_rect.x + 10,
                          self.layout.field_rect.bottom - 22), 14, theme.COLOR_GOLD)
        self.draw_log(surface, view)

    def draw_info_bar(self, surface, view: TableView, state: TableInteraction):
        """信息栏：固定显示上一手 + 可选择提示，连锁时改为连锁提示（不再遮挡出牌区）"""
        rect = self.layout.info_rect
        chaining = state.stage == 'choose_chain'
        bg = (12, 40, 56) if chaining else (14, 40, 30)
        widgets.rounded(surface, rect, bg, 8)
        if chaining:
            pygame.draw.rect(surface, theme.COLOR_BORDER_CHAIN, rect, 2, border_radius=8)

        if view.previous is not None:
            prev = view.previous
            prefix = f'上一手 {prev.player_name}：' if chaining else '上一手：'
            line1 = (f'{prefix}{prev.combo_cn} · '
                     f'{" ".join(c.text_name for c in prev.cards)}'
                     f'（点数之和 {prev.sum}）')
        else:
            line1 = '本回合还没有人出牌'
        color1 = theme.COLOR_TEXT if not chaining else theme.COLOR_BORDER_CHAIN
        widgets.text(surface, line1, (rect.x + 12, rect.y + 6), 17, color1,
                     bold=chaining)

        # 第二行：当前可达成（自己回合）/ 可连锁（连锁窗口）的全部选项
        options = state.hint_groups
        if options:
            cards, name, effect = options[max(0, state.hint_index)]
            verb = '可连锁' if chaining else '可达成'
            line2 = (f'{verb} {len(options)} 种：'
                     f'{state.hint_index + 1}/{len(options)} '
                     f'{name}（{len(cards)} 张）{effect}  —— Tab 切换')
            widgets.text(surface, line2, (rect.x + 12, rect.y + 36), 15, theme.COLOR_GOLD)
        elif chaining:
            widgets.text(surface, '本手没有可连锁的组合；按 Esc 或「放弃连锁」继续',
                         (rect.x + 12, rect.y + 36), 15, theme.COLOR_TEXT_DIM)
        else:
            widgets.text(surface, self.status or '点手牌选择 → Enter 出牌 / E 结束回合 / Tab 提示 / L 收起日志',
                         (rect.x + 12, rect.y + 36), 15, theme.COLOR_TEXT_DIM)

    def draw_log(self, surface, view: TableView):
        if not self.layout.log_visible:
            return
        rect = self.layout.log_rect
        widgets.rounded(surface, rect, (14, 30, 24), 10)

        capacity = self.layout.log_line_capacity
        lines = list(view.log)
        total = len(lines)
        self.log_scroll = min(self.log_scroll, max(0, total - capacity))
        end = total - self.log_scroll
        start = max(0, end - capacity)
        window_lines = lines[start:end]

        title = '对局日志'
        if self.log_scroll:
            title += f'（已往回翻 {self.log_scroll} 行 · {start + 1}-{end}/{total}）'
        else:
            title += f'（最新 {total} 行）'
        widgets.text(surface, title, (rect.x + 10, rect.y + 5), 15, theme.COLOR_TEXT_DIM)

        hint = '滚轮/PgUp/PgDn 翻页 · End 回到最新 · L 收起'
        widgets.text(surface, hint, (rect.right - 12, rect.y + 6), 13,
                     theme.COLOR_TEXT_DIM, right=True)

        y = rect.y + 26
        for line in window_lines:
            color = theme.COLOR_TEXT
            if '🏆' in line or '获胜' in line:
                color = theme.COLOR_GOLD
            elif '非法' in line or '打断' in line:
                color = theme.COLOR_TEXT_WARN
            widgets.text(surface, line[:70], (rect.x + 10, y), 13, color)
            y += 18
            if y > rect.bottom - 4:
                break

        # 滚动条
        if total > capacity:
            track = pygame.Rect(rect.right - 7, rect.y + 24, 4, rect.height - 30)
            pygame.draw.rect(surface, (26, 46, 38), track, border_radius=2)
            ratio = capacity / total
            thumb_h = max(18, int(track.height * ratio))
            span = track.height - thumb_h
            # log_scroll = 0 时滑块在底部
            progress = 1.0 - (self.log_scroll / max(1, total - capacity))
            thumb = pygame.Rect(track.x, track.y + int(span * (1 - progress)),
                                track.width, thumb_h)
            pygame.draw.rect(surface, theme.COLOR_GOLD, thumb, border_radius=2)

    # ------------------------------------------------------------ 座位
    def draw_seat(self, surface, view: TableView, state: TableInteraction,
                  player, seat, focus):
        rect = self.layout.seat_rects[seat]
        is_focus = player is focus
        chaining = state.stage == 'choose_chain' and is_focus
        accent = theme.suit_color(player.faction)

        flags = []
        if player.my_turn:
            flags.append('回合中')
        if player.can_chain:
            flags.append('可连锁')
        if chaining:
            flags.append('连锁中')
        if player.is_ai:
            flags.append('AI')
        if player.is_viewer:
            flags.append('你')
        if view.mode == 'network' and not player.connected:
            flags.append('掉线')
        subtitle = ' · '.join(flags)
        tail = f'{player.score} 分 · 手牌 {player.hand_size}'
        subtitle = f'{subtitle}  |  {tail}' if subtitle else tail

        widgets.draw_panel(surface, rect, player.name, subtitle,
                           active=player.my_turn and not view.game_over,
                           chain=chaining, accent=accent)

        if is_focus and state.message:
            widgets.text(surface, state.message, (rect.centerx, rect.y + 38), 15,
                         theme.COLOR_TEXT_WARN, center=True)
        self.draw_hand(surface, view, state, player, seat, rect, is_focus)
        return rect

    def draw_hand(self, surface, view: TableView, state: TableInteraction,
                  player, seat, rect, is_focus: bool):
        cards = player.hand
        if player.hand_size and not cards:
            self._draw_hidden_hand(surface, player.hand_size, seat, rect)
            return
        if not cards:
            widgets.text(surface, '（无手牌）', (rect.centerx, rect.centery + 10), 16,
                         theme.COLOR_TEXT_DIM, center=True)
            return
        rects = self.layout.hand_card_rects(seat, len(cards))
        selected = state.chain_selected_uids if state.stage == 'choose_chain' \
            else state.selected_uids
        for card, card_rect in zip(cards, rects):
            is_selected = is_focus and card.uid in selected
            is_hint = is_focus and any(h.uid == card.uid for h in state.hint_cards)
            lift = -12 if is_selected else 0
            moved = pygame.Rect(card_rect.x, card_rect.y + lift, card_rect.width, card_rect.height)
            highlight = theme.COLOR_GOLD if (is_hint and not is_selected) else None
            widgets.draw_card(surface, moved, _as_card(card), face_up=not card.hidden,
                              selected=is_selected, highlight=highlight)

    def _draw_hidden_hand(self, surface, count: int, seat: str, rect):
        """对手手牌只画牌背（状态与渲染分离）"""
        rects = self.layout.hand_card_rects(seat, count)
        for card_rect in rects:
            widgets.draw_card(surface, card_rect, face_up=False)

    # ------------------------------------------------------------ 状态栏
    def draw_status(self, surface, view: TableView):
        rect = pygame.Rect(0, self.layout.height - 26, self.layout.width, 26)
        widgets.rounded(surface, rect, theme.COLOR_PANEL, 0)
        if self.status:
            status = self.status
        elif self.layout.log_open:
            status = ('点手牌选择 → Enter 出牌 / E 结束回合 / Tab 提示 / '
                      '滚轮或 PgUp·PgDn 翻日志 / L 收起日志')
        else:
            status = ('点手牌选择 → Enter 出牌 / E 结束回合 / Tab 提示 / '
                      'L 展开日志 / H 规则')
        color = theme.COLOR_GOLD if (view.game_over and view.winner_name) else theme.COLOR_TEXT
        widgets.text(surface, status, (self.layout.width // 2, rect.centery), 15, color,
                     center=True)

    # ------------------------------------------------------------ 悬浮提示 / 弹窗
    def draw_toast(self, surface):
        if self.toast_timer <= 0 or not self.toast:
            return
        alpha = min(1.0, self.toast_timer / 0.4)
        font = theme.font(18, True)
        img = font.render(self.toast[:60], True, theme.COLOR_TEXT)
        pad = 14
        rect = pygame.Rect(0, 0, img.get_width() + pad * 2, img.get_height() + pad)
        rect.center = (self.layout.center.centerx, self.layout.height - 118)
        box = pygame.Surface(rect.size, pygame.SRCALPHA)
        box.fill((*theme.COLOR_TOAST, int(230 * alpha)))
        surface.blit(box, rect.topleft)
        surface.blit(img, (rect.x + pad, rect.y + pad // 2))

    def draw_chain_prompt(self, surface, view: TableView, state: TableInteraction):
        """（已合并进信息栏 draw_info_bar，此方法保留为空实现以兼容旧调用）"""

    def draw_pause(self, surface):
        veil = pygame.Surface(self.layout.screen.size, pygame.SRCALPHA)
        veil.fill((0, 0, 0, 150))
        surface.blit(veil, (0, 0))
        widgets.text(surface, '已暂停', self.layout.screen.center, 52, theme.COLOR_GOLD,
                     center=True, bold=True)
        widgets.text(surface, '按 P 继续 · 按 R 重开 · 按 H 查看规则',
                     (self.layout.screen.centerx, self.layout.screen.centery + 50),
                     20, theme.COLOR_TEXT, center=True)

    def draw_help(self, surface):
        veil = pygame.Surface(self.layout.screen.size, pygame.SRCALPHA)
        veil.fill((0, 0, 0, 205))
        surface.blit(veil, (0, 0))
        box = pygame.Rect(0, 0, min(880, self.layout.width - 80),
                          min(700, self.layout.height - 60))
        box.center = self.layout.screen.center
        widgets.rounded(surface, box, (18, 26, 32), 14)
        pygame.draw.rect(surface, theme.COLOR_GOLD, box, 2, border_radius=14)
        widgets.text(surface, '玩法速查（完整规则见 RULES.md）',
                     (box.centerx, box.y + 26), 24, theme.COLOR_GOLD,
                     center=True, bold=True)
        y = box.y + 62
        for line, gold in HELP_LINES:
            widgets.text(surface, line, (box.x + 28, y), 17,
                         theme.COLOR_GOLD if gold else theme.COLOR_TEXT)
            y += 25
        widgets.text(surface, '点击任意位置或按 H 关闭',
                     (box.centerx, box.bottom - 26), 15, theme.COLOR_TEXT_DIM,
                     center=True)


def _as_card(card_view):
    """CardView → Card（仅为复用绘制函数；隐藏牌返回 None 画牌背）"""
    if card_view is None or card_view.hidden or card_view.suit is None:
        return None
    from Card import Card
    return Card(card_view.suit, card_view.rank, enums.Zone.HAND)


def seat_map_for(view: TableView, focus_name: str = None) -> dict:
    """把视图里的玩家分配到四个座位：焦点玩家固定在下方主面板"""
    players = list(view.players)
    if not players:
        return {}
    if focus_name is None:
        focus_name = view.turn_name
    focus = next((p for p in players if p.name == focus_name), players[0])
    order = [focus] + [p for p in players if p is not focus]
    return {player: ui_layout.seat_for(i) for i, player in enumerate(order)}


__all__ = ['TableRenderer', 'seat_map_for', 'BOTTOM', 'TOP', 'LEFT', 'RIGHT']
