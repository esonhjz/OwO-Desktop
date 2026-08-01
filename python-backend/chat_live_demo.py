#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_live_demo.py — 驱动 L2DServer 实测完整 chat 链路（临时联调脚本）。

流程：
  1) 启动 L2DServer(host='0.0.0.0', port=3000, path='/ws',
                   echo=False, no_interactive=True)
  2) 轮询 server.clients 等待至少一个客户端连接
  3) 连接后调用 await server._handle_chat_pipeline('今天天气真好，好开心呀！')
  4) 每条广播指令打印到 stdout（带时间戳）
  5) 管线完成后再运行 3 秒，正常关闭服务端退出

用法：.venv/Scripts/python.exe chat_live_demo.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

from server import L2DServer, build_command

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def ts() -> str:
    """毫秒级时间戳，便于比对指令时序。"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def main() -> None:
    server = L2DServer(host="0.0.0.0", port=3000, path="/ws",
                       echo=False, no_interactive=True)

    # ---- 拦截广播：把每条指令打印到 stdout，并做分类统计 ----
    stats: dict[str, int] = {}
    orig_send = server.send_command

    async def traced_send(command, target_ids=None, exclude_ids=None):
        # 归一化 command 为 dict，仅用于打印（原样转发给 orig_send）
        if isinstance(command, str):
            try:
                payload_obj = json.loads(command)
            except json.JSONDecodeError:
                payload_obj = {"raw": command}
        elif isinstance(command, tuple):
            payload_obj = build_command(command[0], **(command[1] or {}))
        else:
            payload_obj = dict(command)
        t = str(payload_obj.get("type", "?"))
        stats[t] = stats.get(t, 0) + 1
        print(f"[{ts()}] >> {json.dumps(payload_obj, ensure_ascii=False)}", flush=True)
        return await orig_send(command, target_ids=target_ids,
                               exclude_ids=exclude_ids)

    server.send_command = traced_send

    run_task = asyncio.create_task(server.run())

    # ---- 等待至少一个客户端连接（最多 30s）----
    deadline = time.monotonic() + 30
    while not server.clients and time.monotonic() < deadline:
        await asyncio.sleep(0.2)

    if not server.clients:
        print(f"[{ts()}] [driver] TIMEOUT: 30s 内无客户端连接，直接退出", flush=True)
        await server.stop()
        await run_task
        return

    cid = next(iter(server.clients))
    peer = server._peer(server.clients[cid])
    print(f"[{ts()}] [driver] 客户端已连接 cid={cid} peer={peer}", flush=True)

    # ---- 调用完整 chat 管线 ----
    text = "今天天气真好，好开心呀！"
    print(f"[{ts()}] [driver] >>> _handle_chat_pipeline({text!r})", flush=True)
    try:
        await server._handle_chat_pipeline(text)
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"[{ts()}] [driver] 管线异常: {exc!r}", flush=True)
        traceback.print_exc()

    # ---- 运行 3 秒后正常关闭 ----
    print(f"[{ts()}] [driver] 管线结束，再运行 3 秒后关闭服务端", flush=True)
    await asyncio.sleep(3)
    await server.stop()
    await run_task

    total = sum(stats.values())
    print(f"[{ts()}] [driver] 广播统计: 共 {total} 条 "
          f"{json.dumps(stats, ensure_ascii=False)}", flush=True)
    print(f"[{ts()}] [driver] 服务端已关闭，驱动退出", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt，退出")
