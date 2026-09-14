"""界面主题：配色与字体（pygame 图形层，TODO 2）

只在渲染层使用，游戏逻辑不依赖本模块。
"""

import os

import pygame

import enums

# ---------------------------------------------------------------- 配色
COLOR_BG = (18, 46, 34)
COLOR_FELT = (28, 78, 56)
COLOR_FELT_DARK = (20, 58, 42)
COLOR_FELT_LIGHT = (34, 96, 68)
COLOR_PANEL = (24, 34, 42)
COLOR_PANEL_ACTIVE = (36, 62, 72)
COLOR_PANEL_IDLE = (22, 30, 36)
COLOR_BORDER = (98, 130, 116)
COLOR_BORDER_ACTIVE = (255, 206, 84)
COLOR_BORDER_CHAIN = (120, 210, 255)
COLOR_TEXT = (238, 240, 235)
COLOR_TEXT_DIM = (150, 164, 158)
COLOR_TEXT_WARN = (255, 138, 120)
COLOR_GOLD = (255, 206, 84)
COLOR_RED = (206, 54, 62)
COLOR_BLACK = (32, 34, 38)
COLOR_CARD_FACE = (250, 248, 242)
COLOR_CARD_SHADOW = (10, 18, 14)
COLOR_CARD_BACK = (44, 74, 138)
COLOR_CARD_BACK_EDGE = (28, 48, 96)
COLOR_BTN = (58, 88, 104)
COLOR_BTN_HOVER = (78, 116, 134)
COLOR_BTN_ACTIVE = (222, 170, 52)
COLOR_BTN_DISABLED = (54, 60, 62)
COLOR_SELECT = (255, 206, 84)
COLOR_TOAST = (14, 22, 28)
COLOR_TRANSPARENT = (0, 0, 0, 0)

SUIT_COLORS = {
    enums.Suit.HEART: COLOR_RED,
    enums.Suit.DIAMOND: COLOR_RED,
    enums.Suit.SPADE: COLOR_BLACK,
    enums.Suit.CLUB: COLOR_BLACK,
}

# ---------------------------------------------------------------- 字体
_CJK_CANDIDATES = [
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\simsun.ttc',
    r'C:\Windows\Fonts\Deng.ttf',
    '/System/Library/Fonts/PingFang.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
]

_font_path_cache = {'resolved': False, 'path': None}
_font_cache = {}


def cjk_font_path():
    """找一个支持中文的系统字体，找不到返回 None（回落到 pygame 默认字体）"""
    if not _font_path_cache['resolved']:
        path = None
        for candidate in _CJK_CANDIDATES:
            if os.path.exists(candidate):
                path = candidate
                break
        _font_path_cache['resolved'] = True
        _font_path_cache['path'] = path
    return _font_path_cache['path']


def font(size: int, bold: bool = False) -> 'pygame.font.Font':
    """按字号取字体（带缓存）。中文缺失时 pygame 会画成方块，但不会崩溃。"""
    key = (size, bold)
    if key not in _font_cache:
        path = cjk_font_path()
        try:
            _font_cache[key] = pygame.font.Font(path, size) if path else pygame.font.SysFont(None, size)
        except Exception:
            _font_cache[key] = pygame.font.Font(None, size)
        _font_cache[key].set_bold(bold)
    return _font_cache[key]


def _missing_glyph_fingerprint(size: int = 24):
    """很多字体缺少某个字形时，pygame 会画成同一个「豆腐块」。
    这里取几个几乎不可能都存在的私用区码位，得到回退字形的指纹。"""
    font_obj = font(size)
    prints = []
    for cp in (0xE000, 0xE001, 0xE002):
        img = font_obj.render(chr(cp), True, (255, 255, 255))
        prints.append((img.get_size(), pygame.image.tostring(img, 'RGBA')))
    return prints


_FALLBACK_CACHE = {}


def has_glyph(ch: str, size: int = 24) -> bool:
    """判断字体里是否真的有这个字符的字形。

    像 msyh.ttc 并不包含 ♠♥♦♣(U+2660~2663)，pygame 不会报错，
    而是静默画成豆腐块 —— 直接 font.metrics() 也查不出来，
    只能把渲染结果和「确定缺字」的私用区码位做对比。
    """
    key = size
    if key not in _FALLBACK_CACHE:
        _FALLBACK_CACHE[key] = _missing_glyph_fingerprint(size)
    font_obj = font(size)
    try:
        img = font_obj.render(ch, True, (255, 255, 255))
    except Exception:
        return False
    signature = (img.get_size(), pygame.image.tostring(img, 'RGBA'))
    if signature[0] == (0, 0):
        return False
    return signature not in _FALLBACK_CACHE[key]


def suit_color(suit: enums.Suit):
    return SUIT_COLORS[suit]
