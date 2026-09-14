"""界面布局计算（pygame 图形层，TODO 2）

四名玩家各占一个角落面板（本地热座），中央是出牌区与日志。
所有矩形都由这里算出，方便命中测试与响应式缩放。
"""

import pygame

# 窗口默认尺寸
WINDOW_SIZE = (1440, 900)
MIN_SIZE = (1120, 760)

# 四个面板对应的位置（按玩家在 gm.players 中的索引无关，由 seat 决定）
BOTTOM = 'bottom'
LEFT = 'left'
TOP = 'top'
RIGHT = 'right'

# 手牌尺寸
CARD_W, CARD_H = 78, 110
MINI_W, MINI_H = 52, 74


class Layout:
    def __init__(self, size=WINDOW_SIZE):
        self.log_open = True          # 日志面板是否展开（收起后出牌区变大）
        self.chain_active = False     # 连锁按钮与普通按钮共用一行，由渲染层切换
        self.resize(size)

    def resize(self, size):
        self.width, self.height = max(MIN_SIZE[0], size[0]), max(MIN_SIZE[1], size[1])
        self.screen = pygame.Rect(0, 0, self.width, self.height)

        margin = 10
        top_h = 46
        seat_h = 200          # 底部主面板高度（含标题栏）
        top_panel_h = 168     # 上方面板略矮：它的手牌用小一号的牌
        status_h = 26
        btn_row_h = 44
        side_w = int(self.width * 0.235)
        center_w = self.width - 2 * side_w - 2 * margin

        # 底部座位面板：横跨整个窗口宽度，手牌区才放得下 13 张
        bottom_seat = pygame.Rect(margin, self.height - status_h - seat_h - margin,
                                  self.width - 2 * margin, seat_h)
        # 上方座位面板
        top_seat = pygame.Rect(margin, top_h + margin,
                               self.width - 2 * margin, top_panel_h)
        # 中部可用高度
        mid_top = top_seat.bottom + margin
        mid_bottom = bottom_seat.y - margin
        mid_h = max(200, mid_bottom - mid_top)

        # 中央区域（信息栏 + 出牌区 + 按钮行 + 可选日志）
        self.center = pygame.Rect(side_w + margin, mid_top, center_w, mid_h)
        self.info_rect = pygame.Rect(self.center.x, self.center.y, self.center.width, 62)
        field_top = self.info_rect.bottom + 4
        buttons_top_reserved = btn_row_h + 4
        min_log_h = 110 if self.log_open else 0
        # 出牌区高度：日志展开时让出空间，收起时吃满
        field_h = self.center.bottom - field_top - buttons_top_reserved - min_log_h - 8
        field_h = max(140, min(field_h, int(mid_h * 0.72)))
        self.field_rect = pygame.Rect(self.center.x, field_top,
                                      self.center.width, field_h)
        self.buttons_top = self.field_rect.bottom + 8
        log_top = self.buttons_top + btn_row_h
        self.log_rect = pygame.Rect(self.center.x, log_top,
                                    self.center.width,
                                    max(0, self.center.bottom - log_top))
        if not self.log_open:
            self.log_rect = pygame.Rect(self.center.x, log_top, self.center.width, 0)

        # 顶栏
        self.topbar = pygame.Rect(0, 0, self.width, top_h)
        self.btn_menu = pygame.Rect(margin + 4, 9, 78, 28)
        self.btn_new_game = pygame.Rect(margin + 90, 9, 78, 28)
        self.btn_help = pygame.Rect(margin + 176, 9, 78, 28)
        self.btn_log = pygame.Rect(margin + 262, 9, 88, 28)

        # 四个座位面板
        self.seats = {
            BOTTOM: bottom_seat,
            TOP: top_seat,
            LEFT: pygame.Rect(margin, top_seat.bottom + margin, side_w - margin,
                              mid_h),
            RIGHT: pygame.Rect(self.width - side_w, top_seat.bottom + margin,
                               side_w - margin, mid_h),
        }
        self.panel_bottom = bottom_seat.copy()
        self.panel_top = top_seat.copy()
        self.panel_left = self.seats[LEFT]
        self.panel_right = self.seats[RIGHT]
        self.seat_rects = {BOTTOM: self.panel_bottom, TOP: self.panel_top,
                           LEFT: self.panel_left, RIGHT: self.panel_right}

        # 操作按钮行（出牌区下方、日志上方）。
        # 连锁窗口复用同一行：前两个位置换成「连锁出牌 / 放弃连锁」，
        # 后两个位置继续放「AI 代打 / 提示」，保持整行四个按钮（不要凭空少两个）。
        btn_w, btn_h = 118, 34
        gap = 10
        total = btn_w * 4 + gap * 3
        bx = self.center.centerx - total // 2
        by = self.buttons_top
        self.buttons = {
            'end_turn': pygame.Rect(bx, by, btn_w, btn_h),
            'play': pygame.Rect(bx + btn_w + gap, by, btn_w, btn_h),
            'auto': pygame.Rect(bx + 2 * (btn_w + gap), by, btn_w, btn_h),
            'hint': pygame.Rect(bx + 3 * (btn_w + gap), by, btn_w, btn_h),
        }
        self.chain_buttons = {
            'chain_ok': self.buttons['end_turn'].copy(),
            'chain_no': self.buttons['play'].copy(),
            'chain_auto': self.buttons['auto'].copy(),
            'chain_hint': self.buttons['hint'].copy(),
        }

        self.overlay = self.screen.copy()

    def set_log_open(self, opened: bool):
        self.log_open = bool(opened)
        self.resize((self.width, self.height))

    def set_chain_active(self, active: bool):
        self.chain_active = bool(active)

    @property
    def log_visible(self) -> bool:
        return self.log_open and self.log_rect.height > 30

    @property
    def log_line_capacity(self) -> int:
        """日志区能显示多少行"""
        if not self.log_visible:
            return 0
        return max(1, (self.log_rect.height - 30) // 18)

    # ------------------------------------------------------------ 命中测试
    def hit_seat(self, pos):
        """返回被点到的座位名（手牌在面板内）"""
        for seat, rect in self.seat_rects.items():
            if rect.collidepoint(pos):
                return seat
        return None

    def hit_button(self, pos):
        """返回命中的按钮名（顶部按钮 / 操作按钮 / 连锁按钮），没命中返回 None。

        连锁按钮与普通按钮共用同一行，连锁窗口打开时优先命中连锁按钮。
        """
        if self.chain_active:
            for name, rect in self.chain_buttons.items():
                if rect.collidepoint(pos):
                    return name
        for name, rect in self.buttons.items():
            if rect.collidepoint(pos):
                return name
        if self.btn_menu.collidepoint(pos):
            return 'menu'
        if self.btn_new_game.collidepoint(pos):
            return 'new_game'
        if self.btn_help.collidepoint(pos):
            return 'help'
        if self.btn_log.collidepoint(pos):
            return 'toggle_log'
        return None

    # ------------------------------------------------------------ 手牌布局
    def card_size(self, seat: str):
        """每个座位的牌尺寸：侧边与上方面板更窄/矮，用略小的牌"""
        area = self.seat_rects[seat]
        if seat in (LEFT, RIGHT):
            w = min(CARD_W + 14, area.width - 20)
            h = min(92, max(52, area.height - 110))
            return max(36, w), max(48, h)
        if seat == TOP:
            h = min(96, max(68, area.height - 78))
            return CARD_W, h
        h = min(CARD_H, max(76, area.height - 86))
        return CARD_W, h

    def hand_card_rects(self, seat: str, count: int, selected=None):
        """给某座位的手牌算出一排矩形；一行放不下就折成多行并自动重叠"""
        area = self.seat_rects.get(seat)
        if area is None or count <= 0:
            return []
        pad = 12
        avail = area.width - pad * 2
        card_w, card_h = self.card_size(seat)

        # 一行最多放几张（允许最小 16px 的叠放步长）
        per_row = max(1, (avail - card_w) // 16 + 1)
        per_row = max(1, min(count, per_row))
        head = 34 if seat != BOTTOM else 30
        usable_h = max(card_h, area.height - head - 14)
        max_rows = max(1, (usable_h + 6) // (card_h + 6))
        rows = max(1, min(max_rows, (count + per_row - 1) // per_row))
        per_row = max(1, (count + rows - 1) // rows)

        step = card_w + 6
        if per_row * card_w > avail:
            step = max(12, (avail - card_w) // max(1, per_row - 1))
        row_h = card_h + 6
        block_h = rows * row_h - 6
        y0 = area.bottom - 8 - block_h
        if seat != BOTTOM:
            y0 = max(y0, area.y + head)

        rects = []
        for index in range(count):
            row, col = divmod(index, per_row)
            row_count = min(per_row, count - row * per_row)
            row_w = card_w + step * (row_count - 1)
            start_x = area.centerx - row_w // 2
            start_x = max(area.x + pad, min(start_x, area.right - pad - row_w))
            rects.append(pygame.Rect(start_x + col * step, y0 + row * row_h,
                                     card_w, card_h))
        return rects

    def hit_card(self, seat: str, rects, pos):
        """从右到左命中（右边的牌压在上面）"""
        for idx in range(len(rects) - 1, -1, -1):
            if rects[idx].collidepoint(pos):
                return idx
        return None

    def field_card_rects(self, count: int):
        """出牌区的小牌矩形：按可用高度/宽度自适应行列，保证不出界"""
        if count <= 0:
            return []
        pad_x, pad_y = 16, 28
        avail_w = max(MINI_W, self.field_rect.width - pad_x * 2)
        avail_h = max(MINI_H, self.field_rect.height - pad_y)
        gap = 6
        cols = max(1, min(9, (avail_w + gap) // (MINI_W + gap)))
        rows_needed = (count + cols - 1) // cols
        max_rows = max(1, (avail_h + gap) // (MINI_H + gap))
        if rows_needed > max_rows:
            # 牌太多：缩小牌面并允许更多行，保证所有牌都落在出牌区内
            rows_allowed = max(max_rows, 6)
            target_h = (avail_h - gap * (rows_allowed - 1)) / rows_allowed
            scale = max(0.30, min(1.0, target_h / MINI_H))
            card_w = max(18, int(MINI_W * scale))
            card_h = max(24, int(MINI_H * scale))
            gap = max(2, int(gap * scale))
            cols = max(1, min(9, (avail_w + gap) // (card_w + gap)))
        else:
            card_w, card_h = MINI_W, MINI_H

        rows = max(1, (count + cols - 1) // cols)
        block_h = rows * card_h + (rows - 1) * gap
        if block_h > avail_h:
            scale = avail_h / block_h
            card_w = max(14, int(card_w * scale))
            card_h = max(18, int(card_h * scale))
            gap = max(1, int(gap * scale))
            cols = max(1, min(9, (avail_w + gap) // (card_w + gap)))
            rows = max(1, (count + cols - 1) // cols)
            block_h = rows * card_h + (rows - 1) * gap
        y0 = self.field_rect.centery - block_h // 2
        y0 = max(y0, self.field_rect.y + pad_y // 2)
        rects = []
        for i in range(count):
            r, c = divmod(i, cols)
            row_count = min(cols, count - r * cols)
            row_w = row_count * card_w + (row_count - 1) * gap
            x0 = self.field_rect.centerx - row_w // 2
            rects.append(pygame.Rect(x0 + c * (card_w + gap), y0 + r * (card_h + gap),
                                     card_w, card_h))
        return rects


# ---------------------------------------------------------------- 座位分配
def seat_for(index: int) -> str:
    """静态座位顺序（自己固定在下方）"""
    return [BOTTOM, RIGHT, TOP, LEFT][index % 4]


def seat_map(gm, focus=None):
    """把 4 名玩家分配到四个座位。

    本地热座的关键：把「正在行动 / 正在被操作的玩家」放到下方主面板，
    其余玩家按固定顺序排在左、上、右，这样当前玩家永远面对最大的手牌区。
    """
    players = list(gm.players)
    focus = focus or gm.current_player()
    if focus not in players:
        focus = players[0]
    rest = [p for p in players if p is not focus]
    order = [focus] + rest
    return {player: seat_for(i) for i, player in enumerate(order)}
