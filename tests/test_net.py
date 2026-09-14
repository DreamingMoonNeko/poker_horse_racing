"""联机层测试（TODO 3 / TODO 4）

- ACK 锁：序号分配、确认、超时重传、重复包去重
- 编解码：Frame 往返
- 端到端：真起一个 GameServer（UDP，随机端口），4 个客户端连接并打完一局
  期间统计重传次数，验证 ACK 锁确实在工作
"""

import os
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enums
from net.acklock import AckLock
from net.client import GameClient
from net.controller import NetworkController
from net.frames import Frame, MsgType, ProtocolError, decode, encode
from net.link import ClientLink
from net.server import GameServer


# ---------------------------------------------------------------- 消息编解码
class TestFrames(unittest.TestCase):
    def test_roundtrip(self):
        frame = Frame(MsgType.INTENT, seq=7, ack=3, data={'kind': 'play', 'uids': [1, 2]})
        back = decode(encode(frame))
        self.assertEqual(back.type, MsgType.INTENT)
        self.assertEqual(back.seq, 7)
        self.assertEqual(back.ack, 3)
        self.assertEqual(back.data['uids'], [1, 2])

    def test_needs_ack(self):
        self.assertTrue(Frame(MsgType.SNAPSHOT, seq=1).needs_ack)
        self.assertFalse(Frame(MsgType.PING).needs_ack)

    def test_decode_rejects_garbage(self):
        with self.assertRaises(ProtocolError):
            decode(b'not json')
        with self.assertRaises(ProtocolError):
            decode(b'[]')
        with self.assertRaises(ProtocolError):
            decode(b'{}')

    def test_chinese_payload_survives(self):
        frame = Frame(MsgType.EVENT, data={'message': '红桃家 打出 ♥A，+1 分'})
        self.assertEqual(decode(encode(frame)).data['message'], '红桃家 打出 ♥A，+1 分')


# ---------------------------------------------------------------- ACK 锁
class TestAckLock(unittest.TestCase):
    def test_sequence_allocation(self):
        lock = AckLock()
        first = lock.build(MsgType.SNAPSHOT, {'a': 1})
        second = lock.build(MsgType.SNAPSHOT, {'a': 2})
        self.assertEqual((first.seq, second.seq), (1, 2))
        self.assertEqual(len(lock.pending), 2)
        # 不需要 ACK 的帧不占序号
        ping = lock.build(MsgType.PING, need_ack=False)
        self.assertEqual(ping.seq, 0)
        self.assertEqual(len(lock.pending), 2)

    def test_ack_releases_pending(self):
        lock = AckLock()
        lock.build(MsgType.SNAPSHOT)
        lock.build(MsgType.SNAPSHOT)
        lock.build(MsgType.SNAPSHOT)
        self.assertEqual(len(lock.pending), 3)
        removed = lock.ack(2)
        self.assertEqual(removed, 2)
        self.assertEqual(len(lock.pending), 1)
        self.assertEqual(lock.acked_count, 2)

    def test_cumulative_ack(self):
        """累计确认：ack=3 表示 1~3 都收到了"""
        lock = AckLock()
        for _ in range(5):
            lock.build(MsgType.SNAPSHOT)
        lock.ack(3)
        self.assertEqual(sorted(lock.pending), [4, 5])

    def test_duplicate_detection(self):
        lock = AckLock()
        self.assertFalse(lock.is_duplicate(1))
        self.assertTrue(lock.mark_received(1))
        self.assertTrue(lock.is_duplicate(1))
        self.assertFalse(lock.mark_received(1))     # 重复包不应再处理
        self.assertTrue(lock.mark_received(2))
        self.assertTrue(lock.is_duplicate(1))       # 老包仍然是重复
        self.assertFalse(lock.is_duplicate(3))

    def test_retransmit_after_timeout(self):
        lock = AckLock(timeout=0.10)
        lock.build(MsgType.SNAPSHOT)
        lock.on_sent(1, now=100.0)
        self.assertEqual(lock.due_for_retransmit(now=100.05), [])
        due = lock.due_for_retransmit(now=100.20)
        self.assertEqual(len(due), 1)
        entry = due[0]
        self.assertTrue(lock.on_retransmit(entry, now=100.20))
        self.assertEqual(entry.attempts, 2)
        self.assertEqual(lock.retransmit_count, 1)

    def test_gives_up_after_max_attempts(self):
        lock = AckLock(timeout=0.01, max_attempts=2)
        lock.build(MsgType.SNAPSHOT)
        entry = list(lock.pending.values())[0]
        lock.on_retransmit(entry)          # 第 2 次
        self.assertFalse(lock.on_retransmit(entry))   # 第 3 次 → 放弃
        self.assertEqual(len(lock.pending), 0)
        self.assertEqual(lock.dropped_count, 1)

    def test_ack_frame_uses_last_acked(self):
        lock = AckLock()
        lock.mark_received(5)
        frame = lock.make_ack_frame()
        self.assertEqual(frame.ack, 5)
        self.assertEqual(frame.seq, 0)

    def test_lost_ack_triggers_retransmit_then_success(self):
        """模拟：快照丢了 ACK → 重传 → 这次 ACK 到了 → 队列清空"""
        lock = AckLock(timeout=0.05)
        frame = lock.build(MsgType.SNAPSHOT, {'round': 1})
        self.assertEqual(len(lock.pending), 1)
        # 第一次 ACK 丢失
        self.assertEqual(lock.ack(0), 0)
        self.assertTrue(lock.due_for_retransmit(now=time.monotonic() + 1))
        entry = list(lock.pending.values())[0]
        lock.on_retransmit(entry)
        self.assertEqual(len(lock.pending), 1)
        # 第二次 ACK 到达
        lock.ack(frame.seq)
        self.assertEqual(len(lock.pending), 0)


# ---------------------------------------------------------------- 网络控制器
class TestNetworkController(unittest.TestCase):
    def setUp(self):
        from GameMaster import GameMaster
        self.gm = GameMaster(seed=3)
        self.gm.setup()
        # 用真正的当前回合玩家，否则「出牌」会被当成连锁宣言
        self.player = self.gm.current_player()
        self.controller = NetworkController(self.player.faction, name='远程')
        self.gm.controllers[self.player.faction] = self.controller

    def test_play_intent_queues_action(self):
        self.gm.begin_turn_draw()
        card = list(self.player.hand)[0]
        ok, msg = self.controller.apply_intent(
            self.gm, self.player, {'kind': 'play', 'uids': [card.uid]})
        self.assertTrue(ok, msg)
        action = self.controller.choose_action(self.gm, self.player)
        self.assertEqual(action.kind, 'play')
        self.assertEqual(action.cards, [card])

    def test_end_turn_intent(self):
        ok, _ = self.controller.apply_intent(self.gm, self.player, {'kind': 'end_turn'})
        self.assertTrue(ok)
        self.assertEqual(self.controller.choose_action(self.gm, self.player).kind, 'end')

    def test_unknown_card_rejected(self):
        ok, msg = self.controller.apply_intent(
            self.gm, self.player, {'kind': 'play', 'uids': [999999]})
        self.assertFalse(ok)
        self.assertIn('没有选中', msg)

    def test_unknown_intent_rejected(self):
        ok, msg = self.controller.apply_intent(self.gm, self.player, {'kind': 'hack'})
        self.assertFalse(ok)

    def test_waiting_state_exposed(self):
        self.gm.begin_turn_draw()
        action = self.controller.choose_action(self.gm, self.player)
        self.assertIsNone(action)
        self.assertTrue(self.controller.is_waiting())
        self.assertEqual(self.controller.pending['stage'], 'choose_action')


# ---------------------------------------------------------------- 端到端
class FakeClient:
    """测试用的极简客户端：用 ClientLink 收发，用 NetworkController 的意图格式回话"""

    def __init__(self, host, port, name, faction=None, timeout=0.4):
        self.link = ClientLink(host, port, timeout=timeout)
        self.name = name
        self.desired = str(faction) if faction else None
        self.you = None
        self.connected = False
        self.snapshots = 0
        self.rejections = []
        self.last_stage = None
        self.actions = 0
        self.done = False

    def send_hello(self):
        self.link.send(MsgType.HELLO, {'name': self.name, 'faction': self.desired})

    def tick(self):
        self.link.pump()
        for frame, _addr in self.link.receive():
            if frame.type == MsgType.WELCOME:
                self.you = enums.Suit(frame.data['faction'])
                self.connected = True
            elif frame.type == MsgType.SNAPSHOT:
                self.snapshots += 1
                self.handle_snapshot(frame.data)
            elif frame.type == MsgType.EVENT:
                if frame.data.get('event') == 'rejected':
                    self.rejections.append(frame.data.get('message'))
            elif frame.type == MsgType.BYE:
                self.done = True

    def handle_snapshot(self, data):
        stage = data.get('pending_stage')
        if data.get('game_over'):
            self.done = True
            return
        if stage == 'choose_chain' and self.last_stage != 'chain':
            self.last_stage = 'chain'
            self.link.send(MsgType.INTENT, {'kind': 'decline_chain'})
            return
        if stage == 'choose_action' and self.last_stage != 'action':
            self.last_stage = 'action'
            cards = []
            for p in data.get('players', []):
                if p['faction'] == str(self.you):
                    cards = [c for c in p.get('hand', []) if 'suit' in c]
            if cards:
                self.link.send(MsgType.INTENT, {'kind': 'play',
                                                'uids': [cards[0]['uid']]})
                self.actions += 1
            else:
                self.link.send(MsgType.INTENT, {'kind': 'end_turn'})
        elif stage is None:
            self.last_stage = None

    def close(self):
        try:
            self.link.send(MsgType.BYE, {'reason': 'test done'}, need_ack=False)
            self.link.pump()
        except OSError:
            pass
        self.link.close()


@unittest.skipUnless(os.environ.get('PHR_NET_TEST', '1') != '0', '网络测试被跳过')
class TestEndToEnd(unittest.TestCase):
    def test_four_clients_play_a_full_game(self):
        server = GameServer(port=0, host='127.0.0.1', ai_seats=0, target=12,
                            seed=11, verbose=False, snapshot_interval=0.0)
        port = server.port
        clients = [FakeClient('127.0.0.1', port, f'tester{i}') for i in range(4)]
        try:
            for c in clients:
                c.send_hello()
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                server.tick()
                for c in clients:
                    c.tick()
                if server.gm.game_over and all(c.connected for c in clients):
                    for _ in range(10):
                        server.tick()
                        for c in clients:
                            c.tick()
                    break
                time.sleep(0.002)
        finally:
            stats = server.status()
            for c in clients:
                c.close()
            server.shutdown()

        # 四名玩家都坐上座位并收到过快照
        self.assertEqual(len(server.seat_by_faction), 4, '应有 4 名玩家入座')
        for c in clients:
            self.assertTrue(c.connected, f'{c.name} 未能入座')
            self.assertGreater(c.snapshots, 0, f'{c.name} 没有收到快照')
        # 对局真的打完了
        self.assertTrue(server.gm.game_over, '联机对局未能在超时前结束')
        self.assertIsNotNone(server.gm.winner)
        # 玩家的指令被采纳过
        self.assertTrue(any(c.actions > 0 for c in clients), '客户端指令从未被采纳')
        # ACK 锁确实在工作：有帧被发出并被确认
        total_acked = sum(p['acked'] for p in stats['peers'].values())
        self.assertGreater(total_acked, 0, 'ACK 锁没有确认任何消息')
        self.assertEqual(sum(p['dropped'] for p in stats['peers'].values()), 0)

    def test_snapshot_hides_other_players_hands(self):
        """状态与渲染分离：主机广播的快照里，对手手牌只有 uid，没有牌面"""
        from viewmodel import TableView

        server = GameServer(port=0, host='127.0.0.1', ai_seats=0, verbose=False,
                            snapshot_interval=0.0)
        port = server.port
        client = FakeClient('127.0.0.1', port, 'spy')
        try:
            client.send_hello()
            deadline = time.monotonic() + 10.0
            last_data = None
            while time.monotonic() < deadline and not client.connected:
                server.tick()
                client.tick()
                time.sleep(0.002)
            # 捞一份发给该客户端的快照
            for _ in range(50):
                server.tick()
                client.tick()
                time.sleep(0.002)
                peer = list(server.peers.values())[0]
                view = server.player_of(peer.faction)
                frame = server.snapshot_for(peer)
                last_data = frame.data
                break
        finally:
            client.close()
            server.shutdown()

        self.assertIsNotNone(last_data)
        you = last_data['you']
        for p in last_data['players']:
            revealed = [c for c in p['hand'] if 'suit' in c]
            if p['faction'] == you:
                self.assertEqual(len(revealed), p['hand_size'],
                                 '自己的手牌应当全部可见')
            else:
                self.assertEqual(revealed, [],
                                 f"{p['faction']} 的手牌不应泄露牌面")
        # 客户端解析后，别人的牌应当是 hidden 的 CardView
        parsed = TableView.from_dict(last_data)
        mine = parsed.player_by_faction(enums.Suit(you))
        for p in parsed.players:
            if p.faction == enums.Suit(you):
                continue
            self.assertTrue(all(c.hidden for c in p.hand),
                            f'{p.name} 的手牌没有被当成牌背')
        self.assertTrue(mine is not None and mine.is_viewer)

    def test_room_full_is_rejected(self):
        server = GameServer(port=0, host='127.0.0.1', ai_seats=0, verbose=False,
                            snapshot_interval=0.0)
        port = server.port
        clients = [FakeClient('127.0.0.1', port, f'p{i}') for i in range(6)]
        try:
            for c in clients:
                c.send_hello()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline and len(server.seat_by_faction) < 4:
                server.tick()
                for c in clients:
                    c.tick()
                time.sleep(0.002)
            for _ in range(30):
                server.tick()
                for c in clients:
                    c.tick()
                time.sleep(0.002)
        finally:
            for c in clients:
                c.close()
            server.shutdown()
        self.assertLessEqual(len(server.seat_by_faction), 4)
        self.assertEqual(len(server.seat_by_faction), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
