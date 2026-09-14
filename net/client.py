"""客户端（TODO 3）

    python net/client.py --host 192.168.1.10 --port 45678 --name 小明

客户端不跑 GameMaster，只做两件事：
1. 收快照 → 转成 TableView → 用 ui.render 渲染（复用本地热座的界面代码）
2. 收集输入 → 打包成 Intent → 可靠发送给主机（ACK 锁保证送达）

因为客户端只操作「一名玩家」，所以界面把视角玩家固定在下方，
其他三家的手牌只显示牌背 —— 这正是 TODO 1 阶段二要的形态。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enums
from net.controller import (intent_chain, intent_decline_chain, intent_end_turn,
                            intent_play)
from net.frames import MsgType
from net.link import ClientLink
from viewmodel import (TableInteraction, TableView, chain_preview,
                       find_all_chains, find_all_plays, find_chain_options,
                       selected_cards)


class GameClient:
    """纯网络层：连接、收快照、发指令（不含图形界面）"""

    def __init__(self, host='127.0.0.1', port=45678, name='玩家',
                 faction=None, timeout=0.30, verbose=True):
        self.link = ClientLink(host, port, timeout=timeout)
        self.name = name
        self.desired_faction = str(faction) if faction else None
        self.verbose = verbose
        self.view: TableView | None = None
        self.you = None                 # 自己的花色（WELCOME 后确定）
        self.pending_stage = None
        self.prompt = ''
        self.your_turn = False
        self.can_chain = False
        self.connected = False
        self.rejected: list = []
        self.events: list = []
        self.hello_sent_at = None
        self.last_snapshot_at = None
        self.rtt = None
        self.received_frames = 0
        self.last_reject = ''

    # ------------------------------------------------------------ 连接
    def connect(self, retry_seconds: float = 5.0, now: float = None):
        """发送 HELLO 并等待 WELCOME"""
        now = now if now is not None else time.monotonic()
        self.hello_sent_at = now
        self.link.send(MsgType.HELLO, {'name': self.name,
                                       'faction': self.desired_faction},
                       need_ack=True)
        deadline = now + retry_seconds
        while not self.connected:
            now = time.monotonic()
            self.link.pump(now)
            for frame, addr in self.link.receive():
                self.handle_frame(frame, now)
            if now > deadline:
                return False
            time.sleep(0.01)
        return True

    def handle_frame(self, frame, now: float = None):
        now = now if now is not None else time.monotonic()
        self.received_frames += 1
        if frame.type == MsgType.WELCOME:
            faction = enums.Suit(frame.data['faction']) if frame.data.get('faction') else None
            if self.connected and faction == self.you:
                return              # 重复的 WELCOME（主机对我们的重发 HELLO 的回应）
            self.you = faction
            self.connected = True
            self.log(f'已加入对局，坐 {self.you.name if self.you else "?"}')
        elif frame.type == MsgType.SNAPSHOT:
            self.apply_snapshot(frame.data, now)
        elif frame.type == MsgType.EVENT:
            event = frame.data.get('event')
            message = frame.data.get('message', '')
            self.events.append((event, message))
            if event == 'rejected':
                self.last_reject = message
            self.log(f'事件 {event}：{message}')
        elif frame.type == MsgType.BYE:
            self.log('主机已关闭对局')
            self.connected = False
        elif frame.type == MsgType.PONG:
            if self.hello_sent_at:
                self.rtt = now - self.hello_sent_at
        elif frame.type == MsgType.WELCOME:
            pass

    def apply_snapshot(self, data: dict, now: float = None):
        now = now if now is not None else time.monotonic()
        view = TableView.from_dict(data)
        if self.view is not None and view.seq and view.seq < self.view.seq:
            return                       # 乱序到达的旧快照，直接丢弃（ACK 锁只保证不丢，不保证顺序）
        self.view = view
        self.last_snapshot_at = now
        self.pending_stage = data.get('pending_stage')
        self.prompt = data.get('prompt', '')
        self.your_turn = bool(data.get('your_turn'))
        self.can_chain = bool(data.get('can_chain'))
        if self.you is None and data.get('you'):
            self.you = enums.Suit(data['you'])

    # ------------------------------------------------------------ 输入
    def submit_play(self, uids):
        self.link.send(MsgType.INTENT, intent_play(uids))
        self.log(f'发送出牌意图（{len(uids)} 张）')

    def submit_end_turn(self):
        self.link.send(MsgType.INTENT, intent_end_turn())

    def submit_chain(self, uids):
        self.link.send(MsgType.INTENT, intent_chain(uids))

    def decline_chain(self):
        self.link.send(MsgType.INTENT, intent_decline_chain())

    def ping(self):
        self.link.send(MsgType.PING, {}, need_ack=False)

    def tick(self):
        """一轮网络收发（图形界面每帧调用一次）"""
        now = time.monotonic()
        for frame, addr in self.link.receive():
            self.handle_frame(frame, now)
        self.link.pump(now)

    def close(self):
        try:
            self.link.send(MsgType.BYE, {'reason': 'client quit'}, need_ack=False)
            self.link.pump()
        except OSError:
            pass
        self.link.close()

    def log(self, msg: str):
        if self.verbose:
            print(f'[client] {msg}', flush=True)

    # ------------------------------------------------------------ 视图辅助
    def my_view(self):
        if self.view is None or self.you is None:
            return None
        return self.view.player_by_faction(self.you)


# ==================================================================== 图形客户端
class NetClientApp:
    """把 GameClient 接到 pygame 界面上"""

    def __init__(self, client: GameClient, window_size=(1280, 800)):
        import pygame

        from ui.layout import Layout
        from ui.render import TableRenderer, seat_map_for

        self.pygame = pygame
        self.client = client
        pygame.init()
        pygame.display.set_caption(f'Poker Horse Racing · 联机 {client.name}')
        self.window = pygame.display.set_mode(window_size, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.layout = Layout(window_size)
        self.renderer = TableRenderer(self.window, self.layout)
        self.state = TableInteraction()
        self.seat_map = {}
        self.running = True
        self.empty_view = TableView(mode='network')
        self.seat_map_for = seat_map_for
        self._last_stage = None      # 用于检测「连锁窗口刚打开」

    def run(self):
        pygame = self.pygame
        self.renderer.set_status('正在连接主机…')
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self.client.tick()
            self.handle_events()
            self.update(dt)
            self.draw()
            pygame.display.flip()
        self.client.close()
        pygame.quit()

    def handle_events(self):
        pygame = self.pygame
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.VIDEORESIZE:
                size = (max(1024, event.w), max(700, event.h))
                self.window = pygame.display.set_mode(size, pygame.RESIZABLE)
                self.renderer.resize(self.window, size)
                self.layout = self.renderer.layout
            elif event.type == pygame.KEYDOWN:
                self.on_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.on_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                self.on_wheel(1 if event.button == 4 else -1)
            elif event.type == pygame.MOUSEWHEEL:
                self.on_wheel(event.y)

    def on_wheel(self, direction: int):
        if self.renderer.show_help or not self.layout.log_visible:
            return
        total = len(self.client.view.log) if self.client.view else 0
        self.renderer.scroll_log(direction * 3, total)

    def on_key(self, event):
        pygame = self.pygame
        total_log = len(self.client.view.log) if self.client.view else 0
        if event.key == pygame.K_ESCAPE:
            if self.renderer.show_help:
                self.renderer.show_help = False
            elif self.state.stage == 'choose_chain':
                self.decline_chain()
            else:
                self.running = False
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.submit_play()
        elif event.key == pygame.K_e:
            self.client.submit_end_turn()
            self.state.applied_action()
        elif event.key == pygame.K_a:
            self.auto_play()
        elif event.key in (pygame.K_h, pygame.K_F1):
            self.renderer.show_help = not self.renderer.show_help
        elif event.key == pygame.K_l:
            opened = self.renderer.toggle_log()
            self.renderer.flash('日志已' + ('展开' if opened else '收起'), 1.4)
        elif event.key == pygame.K_BACKSPACE:
            self.state.clear_selection()
        elif event.key == pygame.K_TAB:
            self.show_hint()
        elif event.key == pygame.K_PAGEUP:
            self.renderer.scroll_log_page(1, total_log)
        elif event.key == pygame.K_PAGEDOWN:
            self.renderer.scroll_log_page(-1, total_log)
        elif event.key == pygame.K_HOME:
            self.renderer.scroll_log(total_log, total_log)
        elif event.key == pygame.K_END:
            self.renderer.log_scroll = 0
        elif event.key == pygame.K_UP:
            self.renderer.scroll_log(1, total_log)
        elif event.key == pygame.K_DOWN:
            self.renderer.scroll_log(-1, total_log)

    def on_click(self, pos):
        button = self.layout.hit_button(pos)
        if button in ('help',):
            self.renderer.show_help = True
            return
        if button == 'play':
            self.submit_play()
            return
        if button == 'end_turn':
            self.client.submit_end_turn()
            self.state.applied_action()
            return
        if button == 'hint':
            self.show_hint()
            return
        if button == 'auto':
            self.auto_play()
            return
        if button == 'chain_ok':
            self.submit_chain()
            return
        if button == 'chain_no':
            self.decline_chain()
            return
        if button == 'chain_hint':
            self.show_hint()
            return
        if button == 'chain_auto':
            self.auto_play()
            return
        if button == 'toggle_log':
            self.renderer.toggle_log()
            return
        if button == 'menu':
            self.renderer.paused = not self.renderer.paused
            return
        if self.renderer.show_help:
            self.renderer.show_help = False
            return
        if self.state.stage not in ('choose_action', 'choose_chain'):
            return
        me = self.client.my_view()
        if me is None:
            return
        seat = self.seat_map.get(me)
        if seat is None:
            return
        rects = self.layout.hand_card_rects(seat, len(me.hand))
        idx = self.layout.hit_card(seat, rects, pos)
        if idx is not None:
            self.state.toggle(me.hand[idx].uid)

    # ---------------------------------------------------------------- 操作
    def submit_play(self):
        if self.state.stage == 'choose_chain':
            self.submit_chain()
            return
        me = self.client.my_view()
        if me is None:
            return
        cards = selected_cards(me, self.state.selected_uids)
        if not cards:
            self.renderer.flash('请先点击手牌选择要出的牌', 2.4)
            return
        self.client.submit_play([c.uid for c in cards])
        self.state.applied_action()
        self.renderer.flash('已发送出牌请求，等待主机确认…', 1.6)

    def submit_chain(self):
        me = self.client.my_view()
        if me is None:
            return
        cards = selected_cards(me, self.state.chain_selected_uids)
        if not cards:
            self.renderer.flash('请选择连锁用的牌，或放弃连锁', 2.4)
            return
        ok, why = chain_preview(cards, self.client.view.previous)
        if not ok:
            self.renderer.flash(f'不满足连锁条件：{why}', 3.0)
            return
        self.client.submit_chain([c.uid for c in cards])
        self.state.applied_chain()
        self.renderer.flash('已发送连锁请求…', 1.6)

    def decline_chain(self):
        self.client.decline_chain()
        self.state.applied_chain()
        self.renderer.flash('已放弃连锁', 1.4)

    def auto_play(self):
        """AI 代打：自己回合让 AI 选一手牌；连锁窗口让 AI 挑一个连锁，挑不出就放弃"""
        me = self.client.my_view()
        if me is None:
            return
        if self.state.stage == 'choose_chain':
            groups = self.state.hint_groups or []
            if not groups and not self._refresh_chain_hints():
                self.decline_chain()
                self.renderer.flash('AI 代打：没有可连锁的组合，放弃连锁', 1.8)
                return
            cards, name, effect = self.state.hint_groups[0]
            self.client.submit_chain([c.uid for c in cards])
            self.state.applied_chain()
            self.renderer.flash(f'AI 代打：连锁 {name}（{len(cards)} 张）{effect}', 2.2)
            return
        options = find_all_plays(me.hand, me.faction)
        if not options:
            self.client.submit_end_turn()
            self.renderer.flash('AI 建议：结束回合', 1.6)
            return
        cards, combo = options[0]
        self.client.submit_play([c.uid for c in cards])
        name = enums.COMBO_CN[combo] if combo else '普通出牌'
        self.renderer.flash(f'AI 建议：{name}（{len(cards)} 张）', 1.8)

    def show_hint(self):
        """提示：列出所有可达成/可连锁的组合，Tab 循环切换"""
        me = self.client.my_view()
        if me is None:
            return
        view = self.client.view
        if self.state.stage == 'choose_chain' and view.previous is not None:
            self._refresh_chain_hints(cycle_only=True)
            return
        if self.state.stage != 'choose_action':
            return
        groups = [(cards, enums.COMBO_CN[combo] if combo else '普通出牌',
                   enums.COMBO_EFFECT_TEXT[combo] if combo else '无附加效果')
                  for cards, combo in find_all_plays(me.hand, me.faction)]
        if not groups:
            self.renderer.flash('没有可用的出牌组合', 2.4)
            return
        self.state.set_hint_groups(groups)
        self.renderer.flash(self.state.hint_label(), 3.0)

    def _refresh_chain_hints(self, cycle_only: bool = False) -> bool:
        """列出所有合法连锁；cycle_only=True 表示在已有清单上继续循环"""
        me = self.client.my_view()
        view = self.client.view
        if me is None or view is None or view.previous is None:
            return False
        if cycle_only and self.state.hint_groups:
            self.state.cycle_hint()
            self.renderer.flash(self.state.hint_label(), 3.0)
            return True
        groups = [(cards, enums.COMBO_CN[combo] if combo else '普通出牌',
                   enums.COMBO_EFFECT_TEXT[combo] if combo else '无附加效果')
                  for cards, combo in find_all_chains(me.hand, view.previous)]
        if not groups:
            self.renderer.flash('本手没有可连锁的组合', 2.4)
            return False
        self.state.set_hint_groups(groups)
        self.renderer.flash(self.state.hint_label(), 3.0)
        return True

    # ---------------------------------------------------------------- 更新
    def update(self, dt):
        if self.renderer.toast_timer > 0:
            self.renderer.toast_timer = max(0.0, self.renderer.toast_timer - dt)
        client = self.client
        if client.view is None:
            self.renderer.set_status('正在连接主机…')
            return
        client.view.mode = 'network'
        self.state.sync_from_host(client.pending_stage, client.prompt)
        # 连锁窗口刚打开时，直接把所有合法连锁列出来（不用先按 Tab）
        if client.pending_stage == 'choose_chain' and self._last_stage != 'choose_chain':
            self._refresh_chain_hints()
        self._last_stage = client.pending_stage
        self.seat_map = self.seat_map_for(client.view, client.my_view().name
                                         if client.my_view() else None)
        if client.last_reject:
            self.renderer.flash(client.last_reject, 3.0)
            client.last_reject = ''
        if client.view.game_over:
            self.renderer.set_status(f'🏆 {client.view.winner_name} 获胜！')
        elif not client.connected:
            self.renderer.set_status('与主机断开连接')
        else:
            pending = len(client.link.lock.pending)
            if pending:
                lag = '' if client.rtt is None else f' · RTT {client.rtt * 1000:.0f}ms'
                self.renderer.set_status(f'待确认 {pending}{lag}')
            else:
                # 同步正常时不占用状态栏，交给渲染层的操作提示
                self.renderer.set_status('')

    def draw(self):
        view = self.client.view or self.empty_view
        me = self.client.my_view()
        self.renderer.draw(view, self.state, self.seat_map, focus=me,
                           is_my_turn=bool(me and me.my_turn),
                           clickable=me is not None)


def main(argv=None):
    parser = argparse.ArgumentParser(description='扑克赛马 · 局域网客户端')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=45678)
    parser.add_argument('--name', default=os.environ.get('USERNAME', '玩家'))
    parser.add_argument('--faction', default=None,
                        choices=[s.name.lower() for s in enums.Suit] + [None])
    parser.add_argument('--headless', action='store_true', help='只连接，不开窗口')
    parser.add_argument('--timeout', type=float, default=0.30, help='ACK 超时（秒）')
    args = parser.parse_args(list(argv) if argv is not None else None)

    client = GameClient(host=args.host, port=args.port, name=args.name,
                        faction=args.faction, timeout=args.timeout)
    if not client.connect():
        print(f'无法连接主机 {args.host}:{args.port}', file=sys.stderr)
        return 1
    if args.headless:
        while client.connected:
            client.tick()
            time.sleep(0.05)
        return 0

    app = NetClientApp(client)
    app.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
