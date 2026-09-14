"""基础绘制组件（pygame 图形层，TODO 2）"""

import pygame

import enums
from ui import theme


# ---------------------------------------------------------------- 基础
def rounded(surface, rect, color, radius=8, width=0):
    pygame.draw.rect(surface, color, rect, width, border_radius=radius)


def shadow(surface, rect, offset=3, alpha=90, radius=8):
    shade = pygame.Surface((rect.width + offset * 2, rect.height + offset * 2), pygame.SRCALPHA)
    pygame.draw.rect(shade, (0, 0, 0, alpha), shade.get_rect(), border_radius=radius)
    surface.blit(shade, (rect.x - offset, rect.y - offset + 2))


def text(surface, content, pos, size=18, color=theme.COLOR_TEXT, bold=False,
         center=False, right=False, shadow=False):
    """绘制一行文字，返回其矩形"""
    font = theme.font(size, bold)
    img = font.render(str(content), True, color)
    rect = img.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.topright = pos
    else:
        rect.topleft = pos
    if shadow:
        dark = font.render(str(content), True, (0, 0, 0))
        surface.blit(dark, (rect.x + 1, rect.y + 1))
    surface.blit(img, rect)
    return rect


def wrap_text(content, size, color, max_width, bold=False):
    """按像素宽度折行（中文按字符折行即可）"""
    font = theme.font(size, bold)
    lines, current = [], ''
    for ch in str(content):
        if ch == '\n':
            lines.append(current)
            current = ''
            continue
        if font.size(current + ch)[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current:
        lines.append(current)
    return [(line, font.render(line, True, color)) for line in lines]


# ---------------------------------------------------------------- 花色图形
# 说明：很多中文字体（如 msyh.ttc）并不包含 ♠♥♦♣ (U+2660~U+2663)，
# pygame 找不到字形时会静默画成豆腐块，四种花色看起来完全一样。
# 因此花色统一用几何图形绘制，不依赖任何字体。
SUIT_PIP_SHAPES = ('spade', 'heart', 'diamond', 'club')

SUIT_SHAPE = {
    enums.Suit.SPADE: 'spade',
    enums.Suit.HEART: 'heart',
    enums.Suit.DIAMOND: 'diamond',
    enums.Suit.CLUB: 'club',
}


def draw_suit(surface, suit, center, size, color):
    """在 center 处画一个高约 size 的花色图形（矢量绘制，与字体无关）"""
    shape = SUIT_SHAPE.get(suit, 'spade')
    cx, cy = int(center[0]), int(center[1])
    h = max(8, int(size))
    w = max(6, int(h * 0.86))
    top = cy - h // 2
    bottom = top + h
    left = cx - w // 2
    right = left + w

    if shape == 'spade':
        # 两个圆弧构成的心形倒置 + 梯形柄
        pygame.draw.polygon(surface, color, [
            (cx, top),
            (left + w // 6, top + int(h * 0.30)),
            (left + w // 4, top + int(h * 0.52)),
            (left, top + int(h * 0.56)),
            (left, top + int(h * 0.62)),
            (left + w // 4, top + int(h * 0.62)),
            (cx, top + int(h * 0.80)),
            (right - w // 4, top + int(h * 0.62)),
            (right, top + int(h * 0.62)),
            (right, top + int(h * 0.56)),
            (right - w // 4, top + int(h * 0.52)),
            (right - w // 6, top + int(h * 0.30)),
        ])
        pygame.draw.circle(surface, color, (cx - w // 4, top + int(h * 0.28)), max(2, w // 4))
        pygame.draw.circle(surface, color, (cx + w // 4, top + int(h * 0.28)), max(2, w // 4))
        pygame.draw.polygon(surface, color, [
            (cx - w // 6, top + int(h * 0.78)),
            (cx + w // 6, top + int(h * 0.78)),
            (cx + w // 3, bottom),
            (cx - w // 3, bottom),
        ])
    elif shape == 'heart':
        pygame.draw.circle(surface, color, (cx - w // 4, top + int(h * 0.30)), max(3, w // 4))
        pygame.draw.circle(surface, color, (cx + w // 4, top + int(h * 0.30)), max(3, w // 4))
        pygame.draw.polygon(surface, color, [
            (left, top + int(h * 0.30)),
            (cx, bottom),
            (right, top + int(h * 0.30)),
        ])
    elif shape == 'diamond':
        pygame.draw.polygon(surface, color, [
            (cx, top), (right, cy), (cx, bottom), (left, cy),
        ])
    else:  # club
        r = max(2, w // 4)
        pygame.draw.circle(surface, color, (cx - r, top + r + int(h * 0.20)), r)
        pygame.draw.circle(surface, color, (cx + r, top + r + int(h * 0.20)), r)
        pygame.draw.circle(surface, color, (cx, top + r), r)
        pygame.draw.polygon(surface, color, [
            (cx - w // 6, top + int(h * 0.55)),
            (cx + w // 6, top + int(h * 0.55)),
            (cx + w // 3, bottom),
            (cx - w // 3, bottom),
        ])


# ---------------------------------------------------------------- 卡牌
def draw_card(surface, rect, card=None, face_up=True, selected=False, highlight=None,
              dim=False, scale_corner=True):
    """绘制一张牌。card=None 或 face_up=False 时画牌背。

    牌面排布（从简，避免重叠）：
      左上角：点数 + 小花色
      正中  ：大花色（略微下移，与左上角分居上下两半）
      右下角：倒置点数（只在大牌上画）
    """
    radius = 7
    shadow(surface, rect, offset=3, alpha=80, radius=radius)

    if not face_up or card is None:
        rounded(surface, rect, theme.COLOR_CARD_BACK, radius)
        inner = rect.inflate(-8, -8)
        if inner.width > 6 and inner.height > 6:
            pygame.draw.rect(surface, theme.COLOR_CARD_BACK_EDGE, inner,
                             2, border_radius=5)
            # 网格纹理
            step = max(8, rect.width // 5)
            for x in range(inner.x + step, inner.right, step):
                pygame.draw.line(surface, theme.COLOR_CARD_BACK_EDGE,
                                 (x, inner.y + 2), (x, inner.bottom - 2), 1)
            for y in range(inner.y + step, inner.bottom, step):
                pygame.draw.line(surface, theme.COLOR_CARD_BACK_EDGE,
                                 (inner.x + 2, y), (inner.right - 2, y), 1)
    else:
        face = theme.COLOR_CARD_FACE
        if dim:
            face = (198, 198, 194)
        rounded(surface, rect, face, radius)
        color = theme.suit_color(card.suit)
        if dim:
            color = (140, 140, 138)
        rank_text = enums.RANK_SYMBOL[card.rank]

        if rect.width >= 60:
            # 左上角：点数在上，小花色紧贴其下
            rank_size = max(15, min(24, int(rect.height * 0.22)))
            corner_size = max(11, int(rect.height * 0.17))
            text(surface, rank_text, (rect.x + 8, rect.y + 3), rank_size, color, bold=True)
            draw_suit(surface, card.suit,
                      (rect.x + 9 + rank_size // 2, rect.y + 4 + rank_size + corner_size // 2),
                      corner_size, color)
            # 正中大花色：放在下半部，绝不与左上角重叠
            big_size = int(rect.height * 0.38)
            draw_suit(surface, card.suit, (rect.centerx, rect.y + int(rect.height * 0.62)),
                      big_size, color)
            # 右下角：倒置的花色 + 点数
            text(surface, rank_text, (rect.right - 8, rect.bottom - 4), rank_size, color,
                 bold=True, right=True)
            draw_suit(surface, card.suit,
                      (rect.right - 9 - rank_size // 2, rect.bottom - 6 - rank_size - corner_size // 2),
                      corner_size, color)
        else:
            # 小牌（出牌区）：只留点数 + 一个居中花色
            rank_size = max(11, int(rect.height * 0.20))
            text(surface, rank_text, (rect.x + 4, rect.y + 2), rank_size, color, bold=True)
            draw_suit(surface, card.suit,
                      (rect.centerx, rect.y + int(rect.height * 0.63)),
                      int(rect.height * 0.40), color)

    border = theme.COLOR_BORDER
    width = 1
    if highlight is not None:
        border = highlight
        width = 3
    if selected:
        border = theme.COLOR_SELECT
        width = 3
    pygame.draw.rect(surface, border, rect, width, border_radius=radius)
    return rect


def draw_card_back(surface, rect):
    draw_card(surface, rect, face_up=False)


# ---------------------------------------------------------------- 按钮
class Button:
    def __init__(self, rect, label, key, enabled=True, hint=''):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.key = key
        self.enabled = enabled
        self.hint = hint
        self.hover = False

    def draw(self, surface):
        if not self.enabled:
            color = theme.COLOR_BTN_DISABLED
            text_color = theme.COLOR_TEXT_DIM
        elif self.hover:
            color = theme.COLOR_BTN_HOVER
            text_color = theme.COLOR_TEXT
        else:
            color = theme.COLOR_BTN
            text_color = theme.COLOR_TEXT
        rounded(surface, self.rect, color, 7)
        pygame.draw.rect(surface, (12, 20, 24), self.rect, 1, border_radius=7)
        text(surface, self.label, self.rect.center, 17, text_color, center=True)

    def hit(self, pos) -> bool:
        return self.enabled and self.rect.collidepoint(pos)


# ---------------------------------------------------------------- 面板
def draw_panel(surface, rect, title, subtitle='', active=False, chain=False,
               accent=None, footer=''):
    bg = theme.COLOR_PANEL_ACTIVE if active else theme.COLOR_PANEL_IDLE
    rounded(surface, rect, bg, 10)
    border = theme.COLOR_BORDER
    width = 1
    if active:
        border, width = theme.COLOR_BORDER_ACTIVE, 3
    elif chain:
        border, width = theme.COLOR_BORDER_CHAIN, 3
    pygame.draw.rect(surface, border, rect, width, border_radius=10)

    bar = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, 30)
    rounded(surface, bar, theme.COLOR_PANEL, 9)
    pygame.draw.rect(surface, theme.COLOR_PANEL, pygame.Rect(bar.x, bar.bottom - 9, bar.width, 9))

    if accent is not None:
        pygame.draw.rect(surface, accent, pygame.Rect(rect.x + 6, bar.y + 7, 16, 16),
                         border_radius=4)
        title_x = rect.x + 28
    else:
        title_x = rect.x + 12
    text(surface, title, (title_x, bar.y + 6), 18, theme.COLOR_TEXT, bold=True)
    if subtitle:
        text(surface, subtitle, (rect.right - 12, bar.y + 9), 15, theme.COLOR_TEXT_DIM,
             right=True)
    if footer:
        text(surface, footer, (rect.x + 12, rect.bottom - 24), 15,
             theme.COLOR_TEXT_DIM)
