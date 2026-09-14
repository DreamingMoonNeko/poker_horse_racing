"""回合驱动器（状态机）

把 GameMaster 的流程与 PlayerController 的输入连起来。为了配合图形界面，
这里不做阻塞循环，而是提供 step()：每次调用最多推进一步，返回本次的结果。

这样 pyqt / pygame 主循环可以每帧调用一次 step()，界面始终可交互。
"""

import enums
from GameMaster import GameError, GameMaster


class TurnRunner:
    def __init__(self, gm: GameMaster):
        self.gm = gm
        self.chain_depth = 0
        self.current_draw = []
        self.last_result: str | None = None

    # ------------------------------------------------------------ 生命周期
    def reset(self):
        self.chain_depth = 0
        self.current_draw = []
        self.last_result = None

    # ------------------------------------------------------------ 查询
    def controller(self, player):
        return self.gm.controllers.get(player.faction)

    def is_waiting_for_input(self) -> bool:
        """是否卡在等待玩家输入（UI 据此显示提示 / 禁用作弊按钮）"""
        return any(getattr(c, 'pending', None) for c in self.gm.controllers.values()
                   if c is not None)

    def waiting_players(self) -> list:
        out = []
        for p in self.gm.players:
            c = self.controller(p)
            if c is not None and getattr(c, 'pending', None):
                out.append(p)
        return out

    # ------------------------------------------------------------ 主步骤
    def step(self) -> dict:
        """推进一步。返回 {'stage': ..., 'events': [...], 'result': str}"""
        gm = self.gm
        if gm.game_over:
            return self._result('game_over', '对局已结束')

        if gm.phase == enums.Phase.DRAW_PHASE:
            return self._do_draw()

        if gm.phase == enums.Phase.PLAY_PHASE:
            if not gm.chain_open:
                return self._do_active_choice()
            # 已有出牌：先收集连锁，再结算
            status = self._collect_chains()
            if status == 'waiting':
                return self._result('chain_waiting', '等待连锁选择…')
            gm.resolve_chain()
            self.chain_depth = 0
            self._apply_chain_effects_result()
            return self._result('resolved', f'连锁结算完成（{len(gm.chain_plays)} 次连锁）')

        # END_PHASE（正常流程由 end_turn 直接推进，这里是兜底）
        gm.end_turn()
        return self._result('end', '回合结束')

    # ------------------------------------------------------------ DRAW
    def _do_draw(self) -> dict:
        gm = self.gm
        drawn = gm.begin_turn_draw()
        self.current_draw = drawn
        self.chain_depth = 0
        names = ' '.join(c.short_name() for c in drawn) if drawn else '（无牌可抽）'
        return self._result('drew', f'{gm.current_player().name} 抽到 {names}')

    # ------------------------------------------------------------ PLAY
    def _do_active_choice(self) -> dict:
        gm = self.gm
        player = gm.current_player()
        controller = self.controller(player)
        if controller is None:
            gm.end_turn()
            return self._result('error', f'{player.name} 没有控制器，自动跳过')

        action = controller.choose_action(gm, player)
        if action is None:
            return self._result('waiting', f'等待 {player.name} 出牌…')

        if action.kind == 'play':
            try:
                gm.play_cards(player, action.cards)
            except GameError as exc:
                controller.clear_pending()
                self.gm.log(f'非法出牌：{exc}')
                return self._result('illegal', f'非法出牌：{exc}')
            controller.clear_pending()
            self.chain_depth = 0
            return self._result('played', f'{player.name} 打出了 {len(action.cards)} 张牌')

        # 结束回合 / 跳过
        try:
            if action.kind == 'skip':
                gm.skip_turn(player)
            else:
                gm.end_turn()
        except GameError as exc:
            return self._result('illegal', str(exc))
        controller.clear_pending()
        self.chain_depth = 0
        return self._result('turn_end', f'{player.name} 结束回合')

    # ------------------------------------------------------------ 连锁收集
    def _collect_chains(self) -> str:
        """返回 'done' 或 'waiting'。

        每次有人成功连锁后重新开放窗口（连锁可以被再连锁）。
        只要有玩家正在输入（例如人类玩家还没决定），就立刻暂停，
        保证连锁栈的顺序与玩家决策顺序一致。
        """
        gm = self.gm
        if self.chain_depth > 24:
            gm.log('连锁层数达到上限，强制结算')
            return 'done'

        active = gm.active_play.player
        for player in gm.players:
            if player is active or player.chained_this_turn:
                continue
            if not player.can_chain:
                continue
            controller = self.controller(player)
            if controller is None:
                continue
            if not controller.wants_chain(gm, player):
                continue
            cards, combo = controller.choose_chain(gm, player)
            if not cards:
                # 玩家还没选完（人类）→ 整个窗口暂停等待
                if controller.is_waiting():
                    return 'waiting'
                controller.clear_pending()
                continue
            try:
                gm.declare_chain(player, cards)
            except GameError as exc:
                controller.clear_pending()
                gm.log(f'{player.name} 的连锁不合法：{exc}')
                continue
            controller.clear_pending()
            self.chain_depth += 1
            return self._collect_chains()  # 重新开放窗口
        return 'done'

    def _apply_chain_effects_result(self):
        pass

    # ------------------------------------------------------------ 工具
    def _result(self, stage: str, text: str) -> dict:
        self.last_result = text
        return {'stage': stage, 'text': text, 'events': list(self.gm.events[-8:])}


# ---------------------------------------------------------------- 自动对局
def run_auto_game(gm: GameMaster, max_turns: int = 400) -> GameMaster:
    """纯逻辑自走棋（用于测试 / AI 演示），返回结束后的 gm"""
    runner = TurnRunner(gm)
    turns = 0
    while not gm.game_over and turns < max_turns:
        runner.step()
        turns += 1
    return gm
