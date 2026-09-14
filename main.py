"""程序入口

    python main.py                 # 启动图形客户端（4 名玩家本地热座输入）
    python main.py --ai 3          # 3 家交给 AI，自己只操作 1 家（推荐单人试玩）
    python main.py --ai 4          # 全 AI 自动演示
    python main.py --seed 42       # 固定随机种子，便于复现
    python main.py --cli           # 不打开窗口，纯文本跑一局（无需显卡）
    python main.py --selftest      # 无窗口自检：驱动图形层若干帧，验证渲染不报错

也可以用项目自带的虚拟环境：.venv\\Scripts\\python.exe main.py
"""

import sys


def run_cli(seed=None, ai_seats=4, target=30, max_steps=8000):
    """纯文本自走一局，用于无图形环境下的验证"""
    import enums
    from GameMaster import GameMaster
    from controllers import AIController
    from turn import TurnRunner

    controllers = {
        suit: AIController(suit, name=f'{enums.SUIT_CN[suit]}AI',
                           seed=None if seed is None else seed * 7 + i)
        for i, suit in enumerate(enums.Suit)
    }
    gm = GameMaster(controllers=controllers, seed=seed, target_score=target)
    gm.setup()
    runner = TurnRunner(gm)
    steps = 0
    while not gm.game_over and steps < max_steps:
        runner.step()
        steps += 1

    print(f'=== 对局结束（{steps} 步，第 {gm.round} 轮）===')
    for line in gm.events[-40:]:
        print(' ', line)
    print('-' * 48)
    for p in gm.players:
        print(f'  {p.name}: {p.score} 分，手牌 {len(p.hand)} 张')
    print(f'  抽牌堆 {len(gm.draw_pile)} 张，出牌区 {len(gm.field)} 张')
    if gm.winner:
        print(f'  🏆 获胜者：{gm.winner.name}')
    else:
        print('  达到步数上限，未分出胜负')
    return 0


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])

    if '--help' in argv or '-h' in argv:
        print(__doc__)
        return 0

    if '--cli' in argv:
        seed = _opt_int(argv, '--seed')
        target = _opt_int(argv, '--target', 30)
        return run_cli(seed=seed, target=target)

    if '--selftest' in argv:
        from selftest import run_selftest
        return run_selftest()

    from ui.app import main as gui_main
    return gui_main(argv)


def _opt_int(argv, flag, default=None):
    if flag in argv:
        idx = argv.index(flag)
        try:
            return int(argv[idx + 1])
        except (IndexError, ValueError):
            return default
    return default


if __name__ == '__main__':
    sys.exit(main())
