"""ACK 锁（TODO 4：数据同步使用 ACK 锁）

解决的问题：局域网用不可靠传输（UDP）时，状态快照和玩家指令都可能丢失。
做法是把每条需要可靠送达的消息放进「待确认表」，收到对端 ACK 前一直保留，
超时未确认就重发；接收端用「已确认序号集合」去重，保证幂等。

序号空间：
- 每个方向各自维护一条递增序号（发送序号 seq）
- AckLock.last_acked 记录「已经收到的最大对端序号」，收到帧就回 ACK
- 因为按序发送（stop-and-wait），last_acked 单调递增，天然去重

这不是 TCP：它把「可靠 + 幂等」放在应用层，便于把游戏状态和玩家指令
放进同一套可验证的机制里，也方便做单元测试。
"""

from dataclasses import dataclass, field

import time


@dataclass
class PendingFrame:
    """一条等待 ACK 的消息"""

    seq: int
    frame: object                      # net.frames.Frame
    sent_at: float
    attempts: int = 1                  # 已经发送过几次
    extra: dict = field(default_factory=dict)

    def age(self, now: float = None) -> float:
        return (now if now is not None else time.monotonic()) - self.sent_at


class AckLock:
    """单向的 ACK 锁：负责发送序号、未确认队列、重传与去重。"""

    def __init__(self, timeout: float = 0.30, max_attempts: int = 6, name: str = ''):
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.name = name

        self.next_seq = 1               # 待分配的下一个发送序号
        self.pending: dict[int, PendingFrame] = {}
        self.last_acked = 0             # 已收到的最大对端序号
        self.acked_count = 0
        self.retransmit_count = 0
        self.dropped_count = 0          # 超过重传上限而放弃
        self.stats_sent = 0

    # ------------------------------------------------------------ 发送
    def build(self, msg_type: str, data: dict = None, need_ack: bool = True,
              ack_flag: bool = True):
        """构造一帧。need_ack=True 时分配序号并登记进待确认表。"""
        from net.frames import Frame

        seq = 0
        if need_ack:
            seq = self.next_seq
            self.next_seq += 1
        frame = Frame(type=msg_type, seq=seq,
                      ack=self.last_acked if ack_flag else 0,
                      data=dict(data or {}))
        if need_ack:
            self.pending[seq] = PendingFrame(seq=seq, frame=frame,
                                             sent_at=time.monotonic())
        self.stats_sent += 1
        return frame

    def on_sent(self, seq: int, now: float = None):
        """实际写进 socket 之后调用（用于计算重传时机）"""
        entry = self.pending.get(seq)
        if entry is not None:
            entry.sent_at = now if now is not None else time.monotonic()

    # ------------------------------------------------------------ 接收
    def is_duplicate(self, seq: int) -> bool:
        """已经收到过（序号不大于 last_acked）→ 重复包，应丢弃但补发 ACK"""
        return seq > 0 and seq <= self.last_acked

    def mark_received(self, seq: int) -> bool:
        """登记收到的序号。返回 True 表示这是新消息（需要处理）。"""
        if seq <= 0:
            return True
        if seq <= self.last_acked:
            return False
        self.last_acked = seq
        return True

    def ack(self, seq: int) -> int:
        """登记对端确认（收到帧里的 ack 字段）"""
        if seq <= 0:
            return 0
        removed = 0
        for pending_seq in [s for s in self.pending if s <= seq]:
            del self.pending[pending_seq]
            self.acked_count += 1
            removed += 1
        return removed

    # ------------------------------------------------------------ 重传
    def due_for_retransmit(self, now: float = None):
        """返回超时未确认、需要重发的 PendingFrame 列表"""
        now = now if now is not None else time.monotonic()
        due = []
        for entry in list(self.pending.values()):
            if entry.age(now) >= self.timeout:
                due.append(entry)
        return due

    def on_retransmit(self, entry: PendingFrame, now: float = None):
        entry.attempts += 1
        entry.sent_at = now if now is not None else time.monotonic()
        self.retransmit_count += 1
        if entry.attempts > self.max_attempts:
            self.pending.pop(entry.seq, None)
            self.dropped_count += 1
            return False
        return True

    # ------------------------------------------------------------ 便捷方法
    def make_ack_frame(self, msg_type: str = 'ack'):
        """构造一个纯 ACK 帧（不需要被 ACK）"""
        from net.frames import Frame
        return Frame(type=msg_type, seq=0, ack=self.last_acked, data={})

    @property
    def has_pending(self) -> bool:
        return bool(self.pending)

    def status(self) -> dict:
        return {
            'name': self.name,
            'next_seq': self.next_seq,
            'pending': len(self.pending),
            'last_acked': self.last_acked,
            'acked': self.acked_count,
            'retransmit': self.retransmit_count,
            'dropped': self.dropped_count,
            'sent': self.stats_sent,
        }

    def __repr__(self):
        return (f'<AckLock {self.name} pending={len(self.pending)} '
                f'last_acked={self.last_acked}>')
