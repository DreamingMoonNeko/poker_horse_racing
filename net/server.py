"""主机端联机服务（TODO 3）

主机（房主）跑 GameMaster，客户端只发决策、收快照。流程：

    HELLO ──────────────►  校验协议版本 / 空位 → 落座
          ◄──────────── WELCOME (slot, faction, 玩家列表)
    SNAPSHOT(seq) ──────►  客户端渲染
          ◄──────────── ACK
    INTENT(seq)   ◄──────  玩家点「出牌 / 结束回合 / 连锁」
    ACK           ──────►
          ◄──────────── 下一帧 SNAPSHOT

所有 SNAPSHOT / INTENT 都带序号并要求 ACK（TODO 4），
超时未确认自动重发；重复包由 AckLock 去重。

用法：
    python net/server.py --port 45678 --ai 0 --target 30
"""

import argparse
import select
import socket
import sys
import time

sys.path.insert(0, __file__.rsplit('net', 1)[0].rstrip('\\/'))

import enums
from GameMaster import GameError, GameMaster
from controllers import AIController
from net.frames import MsgType, ProtocolError, decode, encode
from net.link import Peer, UdpLink
from turn import TurnRunner

SNAPSHOT_INTERVAL = 1.0 / 12      # 快照推送频率（12 FPS，足够渲染）
IDLE_TIMEOUT = 12.0               # 多久没收到任何包就认为掉线
MAX_PLAYERS = 4


class GameServer:
    def __init__(self, port: int = 45678, host: str = '0.0.0.0',
                 ai_seats: int = 0, target: int = 30, seed: int = None,
                 verbose: bool = True, snapshot_interval: float = SNAPSHOT_INTERVAL,
                 idle_timeout: float = IDLE_TIMEOUT):
        self.port = port
        self.host = host
        self.verbose = verbose
        self.snapshot_interval = snapshot_interval
        self.idle_timeout = idle_timeout

        self.link = UdpLink(host, port)
        self.host, self.port = self.link.address
        self.peers: dict = {}                # address → Peer
        self.seat_by_faction: dict = {}      # Suit → Peer
        self.ai_seats = ai_seats
        self.target = target
        self.seed = seed

        self.gm = None
        self.runner = None
        self.running = False
        self.last_snapshot = 0.0
        self.tick_count = 0
        self.start_time = time.monotonic()
        self._setup_game()

    # ================================================================ 初始化
    def _setup_game(self):
        controllers = {}
        for i, suit in enumerate(enums.Suit):
            controllers[suit] = AIController(
                suit, name=f'{enums.SUIT_CN[suit]}AI',
                seed=None if self.seed is None else self.seed * 13 + i)
        self.gm = GameMaster(controllers=controllers, seed=self.seed,
                             target_score=self.target)
        self.gm.setup()
        self.runner = TurnRunner(self.gm)

    def log(self, msg: str):
        if self.verbose:
            print(f'[server {time.monotonic() - self.start_time:7.1f}s] {msg}',
                  flush=True)

    # ================================================================ 主循环
    def serve_forever(self):
        self.running = True
        self.log(f'主机已启动：{self.link.address}（等待 {MAX_PLAYERS - self.ai_seats} 名玩家）')
        try:
            while self.running:
                self.tick()
                time.sleep(0.01)
        except KeyboardInterrupt:
            self.log('收到中断，关闭主机')
        finally:
            self.shutdown()
        return 0

    def tick(self, now: float = None):
        """推进一次：收包 → 处理 → 推进一步游戏逻辑 → 广播快照"""
        now = now if now is not None else time.monotonic()
        self.tick_count += 1
        self._receive_all(now)
        self._cull_idle_peers(now)
        self._pump_peers(now)

        if not self.gm.game_over:
            self.runner.step()

        if now - self.last_snapshot >= self.snapshot_interval:
            self.last_snapshot = now
            self.broadcast_snapshot()

        if self.gm.game_over:
            self.broadcast_snapshot()

    # ---------------------------------------------------------------- 收包
    def _receive_all(self, now: float):
        while True:
            try:
                data, addr = self.link.socket.recvfrom(65535)
            except BlockingIOError:
                return
            except OSError as exc:
                self.log(f'接收失败：{exc}')
                return
            self.handle_datagram(data, addr, now)

    def handle_datagram(self, raw: bytes, addr, now: float = None):
        now = now if now is not None else time.monotonic()
        try:
            frame = decode(raw)
        except ProtocolError as exc:
            self.log(f'来自 {addr} 的非法数据包：{exc}')
            return

        peer = self.peers.get(addr)
        if peer is None:
            if frame.type != MsgType.HELLO:
                self.send_event(addr, 'error', '请先发送 HELLO 加入对局')
                return
            peer = self.accept_peer(addr, frame)
            if peer is None:
                return
        peer.touch(now)

        # ACK 处理（所有帧都可能顺带确认）
        if frame.ack:
            peer.lock.ack(frame.ack)
        if not frame.seq:
            return
        if peer.lock.is_duplicate(frame.seq):
            # 重复包：不重复处理，但补发一次 ACK
            self._send_ack(peer)
            return
        peer.lock.mark_received(frame.seq)
        self._send_ack(peer)

        if frame.type == MsgType.INTENT:
            self.handle_intent(peer, frame.data)
        elif frame.type == MsgType.PING:
            self.send(peer, MsgType.PONG, {}, need_ack=False)
        elif frame.type == MsgType.BYE:
            self.drop_peer(peer, reason='玩家主动退出')
        elif frame.type == MsgType.HELLO:
            # HELLO 幂等：客户端可能因为 WELCOME 丢失而重发，这里补发一份
            self.send_welcome(peer)

    def _send_ack(self, peer: Peer):
        frame = peer.lock.make_ack_frame()
        self._write(peer, frame, count=False)

    # ---------------------------------------------------------------- 入座
    def accept_peer(self, addr, frame):
        if frame.version != 1:
            self.send_event(addr, 'error', '协议版本不一致，请更新客户端')
            return None
        free = self.free_slots()
        if not free:
            self.send_event(addr, 'error', '房间已满')
            return None
        requested = frame.data.get('faction')
        faction = None
        if requested:
            try:
                wanted = enums.Suit(requested)
                if wanted in free:
                    faction = wanted
            except ValueError:
                faction = None
        if faction is None:
            faction = free[0]

        peer = Peer(addr, faction, name=frame.data.get('name') or enums.SUIT_CN[faction])
        self.peers[addr] = peer
        self.seat_by_faction[faction] = peer
        # 用 NetworkController 取代 AI 托管
        from net.controller import NetworkController
        self.gm.controllers[faction] = NetworkController(faction, peer)

        self.log(f'{peer.name} 从 {addr} 加入，坐 {enums.SUIT_CN[faction]}')
        self.send_welcome(peer)
        return peer

    def send_welcome(self, peer: Peer):
        self.send(peer, MsgType.WELCOME, {
            'faction': str(peer.faction),
            'name': peer.name,
            'target_score': self.target,
            'players': [{'faction': str(p.faction), 'name': p.name} for p in self.gm.players],
        })

    def free_slots(self) -> list:
        taken = set(self.seat_by_faction)
        return [suit for suit in enums.Suit if suit not in taken]

    def drop_peer(self, peer: Peer, reason: str = '掉线'):
        self.peers.pop(peer.address, None)
        self.seat_by_faction.pop(peer.faction, None)
        # 交回 AI 托管，保证对局能继续
        self.gm.controllers[peer.faction] = AIController(
            peer.faction, name=f'{enums.SUIT_CN[peer.faction]}AI(托管)',
            seed=int(time.monotonic() * 1000) % 99991)
        self.log(f'{peer.name} {reason}，已交给 AI 托管')
        self.broadcast_snapshot(force=True)

    def _cull_idle_peers(self, now: float):
        for peer in list(self.peers.values()):
            if now - peer.last_seen > self.idle_timeout:
                self.drop_peer(peer, reason=f'超时 {self.idle_timeout:.0f}s 未响应')

    # ---------------------------------------------------------------- 玩家指令
    def handle_intent(self, peer: Peer, data: dict):
        controller = self.gm.controllers.get(peer.faction)
        player = self.player_of(peer.faction)
        if player is None or controller is None:
            return
        if not hasattr(controller, 'apply_intent'):
            self.log(f'{peer.name} 的座位当前由 AI 托管，忽略指令')
            return
        try:
            ok, message = controller.apply_intent(self.gm, player, data)
        except GameError as exc:
            ok, message = False, str(exc)
        if not ok:
            self.send_event(peer.address, 'rejected', message)
        if ok:
            self.log(f'{peer.name} 指令 {data.get("kind")} 已采纳')
        self.broadcast_snapshot(force=True)

    def player_of(self, faction):
        for p in self.gm.players:
            if p.faction == faction:
                return p
        return None

    # ---------------------------------------------------------------- 发送
    def _write(self, peer: Peer, frame, count: bool = True):
        try:
            self.link.send_to(frame, peer.address)
        except OSError as exc:
            self.log(f'发送给 {peer.address} 失败：{exc}')
            return False
        if count and frame.seq:
            peer.lock.on_sent(frame.seq)
        return True

    def _pump_peers(self, now: float):
        """把待发队列写出去，并重传超时未确认的帧"""
        for peer in list(self.peers.values()):
            while peer.outbox:
                frame = peer.outbox.popleft()
                self._write(peer, frame)
            for entry in peer.lock.due_for_retransmit(now):
                if not peer.lock.on_retransmit(entry, now):
                    self.log(f'{peer.name} 有消息重传 {entry.attempts} 次仍失败')
                    continue
                self._write(peer, entry.frame, count=False)

    def send(self, peer: Peer, msg_type: str, data: dict = None, need_ack: bool = True):
        frame = peer.lock.build(msg_type, data, need_ack=need_ack)
        peer.outbox.append(frame)
        return frame

    def send_event(self, address, event: str, message: str):
        peer = self.peers.get(address)
        from net.frames import Frame
        frame = Frame(type=MsgType.EVENT, data={'event': event, 'message': message})
        try:
            self.link.send_to(frame, address)
        except OSError:
            pass

    def broadcast_snapshot(self, force: bool = False):
        if not self.peers:
            return
        for peer in list(self.peers.values()):
            snapshot = self.snapshot_for(peer, require_ack=True)
            peer.outbox.append(snapshot)

    def snapshot_for(self, peer: Peer, require_ack: bool = True):
        """生成只对这名玩家可见的快照（状态与渲染分离：别人的手牌只有数量）"""
        from viewmodel import TableView
        viewer = self.player_of(peer.faction)
        view = TableView.from_game_master(
            self.gm, viewer=viewer, mode='network',
            ack_map={suit: p.lock.last_acked for suit, p in self.seat_by_faction.items()})
        data = view.to_dict()
        data['ack'] = peer.lock.last_acked
        data['you'] = str(peer.faction)
        # 主机告知客户端「现在轮到你怎么操作」，客户端据此切换输入状态
        controller = self.gm.controllers.get(peer.faction)
        pending = getattr(controller, 'pending', None) or {}
        data['pending_stage'] = pending.get('stage')
        data['prompt'] = pending.get('prompt', '')
        data['your_turn'] = bool(viewer and viewer.my_turn)
        data['can_chain'] = bool(viewer and viewer.can_chain)
        data['phase'] = self.gm.phase.name
        data['chain_open'] = bool(self.gm.chain_open)
        frame = peer.lock.build(MsgType.SNAPSHOT, data, need_ack=require_ack)
        # 让客户端也能按序号丢弃乱序到达的旧快照
        frame.data['seq'] = frame.seq
        return frame

    # ---------------------------------------------------------------- 收尾
    def shutdown(self):
        self.running = False
        for peer in list(self.peers.values()):
            try:
                self.link.send_to(peer.lock.build(MsgType.BYE, {'reason': 'host closed'},
                                                  need_ack=False), peer.address)
            except OSError:
                pass
        self.link.close()
        self.log('主机已关闭')

    def status(self) -> dict:
        return {
            'uptime': time.monotonic() - self.start_time,
            'round': self.gm.round,
            'phase': self.gm.phase.name,
            'peers': {str(p.faction): p.lock.status() for p in self.peers.values()},
            'ai_seats': [str(p.faction) for p in self.gm.players
                         if p.faction not in self.seat_by_faction],
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description='扑克赛马 · 局域网主机')
    parser.add_argument('--port', type=int, default=45678)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--ai', type=int, default=0, help='预留多少个 AI 座位（0~4）')
    parser.add_argument('--target', type=int, default=30)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(list(argv) if argv is not None else None)

    server = GameServer(port=args.port, host=args.host, ai_seats=args.ai,
                        target=args.target, seed=args.seed, verbose=not args.quiet)
    return server.serve_forever()


if __name__ == '__main__':
    raise SystemExit(main())
