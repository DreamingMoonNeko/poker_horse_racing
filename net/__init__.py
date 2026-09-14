"""局域网联机（TODO 3 + TODO 4）

设计要点：
- 主机（房主）是唯一权威：跑 GameMaster，广播状态快照
- 客户端只做「渲染 + 收集输入」，把玩家的决策打包成 Intent 发回主机
- 所有需要可靠的消息（快照 / Intent）都带序号，并对端必须回 ACK；
  超时未收到 ACK 就重发 —— 这就是 TODO 4 的「数据同步使用 ACK 锁」

模块划分：
    frames.py  消息定义与编解码
    acklock.py ACK 锁（发送队列 / 重传 / 去重 / 确认）
    protocol.py 会话层：连接握手、序号空间、快照与指令的收发
    server.py  主机端（GameMaster + 联机循环）
    client.py  客户端（接收快照 + 发送指令 + pygame 渲染）

依赖：仅标准库（socket / json / select）
"""

from net.frames import Frame, MsgType, encode, decode
from net.acklock import AckLock, PendingFrame

__all__ = ['Frame', 'MsgType', 'encode', 'decode', 'AckLock', 'PendingFrame']
