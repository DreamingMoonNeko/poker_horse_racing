"""无窗口自检（TODO 2）

不打开真实窗口，用 SDL 的 dummy 驱动把图形层跑若干帧，
并模拟「点牌 → 出牌 → 连锁 → 结束回合」的完整点击流程，
用来在没有显示器/显卡的环境里验证界面代码不会崩。

运行：python main.py --selftest
"""

import os


def run_selftest(frames: int = 1500, seed: int = 7, verbose: bool = True) -> int:
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

    import pygame

    import enums
    from controllers import HumanController
    from ui.app import GameApp

    # 1 家真人 + 3 家 AI：既能自动推进，又能走到人类输入分支
    app = GameApp(seed=seed, ai_seats=3, window_size=(1280, 800))
    assert app.gm is not None and len(app.gm.players) == 4

    # 把真人玩家排到第一位出手，保证「出牌 / 结束回合」两条路径在第一轮就被走到
    # （否则随机出手顺序可能让真人排在很后面，1500 帧内轮不到）
    human = next(p for p in app.gm.players
                 if isinstance(app.gm.controllers[p.faction], HumanController))
    order = [human] + [p for p in app.gm.players if p is not human]
    app.gm.turn_order = {i: p for i, p in enumerate(order)}
    app.gm.turn_index = 0
    app.gm._update_turn_flag()
    app.gm.phase = enums.Phase.DRAW_PHASE
    app.refresh_view()

    exercised = {'frames': 0, 'hints': 0, 'plays': 0, 'chains': 0,
                 'declines': 0, 'ends': 0}
    acted_stage = None          # 本轮已经处理过的输入请求
    opportunity = 0             # 累计遇到多少次需要真人决策的机会
    action_opportunity = 0      # 其中「出牌阶段」的机会次数
    last_log_size = len(app.gm.events)
    end_attempted = set()       # 已提交过「结束回合」的 (round, turn_index)
    end_turn_index = app.gm.turn_index

    def new_play_logs():
        """submit_* 只是把决策排队，真正的出牌发生在下一次 runner.step()，
        因此用日志增长来判断动作是否真的执行了。"""
        nonlocal last_log_size
        fresh = app.gm.events[last_log_size:]
        last_log_size = len(app.gm.events)
        plays = sum(1 for line in fresh if '打出' in line)
        # 连锁宣言的日志形如「红桃家 连锁 黑桃家 的 ♦9 → ♦K（点数之和更大）」
        chains = sum(1 for line in fresh if '连锁' in line and '的' in line)
        return plays, chains

    for frame in range(frames):
        app.handle_events()
        app.update(1.0 / 60.0)
        app.draw()
        pygame.display.flip()
        exercised['frames'] += 1

        # 模拟鼠标移动 + 滚轮，覆盖 hover 与翻日志分支
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEMOTION, {'pos': (640, 700), 'rel': (1, 1), 'buttons': (0, 0, 0)}))
        if frame % 7 == 0:
            app.on_wheel(1 if frame % 14 == 0 else -1)

        if app.gm.game_over:
            break

        plays, chains = new_play_logs()
        exercised['plays'] += plays
        exercised['chains'] += chains

        # 「结束回合」是否真的生效：round 单调递增，用它判定最可靠
        if end_attempted:
            done = [key for key in end_attempted
                    if app.gm.round > key[0] or app.gm.game_over]
            if done:
                exercised['ends'] += len(done)
                for key in done:
                    end_attempted.discard(key)
            if app.gm.turn_index != end_turn_index:
                exercised['ends'] += len(end_attempted)
                end_attempted.clear()
        end_turn_index = app.gm.turn_index

        stage = 'choose_chain' if app.chain_mode else app._human_pending_stage()
        if stage is None:
            acted_stage = None
            continue
        if stage == acted_stage:
            continue
        acted_stage = stage
        opportunity += 1

        if stage == 'choose_chain':
            # 每 3 次连锁询问里放弃 1 次、出连锁 2 次
            if opportunity % 3 == 0:
                app.cancel_chain()
                exercised['declines'] += 1
            else:
                app.show_hint()          # 自动选出合法连锁
                exercised['hints'] += 1
                if not app.chain_selected_uids:
                    app.cancel_chain()
                    exercised['declines'] += 1
                else:
                    app.submit_chain()
        else:
            action_opportunity += 1
            # 奇数次机会出牌，偶数次机会结束回合，两条路径都覆盖到
            if action_opportunity % 2 == 1:
                app.show_hint()
                exercised['hints'] += 1
                if app.selected_uids:
                    app.submit_play()
                else:
                    app.submit_end_turn()
                    end_attempted.add((app.gm.round, app.gm.turn_index))
            else:
                app.submit_end_turn()
                end_attempted.add((app.gm.round, app.gm.turn_index))

        # 覆盖帮助 / 暂停 / 收起日志的绘制分支
        if frame == frames // 3:
            app.renderer.show_help = True
        if frame == frames // 3 + 3:
            app.renderer.show_help = False
            app.renderer.paused = True
        if frame == frames // 3 + 6:
            app.renderer.paused = False
            app.renderer.toggle_log()
        if frame == frames // 3 + 12:
            app.renderer.toggle_log()

    rounds_before_restart = app.gm.round
    score_total = sum(p.score for p in app.gm.players)
    app.new_game(seed=seed)  # 重开一局，验证重建流程
    for _ in range(30):
        app.update(1.0 / 60.0)
        app.draw()

    pygame.quit()

    checks = [
        ('图形层跑满帧数', exercised['frames'] == frames),
        ('模拟出牌成功', exercised['plays'] > 0),
        ('模拟结束回合', exercised['ends'] > 0),
        ('模拟连锁或放弃连锁', exercised['chains'] + exercised['declines'] > 0),
        ('有人得分（加分逻辑生效）', score_total > 0),
        ('事件日志非空', len(app.gm.events) > 0),
        ('重开后卡牌总数守恒（52）', _card_count(app.gm) == 52),
        ('重开后回合重置为 1', app.gm.round == 1),
    ]
    if verbose:
        print('=== 无窗口自检 ===')
        for name, passed in checks:
            print(f'  [{"OK" if passed else "FAIL"}] {name}')
        print(f'  帧数={exercised["frames"]} 重开前轮次={rounds_before_restart} '
              f'重开前总分={score_total}')
        print(f'  模拟出牌={exercised["plays"]} 模拟连锁={exercised["chains"]} '
              f'放弃连锁={exercised["declines"]} 模拟结束回合={exercised["ends"]}')
    return 0 if all(passed for _, passed in checks) else 1


def _card_count(gm) -> int:
    total = len(gm.draw_pile) + len(gm.field)
    for p in gm.players:
        total += len(p.hand)
    return total


if __name__ == '__main__':
    raise SystemExit(run_selftest())
