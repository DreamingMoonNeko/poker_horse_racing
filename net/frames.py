"""联机消息定义与编解码

协议（JSON over UDP / TCP 均可，一帧一条消息）：

    Frame:
      type   消息类型（见 MsgType）
      seq    发送方为该消息分配的序号；有 seq 的消息必须被 ACK
      ack    本帧顺便确认的「对端序号」（可选，节省往返）
      data   负载

消息类型：
    HELLO     客户端 → 主机   请求入座（data.name 玩家名，data.faction 期望花色）
    WELCOME   主机 → 客户端   入座确认（data.slot/faction/players...）
    SNAPSHOT  主机 → 客户端   状态快照（带 seq，需要 ACK）
    INTENT    客户端 → 主机   玩家决策（带 seq，需要 ACK）
    EVENT     主机 → 客户端   提示信息（入座/拒绝/对局结束）
    PING/PONG 双向            保活与 RTT 测量
    BYE       双向            主动退出
"""

import json
from dataclasses import dataclass, field
from enum import Enum

PROTOCOL_VERSION = 1
MAX_DATAGRAM = 60_000


class MsgType(str, Enum):
    HELLO = 'hello'
    WELCOME = 'welcome'
    SNAPSHOT = 'snapshot'
    INTENT = 'intent'
    EVENT = 'event'
    PING = 'ping'
    PONG = 'pong'
    BYE = 'bye'


@dataclass
class Frame:
    type: str
    seq: int = 0                 # 0 表示不需要 ACK
    ack: int = 0                 # 顺带确认的对端序号，0 表示无
    data: dict = field(default_factory=dict)
    version: int = PROTOCOL_VERSION

    @property
    def needs_ack(self) -> bool:
        return self.seq > 0

    def to_dict(self) -> dict:
        out = {'v': self.version, 'type': self.type}
        if self.seq:
            out['seq'] = self.seq
        if self.ack:
            out['ack'] = self.ack
        if self.data:
            out['data'] = self.data
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> 'Frame':
        return cls(
            type=str(raw.get('type', '')),
            seq=int(raw.get('seq', 0) or 0),
            ack=int(raw.get('ack', 0) or 0),
            data=dict(raw.get('data') or {}),
            version=int(raw.get('v', PROTOCOL_VERSION)),
        )

    def __repr__(self):
        return f'<Frame {self.type} seq={self.seq} ack={self.ack} {list(self.data)}>'


class ProtocolError(Exception):
    pass


def encode(frame: Frame) -> bytes:
    payload = json.dumps(frame.to_dict(), ensure_ascii=False, separators=(',', ':'))
    return payload.encode('utf-8')


def decode(raw: bytes) -> Frame:
    if not raw:
        raise ProtocolError('空数据包')
    try:
        parsed = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f'无法解析数据包：{exc}') from exc
    if not isinstance(parsed, dict):
        raise ProtocolError('数据包顶层必须是对象')
    frame = Frame.from_dict(parsed)
    if not frame.type:
        raise ProtocolError('缺少消息类型')
    return frame
