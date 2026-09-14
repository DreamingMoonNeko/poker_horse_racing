from enum import Enum, StrEnum, IntEnum
import zones

# contains the suits of the cards
class Suit(StrEnum):
    HEART = 'heart'     # 红桃
    SPADE = 'spade'     # 黑桃
    DIAMOND = 'diamond' # 方片
    CLUB = 'club'       # 梅花

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

# Zone 改用字符串标识，具体容器对象由 GameMaster 管理
class Zone(Enum):
    DRAW_PILE = 'draw_pile'
    FIELD = 'field'
    HAND = 'hand'

# 用IntEnum让phase按值循环遍历
class Phase(IntEnum):
    DRAW_PHASE = 0
    PLAY_PHASE = 1
    END_PHASE = 2
