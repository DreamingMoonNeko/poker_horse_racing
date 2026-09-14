"""UDP 连接与对端对象

- UdpLink：封装一个非阻塞 UDP socket，负责发/收 Frame
- Peer：主机侧的一条「座位连接」，持有自己的 AckLock 与发送队列
- ClientLink：客户端侧的一条连接
"""

import socket
from collections import deque

from net.acklock import AckLock
from net.frames import encode, decode


class UdpLink:
    """非阻塞 UDP socket 封装"""

    def __init__(self, host: str, port: int, timeout: float = 0.0):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.socket.setblocking(False)
        self.address = self.socket.getsockname()

    def send_to(self, frame, address):
        self.socket.sendto(encode(frame), address)

    def send(self, frame):
        """客户端用：发给已连接的主机地址"""
        self.socket.sendto(encode(frame), self.remote)

    def close(self):
        try:
            self.socket.close()
        except OSError:
            pass

    def __repr__(self):
        return f'<UdpLink {self.address}>'


class Peer:
    """主机侧的一个客户端连接"""

    def __init__(self, address, faction, name: str = '', timeout: float = 0.30):
        self.address = address
        self.faction = faction
        self.name = name or str(faction)
        self.lock = AckLock(timeout=timeout, name=self.name)
        self.outbox = deque()
        self.connected_at = None
        self.last_seen = 0.0

    def touch(self, now: float):
        if self.connected_at is None:
            self.connected_at = now
        self.last_seen = now

    @property
    def pending_count(self) -> int:
        return len(self.lock.pending)

    def __repr__(self):
        return f'<Peer {self.name} {self.address} pending={self.pending_count}>'


class ClientLink:
    """客户端侧连接：发送需要 ACK 的帧，并处理重传与去重"""

    def __init__(self, host: str = '127.0.0.1', port: int = 45678,
                 timeout: float = 0.30):
        self.remote = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.lock = AckLock(timeout=timeout, name='client')
        self.outbox = deque()
        self.last_seen = 0.0

    # ---------- 收 ----------
    def receive(self, limit: int = 32):
        """读取所有可读数据包，返回 [(frame, addr)]（已去重）"""
        from net.frames import MsgType
        out = []
        for _ in range(limit):
            try:
                data, addr = self.socket.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError:
                break
            try:
                frame = decode(data)
            except Exception:
                continue
            if frame.ack:
                self.lock.ack(frame.ack)
            if frame.seq:
                if self.lock.is_duplicate(frame.seq):
                    # 重复帧：补一个 ACK，避免主机一直重传
                    self._queue_ack()
                    continue
                self.lock.mark_received(frame.seq)
                self._queue_ack()
            out.append((frame, addr))
        return out

    def _queue_ack(self):
        self.outbox.append(self.lock.make_ack_frame())

    # ---------- 发 ----------
    def send(self, msg_type: str, data: dict = None, need_ack: bool = True):
        frame = self.lock.build(msg_type, data, need_ack=need_ack)
        self.outbox.append(frame)
        return frame

    def pump(self, now: float = None):
        """写出待发队列 + 重传超时帧"""
        import time
        now = now if now is not None else time.monotonic()
        while self.outbox:
            frame = self.outbox.popleft()
            try:
                self.socket.sendto(encode(frame), self.remote)
            except OSError:
                break
            if frame.seq:
                self.lock.on_sent(frame.seq)
        for entry in self.lock.due_for_retransmit(now):
            if not self.lock.on_retransmit(entry, now):
                continue
            try:
                self.socket.sendto(encode(entry.frame), self.remote)
            except OSError:
                break

    def close(self):
        try:
            self.socket.close()
        except OSError:
            pass

    @property
    def has_pending(self) -> bool:
        return bool(self.lock.pending) or bool(self.outbox)
