"""界面数据模型与输入状态机

把「界面需要看到的数据」与「界面能产生的操作」从 GameMaster 里剥出来，
这样同一套数据模型可以同时服务于：
- 本地热座（数据来自本地 GameMaster）
- 局域网客户端（数据来自主机广播的状态快照）

本模块**不依赖 pygame**，所以主机端（net/server.py）也能直接用它生成快照。

关键点：状态与渲染分离（README 关键技术要点 3）——
主机广播的快照里，非视角玩家的手牌只有数量、没有牌面，
渲染层直接把「有数量没牌面」翻译成牌背，不需要关心数据打哪来。
"""

from dataclasses import dataclass, field

import enums
import effects as effects_mod
import rules

# 界面阶段（与 GameMaster 的 Phase 同名的字符串，便于跨进程传输）
PHASE_CN = {
    'DRAW_PHASE': '抽牌阶段',
    'PLAY_PHASE': '出牌阶段',
    'END_PHASE': '结束阶段',
}


# ---------------------------------------------------------------- 视图模型
@dataclass
class CardView:
    uid: int
    suit: enums.Suit | None = None
    rank: enums.Rank | None = None
    hidden: bool = False          # 牌背（对手手牌）
    zone: str | None = None

    @property
    def symbol(self) -> str:
        """形如 A♠ 的短名。

        注意：很多中文字体没有 ♠♥♦♣ 字形，所以界面上的日志/提示不要直接用
        这个字符串，请用 suit_cn；卡牌牌面本身由 ui.widgets.draw_suit 矢量绘制。
        """
        if self.hidden or self.suit is None or self.rank is None:
            return '??'
        return f'{enums.RANK_SYMBOL[self.rank]}{enums.SUIT_SYMBOL[self.suit]}'

    @property
    def text_name(self) -> str:
        """只用必然存在的字符：形如 红桃A / 黑桃10"""
        if self.hidden or self.suit is None or self.rank is None:
            return '未知'
        return f'{enums.SUIT_CN[self.suit]}{enums.RANK_SYMBOL[self.rank]}'

    @classmethod
    def from_dict(cls, data: dict) -> 'CardView':
        if 'suit' not in data:
            return cls(uid=data.get('uid', -1), hidden=True)
        return cls(uid=data['uid'],
                   suit=enums.Suit(data['suit']),
                   rank=enums.Rank(data['rank']),
                   hidden=False,
                   zone=data.get('zone'))

    def as_card(self):
        """转成规则层使用的 Card，并保留 uid（这样按 uid 能回查到界面上的牌）"""
        if self.hidden or self.suit is None or self.rank is None:
            return None
        from Card import Card
        card = Card(self.suit, self.rank, enums.Zone.HAND)
        card.uid = self.uid
        return card


def to_cards(card_views) -> list:
    """把一串 CardView 转成 Card（隐藏牌会被跳过）"""
    out = []
    for view in card_views:
        card = view.as_card()
        if card is not None:
            out.append(card)
    return out


@dataclass(eq=False)   # eq=False → 保持按对象身份哈希，可直接做字典键（座位映射）
class PlayerView:
    name: str
    faction: enums.Suit
    score: int = 0
    hand_size: int = 0
    ack: int = 0
    hand: list = field(default_factory=list)   # list[CardView]
    my_turn: bool = False
    can_chain: bool = False
    is_viewer: bool = False
    is_ai: bool = False
    connected: bool = True

    @classmethod
    def from_dict(cls, data: dict, is_viewer: bool = False) -> 'PlayerView':
        hand = [CardView.from_dict(c) for c in data.get('hand', [])]
        view = cls(
            name=data['name'],
            faction=enums.Suit(data['faction']),
            score=data.get('score', 0),
            hand_size=data.get('hand_size', len(hand)),
            ack=data.get('ack', 0),
            hand=hand,
            my_turn=data.get('my_turn', False),
            can_chain=data.get('can_chain', False),
            is_viewer=is_viewer,
            is_ai=data.get('is_ai', False),
            connected=data.get('connected', True),
        )
        return view


@dataclass
class PlayView:
    """一次出牌（含连锁）"""
    player_name: str
    cards: list = field(default_factory=list)
    combo: str | None = None
    combo_cn: str = '普通出牌'
    is_chain: bool = False
    sum: int = 0
    label: str = ''

    @classmethod
    def from_chain_play(cls, play: 'effects_mod.ChainPlay') -> 'PlayView':
        return cls(player_name=play.player.name,
                   cards=[CardView.from_dict(c.to_dict()) for c in play.cards],
                   combo=str(play.combo) if play.combo else None,
                   combo_cn=enums.COMBO_CN[play.combo] if play.combo else '普通出牌',
                   is_chain=play.is_chain,
                   sum=play.sum,
                   label=play.label)

    @classmethod
    def from_dict(cls, data: dict) -> 'PlayView':
        return cls(player_name=data.get('player_name', '?'),
                   cards=[CardView.from_dict(c) for c in data.get('cards', [])],
                   combo=data.get('combo'),
                   combo_cn=data.get('combo_cn', '普通出牌'),
                   is_chain=data.get('is_chain', False),
                   sum=data.get('sum', 0),
                   label=data.get('label', ''))


@dataclass
class TableView:
    """一帧界面需要的全部数据"""
    round: int = 0
    phase: str = 'DRAW_PHASE'
    turn_name: str = ''
    turn_faction: enums.Suit | None = None
    draw_pile: int = 0
    target_score: int = 30
    game_over: bool = False
    winner_name: str | None = None
    players: list = field(default_factory=list)      # list[PlayerView]
    plays: list = field(default_factory=list)        # list[PlayView]，本回合已发生的出牌
    previous: PlayView | None = None                 # 上一手（连锁参照）
    chain_stack: list = field(default_factory=list)  # [{'owner','label'}]
    log: list = field(default_factory=list)
    seq: int = 0
    mode: str = 'local'                              # local / network
    viewer_faction: enums.Suit | None = None

    # ---------- 查询 ----------
    @property
    def phase_cn(self) -> str:
        return PHASE_CN.get(self.phase, self.phase)

    def player_by_faction(self, faction) -> PlayerView | None:
        for p in self.players:
            if p.faction == faction:
                return p
        return None

    def player_by_name(self, name) -> PlayerView | None:
        for p in self.players:
            if p.name == name:
                return p
        return None

    def last_log(self, count: int = 9) -> list:
        return self.log[-count:]

    # ---------- 构造 ----------
    @classmethod
    def from_game_master(cls, gm, viewer=None, mode='local', ack_map=None) -> 'TableView':
        """从本地 GameMaster 生成视图。

        viewer=None  → 上帝视角（本地热座，4 家手牌都可见）
        viewer=玩家  → 该玩家的视角，只有他的手牌有牌面，其余只给 uid（渲染成牌背）
        """
        ack_map = ack_map or {}
        players = []
        for p in gm.players:
            controller = gm.controllers.get(p.faction)
            visible = gm.is_hand_visible_to(p, viewer)
            players.append(PlayerView(
                name=p.name, faction=p.faction, score=p.score,
                hand_size=len(p.hand),
                ack=ack_map.get(p.faction, 0),
                hand=[CardView.from_dict(c.to_dict(reveal=visible)) for c in p.hand],
                my_turn=p.my_turn, can_chain=p.can_chain,
                is_viewer=(viewer is not None and p is viewer),
                is_ai=(getattr(controller, 'kind', '') == 'ai'),
            ))
        plays = [PlayView.from_chain_play(play) for play in gm.all_plays_this_turn()]
        prev = gm.pending_previous_play()
        previous = None
        if prev is not None:
            previous = PlayView(
                player_name=prev['player'].name,
                cards=[CardView.from_dict(c.to_dict()) for c in prev['cards']],
                combo=str(prev['combo']) if prev['combo'] else None,
                combo_cn=enums.COMBO_CN[prev['combo']] if prev['combo'] else '普通出牌',
                is_chain=bool(getattr(prev.get('play'), 'is_chain', False)),
                sum=prev['sum'],
            )
        chain_stack = [{'owner': e.owner.name if e.owner else '?',
                        'label': e.label, 'kind': e.kind} for e in gm.chain_stack]
        return cls(
            round=gm.round, phase=gm.phase.name,
            turn_name=gm.current_player().name,
            turn_faction=gm.current_player().faction,
            draw_pile=len(gm.draw_pile), target_score=gm.target_score,
            game_over=gm.game_over,
            winner_name=gm.winner.name if gm.winner else None,
            players=players, plays=plays, previous=previous,
            chain_stack=chain_stack, log=list(gm.events),
            mode=mode, viewer_faction=viewer.faction if viewer else None,
        )

    @classmethod
    def from_dict(cls, data: dict) -> 'TableView':
        viewer_faction = data.get('viewer_faction')
        viewer_faction = enums.Suit(viewer_faction) if viewer_faction else None
        players = []
        for item in data.get('players', []):
            is_viewer = viewer_faction is not None and enums.Suit(item['faction']) == viewer_faction
            players.append(PlayerView.from_dict(item, is_viewer=is_viewer))
        previous = data.get('previous')
        return cls(
            round=data.get('round', 0),
            phase=data.get('phase', 'DRAW_PHASE'),
            turn_name=data.get('turn_name', ''),
            turn_faction=enums.Suit(data['turn_faction']) if data.get('turn_faction') else None,
            draw_pile=data.get('draw_pile', 0),
            target_score=data.get('target_score', 30),
            game_over=data.get('game_over', False),
            winner_name=data.get('winner_name'),
            players=players,
            plays=[PlayView.from_dict(item) for item in data.get('plays', [])],
            previous=PlayView.from_dict(previous) if previous else None,
            chain_stack=list(data.get('chain_stack', [])),
            log=list(data.get('log', [])),
            seq=data.get('seq', 0),
            mode=data.get('mode', 'network'),
            viewer_faction=viewer_faction,
        )

    def to_dict(self) -> dict:
        return {
            'round': self.round, 'phase': self.phase,
            'turn_name': self.turn_name,
            'turn_faction': str(self.turn_faction) if self.turn_faction else None,
            'draw_pile': self.draw_pile, 'target_score': self.target_score,
            'game_over': self.game_over, 'winner_name': self.winner_name,
            'players': [{
                'name': p.name, 'faction': str(p.faction), 'score': p.score,
                'hand_size': p.hand_size, 'ack': p.ack,
                'hand': [{'uid': c.uid, **({} if c.hidden else
                                           {'suit': str(c.suit), 'rank': int(c.rank),
                                            'zone': c.zone})} for c in p.hand],
                'my_turn': p.my_turn, 'can_chain': p.can_chain,
                'is_ai': p.is_ai, 'connected': p.connected,
            } for p in self.players],
            'plays': [{'player_name': pl.player_name,
                       'cards': [{'uid': c.uid, **({} if c.hidden else
                                                   {'suit': str(c.suit), 'rank': int(c.rank),
                                                    'zone': c.zone})}
                                 for c in pl.cards],
                       'combo': pl.combo, 'combo_cn': pl.combo_cn,
                       'is_chain': pl.is_chain, 'sum': pl.sum,
                       'label': pl.label} for pl in self.plays],
            'previous': None if self.previous is None else {
                'player_name': self.previous.player_name,
                'cards': [{'uid': c.uid, **({} if c.hidden else
                                            {'suit': str(c.suit), 'rank': int(c.rank),
                                             'zone': c.zone})}
                          for c in self.previous.cards],
                'combo': self.previous.combo, 'combo_cn': self.previous.combo_cn,
                'is_chain': self.previous.is_chain, 'sum': self.previous.sum,
                'label': self.previous.label,
            },
            'chain_stack': list(self.chain_stack),
            'log': list(self.log[-40:]),
            'seq': self.seq, 'mode': self.mode,
            'viewer_faction': str(self.viewer_faction) if self.viewer_faction else None,
        }


# ---------------------------------------------------------------- 输入状态机
# 阶段：idle / choose_action / ask_chain / choose_chain
class TableInteraction:
    """界面输入状态机。

    UI 只跟它打交道：点击 → 产出 Intent；Intent 既可以本地直接执行，
    也可以打包成网络消息发给主机（TODO 1 阶段二 / TODO 3）。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.selected_uids: set = set()
        self.chain_selected_uids: set = set()
        self.chain_declined = False
        self.stage = 'idle'
        self.message = ''
        self.hint_cards: list = []
        self.hint_groups: list = []      # [(卡片列表, 组合名, 效果文本), ...]
        self.hint_index = -1             # Tab 在这份清单里循环

    # ---------- 状态切换 ----------
    def begin_choose_action(self):
        self.stage = 'choose_action'
        self.message = ''

    def begin_ask_chain(self):
        self.stage = 'ask_chain'
        self.chain_selected_uids.clear()
        self.chain_declined = False

    def begin_choose_chain(self):
        self.stage = 'choose_chain'
        self.message = ''

    def to_idle(self):
        self.stage = 'idle'
        self.selected_uids.clear()
        self.chain_selected_uids.clear()
        self.hint_cards = []
        self.hint_groups = []
        self.hint_index = -1

    # ---------- 组合技建议清单 ----------
    def set_hint_groups(self, groups):
        """groups: [(卡片列表, 组合名, 效果文本), ...]"""
        self.hint_groups = list(groups)
        self.hint_index = -1
        self.hint_cards = []
        if not self.hint_groups:
            return None
        return self.cycle_hint()

    def cycle_hint(self):
        """切到下一组建议，同时把它选上；返回 (卡片, 组合名, 效果文本)"""
        if not self.hint_groups:
            return None
        self.hint_index = (self.hint_index + 1) % len(self.hint_groups)
        cards, name, effect = self.hint_groups[self.hint_index]
        self.hint_cards = list(cards)
        target = self.chain_selected_uids if self.stage == 'choose_chain' \
            else self.selected_uids
        target.clear()
        target.update(c.uid for c in cards)
        return self.hint_groups[self.hint_index]

    def hint_label(self) -> str:
        if not self.hint_groups or self.hint_index < 0:
            return ''
        cards, name, effect = self.hint_groups[self.hint_index]
        return (f'建议 {self.hint_index + 1}/{len(self.hint_groups)}：'
                f'{name}（{len(cards)} 张）{effect}')

    # ---------- 选择 ----------
    def toggle(self, uid: int):
        target = self.chain_selected_uids if self.stage == 'choose_chain' else self.selected_uids
        if uid in target:
            target.discard(uid)
        else:
            target.add(uid)
        # 手动改动选择 → 结束建议高亮（建议清单仍保留，Tab 可继续循环）
        self.hint_cards = []

    def clear_selection(self):
        if self.stage == 'choose_chain':
            self.chain_selected_uids.clear()
        else:
            self.selected_uids.clear()
        self.hint_cards = []

    def applied_action(self):
        """Intent 被采纳后调用"""
        self.selected_uids.clear()
        self.hint_cards = []
        self.message = ''

    def applied_chain(self):
        self.chain_selected_uids.clear()
        self.hint_cards = []
        self.chain_declined = False
        self.message = ''

    # ---------- 主机提示（联机模式） ----------
    def sync_from_host(self, stage: str, prompt: str = ''):
        """联机时由主机的 pending_stage 驱动本地输入状态"""
        if stage == 'choose_chain':
            if self.stage != 'choose_chain':
                self.begin_choose_chain()
            self.message = prompt or '连锁窗口：选择要连锁的牌'
        elif stage == 'choose_action':
            if self.stage != 'choose_action':
                self.begin_choose_action()
            self.message = prompt or ''
        else:
            if self.stage != 'idle':
                self.to_idle()


def selected_cards(player_view: PlayerView, uids) -> list:
    """按 uid 从玩家视图里取出卡牌（保持手牌顺序）"""
    return [c for c in player_view.hand if c.uid in uids]


def combo_preview(cards) -> tuple:
    """给界面用的组合技预览：返回 (名称, 效果文本)"""
    real = to_cards(cards)
    if len(real) != len(cards):
        return '未知', ''
    combo = rules.detect_combo(real)
    if combo is None:
        return '普通出牌', '无附加效果'
    return enums.COMBO_CN[combo], enums.COMBO_EFFECT_TEXT[combo]


def chain_preview(cards, previous: PlayView) -> tuple:
    """连锁预览：返回 (是否满足, 条件文本)"""
    real = to_cards(cards)
    if len(real) != len(cards) or previous is None:
        return False, '条件不满足'
    prev_real = to_cards(previous.cards)
    if len(prev_real) != len(previous.cards):
        return False, '条件不满足'
    return rules.can_chain_detailed(real, prev_real)


def find_chain_options(hand, previous: PlayView) -> list:
    """枚举手牌里所有可连锁的组合，返回 [(CardView 列表, 组合名), ...]"""
    if previous is None:
        return []
    hand_real = to_cards(hand)
    if len(hand_real) != len(hand):
        return []
    prev_real = to_cards(previous.cards)
    if len(prev_real) != len(previous.cards):
        return []
    by_uid = {c.uid: c for c in hand}
    out = []
    for cards, combo in rules.find_chains(hand_real, prev_real):
        picked = [by_uid.get(c.uid) for c in cards]
        if any(p is None for p in picked):
            continue
        combo_cn = enums.COMBO_CN[combo] if combo else '普通出牌'
        out.append((picked, combo_cn))
    return out


def best_play(hand, faction, is_own_turn: bool = True):
    """给出当前手牌的一个建议（界面「提示」按钮用），返回 CardView 列表"""
    options = find_all_plays(hand, faction)
    return options[0][0] if options else []


def _group_options(hand, groups):
    """把 rules 给出的真实 Card 组合映射回 CardView，并过滤掉映射失败的"""
    by_uid = {c.uid: c for c in hand}
    out = []
    for cards, combo in groups:
        picked = [by_uid.get(c.uid) for c in cards]
        if any(p is None for p in picked):
            continue
        out.append((picked, combo))
    return out


def find_all_plays(hand, faction, limit: int = 40):
    """列出当前手牌可以打出的所有组合（按「组合技优先、张数多、有阵营花色」排序）。

    普通出牌（单张）数量很多，只保留价值最高的若干张，避免刷屏。
    """
    real = to_cards(hand)
    if not real:
        return []
    available = rules.find_plays(real, max_size=5)
    mapped = _group_options(hand, available)

    def score(item):
        cards, combo = item
        value = 100 * (combo is not None)
        value += 10 * sum(1 for c in cards if c.suit == faction)
        value += 6 * len(cards)
        return value

    combos = [item for item in mapped if item[1] is not None]
    combos.sort(key=score, reverse=True)
    singles = [item for item in mapped if item[1] is None]
    singles.sort(key=score, reverse=True)
    singles = singles[:4]          # 普通出牌只给几个建议
    return (combos + singles)[:limit]


def find_all_chains(hand, previous: PlayView, limit: int = 40):
    """列出当前手牌可以发动连锁的所有组合（按组合技优先排序）"""
    if previous is None:
        return []
    hand_real = to_cards(hand)
    if len(hand_real) != len(hand):
        return []
    prev_real = to_cards(previous.cards)
    if len(prev_real) != len(previous.cards):
        return []
    available = rules.find_chains(hand_real, prev_real)
    mapped = _group_options(hand, available)
    mapped.sort(key=lambda item: (item[1] is None, -len(item[0])))
    return mapped[:limit]
