"""游戏逻辑核心（服务端 / 权威状态）

设计原则：
- 单一数据源：所有卡牌移动只走 move_cards()
- 状态与渲染分离：这里只维护 Card.zone 与 Player 状态，不处理可见性
- 玩家输入通过 PlayerController 抽象注入，GameMaster 不关心是本地热座还是网络
"""

from random import Random

import effects as effects_mod
import enums
import rules
from Card import Card
from Player import Player
from zones import DrawPile, Field

DEFAULT_TARGET_SCORE = 30
INITIAL_HAND = 7
DRAW_PER_TURN = 2
HAND_LIMIT = 13
MAX_EVENTS = 400


class GameError(Exception):
    """非法操作（RULES §7.3）：拒绝执行，不消耗资源"""


class GameMaster:
    def __init__(self, controllers: dict = None, target_score: int = DEFAULT_TARGET_SCORE,
                 seed: int = None, interactive_discard: bool = False,
                 allow_self_chain: bool = False):
        self.round = 0
        self.players: list[Player] = []
        self.turn_order: dict[int, Player] = {}
        self.turn_index = 0
        self.phase = enums.Phase.END_PHASE
        self.chain_stack = []          # 效果栈（LIFO），resolve_chain 从尾部弹出
        self.target_score = target_score
        self.seed = seed
        # 专用随机源：给了 seed 就能完全复现发牌与出手顺序（测试依赖这一点）
        self.rng = Random(seed)
        self.winner: Player | None = None
        self.game_over = False
        self.interactive_discard = interactive_discard
        self.allow_self_chain = allow_self_chain

        # 全局区域
        self.draw_pile = DrawPile()
        self.field = Field()

        # 控制器：{Suit: PlayerController}
        self.controllers: dict = dict(controllers or {})
        self.states: dict = {}         # 每名玩家当前待输入状态（供 UI 渲染）

        # 出牌 / 连锁记录
        self.active_play = None        # 当前回合玩家本回合最近一次出牌
        self.chain_open = False        # 是否还有未结算的连锁窗口
        self.chain_plays: list = []    # 连锁宣言（按时间顺序）
        self.play_history: list = []   # 上一手牌信息 {'player','cards','combo','sum'}
        self.pending_events: list = [] # 待 UI 播放的动画事件
        self.events: list = []         # 文本日志
        self.skip_count = 0            # 连续跳过计数（RULES §7.4）
        self._resolving = False

    # ================================================================ 初始化
    def setup(self):
        """创建 4 名玩家、初始化 52 张牌、洗牌、发初始手牌（RULES §3.1）"""
        self.round = 0
        self.turn_index = 0
        self.phase = enums.Phase.END_PHASE
        self.chain_stack.clear()
        self.chain_plays.clear()
        self.play_history.clear()
        self.pending_events.clear()
        self.events.clear()
        self.active_play = None
        self.chain_open = False
        self.winner = None
        self.game_over = False
        self.skip_count = 0

        # 1. 创建玩家（用四种花色代表四家），faction → 控制器
        self.players = [Player(suit, name=f'{enums.SUIT_CN[suit]}家') for suit in enums.Suit]
        for p in self.players:
            p.score = 0
            self.controllers.setdefault(p.faction, None)
            self.states.setdefault(p.faction, {'stage': 'idle'})

        # 2. 随机决定出手顺序
        order = self.rng.sample(self.players, len(self.players))
        self.turn_order = {i: p for i, p in enumerate(order)}

        # 3. 生成 52 张牌入抽牌堆
        self.draw_pile = DrawPile()
        self.field = Field()
        for suit in enums.Suit:
            for rank in enums.Rank:
                self.draw_pile.add(Card(suit, rank, enums.Zone.DRAW_PILE))

        # 4. 洗牌
        self.shuffle_draw_pile()

        # 5. 按出手顺序每人发 7 张
        for i in range(len(self.turn_order)):
            self.draw_cards(self.turn_order[i], INITIAL_HAND)

        # 6. 首位玩家进入抽牌阶段
        self.round = 1
        self._update_turn_flag()
        self.phase = enums.Phase.DRAW_PHASE
        for p in self.players:
            p.can_chain = False
            p.chained_this_turn = False
        self.log(f'=== 第 {self.round} 轮，{self.current_player().name} 的回合 ===')
        return self

    # ================================================================ 日志与事件
    def log(self, text: str):
        self.events.append(f'[R{self.round}][{self.phase.name}] {text}')
        if len(self.events) > MAX_EVENTS:
            del self.events[:len(self.events) - MAX_EVENTS]

    def _emit(self, event: dict):
        self.pending_events.append(event)

    def drain_events(self) -> list:
        out = self.pending_events
        self.pending_events = []
        return out

    # ================================================================ 流程控制
    def current_player(self) -> Player:
        return self.turn_order[self.turn_index]

    def next_round(self):
        self.round += 1
        self.turn_index = 0
        self._update_turn_flag()
        self.phase = enums.Phase.DRAW_PHASE

    def next_turn(self):
        """轮到下一位玩家（RULES §3.2）"""
        self.current_player().end_turn()
        self.turn_index = (self.turn_index + 1) % len(self.turn_order)
        if self.turn_index == 0:
            self.round += 1
        self.active_play = None
        self.chain_plays.clear()
        self.chain_open = False
        self.skip_count = 0
        # 新的回合开始，所有人的「每回合连锁 1 次」额度重置（RULES §5.3）
        for p in self.players:
            p.chained_this_turn = False
            p.declined_chain_this_turn = False
            p.can_chain = False
        self._update_turn_flag()
        self.phase = enums.Phase.DRAW_PHASE  # 新回合从抽牌阶段开始
        self.log(f'=== 第 {self.round} 轮，{self.current_player().name} 的回合 ===')

    def _update_turn_flag(self):
        for p in self.players:
            p.my_turn = False
        self.current_player().begin_turn()
        self._refresh_chain_flags()

    def _refresh_chain_flags(self):
        """刷新 can_chain：连锁窗口打开、非当前玩家、本回合未连锁过、且手牌确实可连锁"""
        prev = self.active_play
        for p in self.players:
            if (not self.chain_open or p.my_turn or p.chained_this_turn or prev is None):
                p.can_chain = False
                continue
            if p.declined_chain_this_turn:
                # 本回合已经明确放弃过连锁，就不要再弹窗打扰（RULES §5.3 每回合 1 次）
                p.can_chain = False
                continue
            p.can_chain = bool(rules.find_chains(p.hand, prev.cards, prev.combo))

    def next_phase(self):
        """推进阶段；返回推进后的阶段（END_PHASE 的结算由 end_turn 负责）"""
        if self.game_over:
            return self.phase
        self.phase = enums.Phase((self.phase + 1) % len(enums.Phase))
        return self.phase

    # ================================================================ 抽牌
    def draw_cards(self, player: Player, number: int = 1) -> list:
        """从抽牌堆顶部抽 number 张牌到玩家手牌。

        牌库不足时按 RULES §7.1 依次把 FIELD、弃牌洗回抽牌堆。
        """
        drawn = []
        for _ in range(max(0, number)):
            if not self.draw_pile.cards:
                if not self._recycle_to_draw_pile():
                    self.log('抽牌堆与出牌区均已耗尽，无法继续抽牌')
                    break
            cards = self.draw_pile.draw_many(1)
            if not cards:
                break
            card = cards[0]
            self.field.remove(card)
            card.change_zone(enums.Zone.HAND)
            player.hand.add(card)
            drawn.append(card)
        return drawn

    def _recycle_to_draw_pile(self) -> bool:
        """把 FIELD（含弃牌）洗回抽牌堆；成功返回 True"""
        recycled = self.field.clear()
        for card in recycled:
            card.change_zone(enums.Zone.DRAW_PILE)
        if not recycled:
            return False
        self.draw_pile.extend(recycled)
        self.shuffle_draw_pile()
        self.log(f'出牌区 {len(recycled)} 张牌洗回抽牌堆')
        self._emit({'type': 'recycle', 'count': len(recycled)})
        return True

    def shuffle_draw_pile(self):
        self.rng.shuffle(self.draw_pile.cards)

    # ================================================================ 卡牌移动
    def _get_zone(self, zone: enums.Zone, player: Player = None):
        """根据 Zone 枚举和玩家找到实际容器"""
        if zone == enums.Zone.DRAW_PILE:
            return self.draw_pile
        if zone == enums.Zone.FIELD:
            return self.field
        if zone == enums.Zone.HAND:
            if player is None:
                raise ValueError('HAND 区域需要指定玩家')
            return player.hand
        raise ValueError(f'未知区域: {zone}')

    def move_cards(self, cards: list[Card], to_zone: enums.Zone, to_player: Player = None):
        """从卡牌当前所在区域移动到目标区域（单一数据源）"""
        target = self._get_zone(to_zone, to_player)
        for card in cards:
            src = self._find_zone_of(card)
            if src is not None:
                src.remove(card)
            if card not in target.cards:
                target.add(card)
            card.change_zone(to_zone)

    def _find_zone_of(self, card: Card):
        """在所有区域中查找卡牌所在容器"""
        if card in self.draw_pile.cards:
            return self.draw_pile
        if card in self.field.cards:
            return self.field
        for p in self.players:
            if card in p.hand.cards:
                return p.hand
        return None

    # ================================================================ 阶段一：抽牌
    def begin_turn_draw(self) -> list:
        """当前玩家执行抽牌阶段：抽 2 张后自动进入出牌阶段"""
        if self.game_over:
            return []
        if self.phase != enums.Phase.DRAW_PHASE:
            raise GameError(f'当前不是抽牌阶段（当前 {self.phase.name}）')
        player = self.current_player()
        drawn = self.draw_cards(player, DRAW_PER_TURN)
        self.log(f'{player.name} 抽 {len(drawn)} 张牌')
        self._emit({'type': 'draw', 'player': player, 'cards': drawn})
        self.phase = enums.Phase.PLAY_PHASE
        return drawn

    # ================================================================ 阶段二：出牌
    def validate_play(self, player: Player, cards: list[Card], as_chain: bool = False) -> enums.ComboType | None:
        """出牌合法性校验（RULES §4.2 / §7.3），返回组合技类型（普通出牌为 None）"""
        if self.game_over:
            raise GameError('对局已结束')
        if self.phase != enums.Phase.PLAY_PHASE:
            raise GameError(f'只能在出牌阶段出牌（当前 {self.phase.name}）')
        if not cards:
            raise GameError('未选择任何卡牌')
        cards = list(cards)
        if len(set(cards)) != len(cards):
            raise GameError('同一张牌不能重复打出')
        for card in cards:
            if not player.owns(card):
                raise GameError(f'{card} 不在 {player.name} 的手牌中')

        if player.my_turn:
            if as_chain:
                raise GameError('自己的回合直接出牌即可，无需连锁')
            return rules.detect_combo(cards)

        # 连锁：必须处于连锁窗口
        if not as_chain:
            raise GameError(f'当前是 {self.current_player().name} 的回合，非当前玩家需发动连锁')
        if self.allow_self_chain is False and player is self.current_player():
            raise GameError('不能连锁自己的出牌')
        if player.chained_this_turn:
            raise GameError('每回合每人最多连锁 1 次')
        if self.active_play is None:
            raise GameError('当前没有可连锁的出牌')
        prev = self.active_play
        combo = rules.detect_combo(cards)
        if not rules.can_chain(cards, prev.cards, prev.combo, combo):
            raise GameError('不满足连锁条件（花色相同 / 花色相反 / 点数之和相同或更大）')
        return combo

    def play_cards(self, player: Player, cards: list[Card]):
        """出牌入口（RULES §4.2）。

        当前回合玩家：普通出牌，建立本回合的 active_play。
        其他玩家：连锁宣言，压入连锁栈。
        """
        if player.my_turn:
            return self._play_active(player, cards)
        return self.declare_chain(player, cards)

    def _play_active(self, player: Player, cards: list[Card]):
        combo = self.validate_play(player, cards, as_chain=False)

        self.move_cards(cards, enums.Zone.FIELD)
        self.play_history.append({'player': player, 'cards': list(cards), 'combo': combo,
                                  'sum': rules.points_sum(cards)})
        play = effects_mod.ChainPlay(player, cards, combo, is_chain=False)
        self.active_play = play
        self.chain_open = True   # 开放连锁窗口
        self.chain_stack.extend(self._build_effects(play, prev_sum=0))

        self.log(f'{player.name} 打出 {" ".join(c.text_name for c in cards)}'
                 f'（{enums.COMBO_CN[combo] if combo else "普通出牌"}）')
        self._emit({'type': 'play', 'player': player, 'cards': list(cards),
                    'combo': combo, 'is_chain': False})
        self._refresh_chain_flags()
        return play

    def declare_chain(self, player: Player, cards: list[Card] = None):
        """连锁宣言（RULES §4.4 / §5.3）。

        cards 为 None 表示玩家明确放弃连锁 —— 记下这个决定，
        本回合不再向他重复弹出连锁询问（每回合 1 次连锁额度，§5.3）。
        """
        if cards is None:
            player.declined_chain_this_turn = True
            player.can_chain = False
            self.log(f'{player.name} 放弃连锁（本回合不再询问）')
            self._emit({'type': 'decline_chain', 'player': player})
            return None
        combo = self.validate_play(player, cards, as_chain=True)
        prev = self.active_play
        self.move_cards(cards, enums.Zone.FIELD)
        player.chained_this_turn = True
        player.can_chain = False
        play = effects_mod.ChainPlay(player, cards, combo, is_chain=True, chain_of=prev)
        self.chain_plays.append(play)
        self.chain_stack.extend(self._build_effects(play, prev_sum=prev.sum))
        self.play_history.append({'player': player, 'cards': list(cards), 'combo': combo,
                                  'sum': rules.points_sum(cards)})
        cond_text = rules.can_chain_detailed(cards, prev.cards)[1]
        self.log(f'{player.name} 连锁 {prev.player.name} 的 '
                 f'{" ".join(c.text_name for c in prev.cards)} → '
                 f'{" ".join(c.text_name for c in cards)}（{cond_text}）')
        self._emit({'type': 'chain', 'player': player, 'cards': list(cards),
                    'combo': combo, 'is_chain': True, 'condition': cond_text})
        return play

    # ---------------------------------------------------------- 效果生成
    def _build_effects(self, play: effects_mod.ChainPlay, prev_sum: int = 0) -> list:
        """按 RULES §6 生成一次出牌的全部效果。

        压栈顺序即 LIFO 结算顺序：打断（§6.1 要求先入栈）→ 基础加分 → 组合技效果。
        """
        player = play.player
        cards = play.cards
        combo = play.combo
        out = []

        # 1. 打断：他人回合打出「当前回合玩家阵营花色」且点数之和大于上一手
        if rules.is_interrupt(cards, player.faction, self.current_player().faction,
                              player.my_turn, prev_sum):
            eff = effects_mod.InterruptEffect(player, source_cards=cards, prev_sum=prev_sum)
            out.append(eff)
            self.log(f'{player.name} 触发【打断】')

        # 2. 基础加分：自己回合打出自己阵营花色的牌，每张 +1 分
        if player.my_turn:
            faction_cards = [c for c in cards if c.suit == player.faction]
            if faction_cards:
                out.append(effects_mod.ScoreEffect(
                    player, len(faction_cards), reason='阵营花色加分', source_cards=cards))
            else:
                self.log(f'{player.name} 未打出阵营花色，本次不加分')

        # 3. 组合技附加效果
        if combo is not None:
            combo_effects = effects_mod.build_combo_effects(combo, player, cards, self)
            combo_effects.sort(key=lambda e: 0 if e.kind != 'discard' else 1)
            out.extend(combo_effects)
        elif not player.my_turn:
            self.log(f'{player.name} 的连锁不构成组合技，无附加效果')

        play.effects.extend(out)
        for eff in out:
            eff.turn_stamp = self.round
        return out

    # ================================================================ 连锁结算
    def find_interrupt_target(self, owner: Player):
        """找到被【打断】无效化的目标：连锁栈中最靠上、由其他玩家持有的未结算加分效果"""
        for eff in reversed(self.chain_stack):
            if eff.kind == 'score' and not eff.resolved and not eff.negated and eff.owner is not owner:
                return eff
        return None

    def resolve_chain(self):
        """后进先出结算（RULES §4.4）"""
        if self.game_over:
            return []
        self._resolving = True
        events = []
        self.log('--- 连锁结算（LIFO）---')
        while self.chain_stack and not self.game_over:
            eff = self.chain_stack.pop()
            events.extend(eff.resolve(self) or [])
            self.check_victory()
        self._resolving = False

        # 结算完毕：关闭连锁窗口，本次出牌与连锁的全部效果已生效
        # （规则上本回合该玩家完成了出牌，接下来只能选择结束回合 —— RULES §3.3.2）
        self.chain_open = False
        self.chain_plays = []
        self.active_play = None
        for p in self.players:
            p.can_chain = False
        self.phase = enums.Phase.PLAY_PHASE
        self._emit({'type': 'chain_resolved'})
        return events

    # ================================================================ 弃牌
    def request_discard(self, player: Player, number: int) -> list:
        """请求玩家弃牌（RULES §4.5），弃牌进入 FIELD"""
        number = min(number, len(player.hand))
        if number <= 0:
            return []
        controller = self.controllers.get(player.faction)
        picked = []
        if controller is not None and hasattr(controller, 'choose_discard'):
            picked = list(controller.choose_discard(self, player, number) or [])
        # 兜底：从手牌中依次补足（不改变选牌顺序以外的手牌排列）
        picked = [c for c in picked if player.owns(c)]
        for card in player.hand:
            if len(picked) >= number:
                break
            if card not in picked:
                picked.append(card)
        picked = picked[:number]
        self.move_cards(picked, enums.Zone.FIELD)
        self._emit({'type': 'discard', 'player': player, 'cards': picked})
        return picked

    # ================================================================ 结束回合
    def skip_turn(self, player: Player):
        """当前玩家跳过出牌阶段"""
        if not player.my_turn:
            raise GameError('只有当前回合玩家可以跳过')
        if self.phase != enums.Phase.PLAY_PHASE:
            raise GameError(f'当前不是出牌阶段（{self.phase.name}）')
        self.skip_count += 1
        self.log(f'{player.name} 跳过出牌（连续跳过 {self.skip_count} 次）')
        self._emit({'type': 'skip', 'player': player})
        self.end_turn()

    def end_turn(self):
        """进入结束阶段并推进到下一位玩家"""
        if self.game_over:
            return
        self.phase = enums.Phase.END_PHASE
        self._run_end_phase()
        if not self.game_over:
            self.next_turn()

    # ---------------------------------------------------------- END_PHASE
    def _run_end_phase(self):
        """RULES §3.3.3：清场 → 手牌上限 → 胜负判定"""
        # 1. FIELD 上的牌洗回抽牌堆
        recycled = self.field.clear()
        for card in recycled:
            card.change_zone(enums.Zone.DRAW_PILE)
        if recycled:
            self.draw_pile.extend(recycled)
            self.shuffle_draw_pile()
            self.log(f'结束阶段：出牌区 {len(recycled)} 张牌洗回抽牌堆')
            self._emit({'type': 'recycle', 'count': len(recycled)})

        # 2. 手牌上限 13
        for p in self.players:
            if len(p.hand) > HAND_LIMIT:
                self.log(f'{p.name} 手牌超过 {HAND_LIMIT} 张，弃牌')
                self.request_discard(p, len(p.hand) - HAND_LIMIT)

        # 3. 胜负判定
        self.check_victory()
        if not self.game_over:
            for p in self.players:
                p.chained_this_turn = False
                p.declined_chain_this_turn = False
                p.can_chain = False

    # ================================================================ 胜负
    def check_victory(self) -> Player | None:
        """RULES §1.2：率先达到目标分数者获胜；同分则并列（取最高分者）"""
        if self.game_over:
            return self.winner
        candidates = [p for p in self.players if p.score >= self.target_score]
        if candidates:
            best = max(p.score for p in candidates)
            winners = [p for p in candidates if p.score == best]
            self.game_over = True
            self.winner = winners[0]
            if len(winners) > 1:
                self.log(f'平局：{"、".join(p.name for p in winners)} 同为 {best} 分')
            else:
                self.log(f'🏆 {self.winner.name} 达到 {best} 分，获胜！')
            self._emit({'type': 'game_over', 'winner': self.winner})
        return self.winner

    def declare_victory(self, player: Player):
        self.game_over = True
        self.winner = player
        self.log(f'{player.name} 玩家胜利！')

    # ================================================================ 查询辅助
    @property
    def last_play(self):
        return self.play_history[-1] if self.play_history else None

    def is_hand_visible_to(self, player: Player, viewer: Player = None) -> bool:
        """手牌可见性（RULES §2.2）：只有自己看得见自己的手牌。

        viewer=None 表示本地热座 / 上帝视角，此时全部可见。
        """
        return viewer is None or viewer is player

    def pending_previous_play(self):
        """连锁时需要参照的「上一手牌」：最新的连锁，否则当前回合玩家的出牌"""
        if self.chain_plays:
            last = self.chain_plays[-1]
            return {'player': last.player, 'cards': last.cards, 'combo': last.combo,
                    'sum': last.sum}
        if self.active_play is not None:
            return {'player': self.active_play.player, 'cards': self.active_play.cards,
                    'combo': self.active_play.combo, 'sum': self.active_play.sum}
        return None

    def all_plays_this_turn(self) -> list:
        """本回合已经发生的全部出牌（含连锁），用于界面展示"""
        out = []
        if self.active_play is not None:
            out.append(self.active_play)
        out.extend(self.chain_plays)
        return out

    # ================================================================ 对外快照
    def to_snapshot(self, viewer: Player = None) -> dict:
        """状态快照：状态与渲染分离（README 关键技术要点 3）。

        viewer 为 None 时按「上帝视角」输出全部手牌（本地热座用）。
        """
        return {
            'round': self.round,
            'phase': self.phase.name,
            'game_over': self.game_over,
            'winner': self.winner.name if self.winner else None,
            'target_score': self.target_score,
            'turn': self.current_player().name,
            'turn_faction': str(self.current_player().faction),
            'draw_pile': len(self.draw_pile),
            'field': [c.to_dict() for c in self.field],
            'players': [
                p.to_dict(reveal_hand=(viewer is None or p is viewer))
                for p in self.players
            ],
        }
