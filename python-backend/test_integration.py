"""python-backend 集成测试（自包含，不依赖 pytest）。

验证：指令构造/解析、WebSocket 握手、广播接收、echo 回显、路径校验。
运行：.venv/Scripts/python.exe test_integration.py
"""
import asyncio
import json
import sys

import websockets

from server import L2DServer, build_command, parse_input_line

PORT = 3999


async def main() -> None:
    server = L2DServer(host="127.0.0.1", port=PORT, path="/ws",
                       echo=False, no_interactive=True)
    task = asyncio.create_task(server.run())
    await asyncio.sleep(0.3)

    # 1. 指令构造与解析
    assert build_command("motion", group="TapBody", no=2) == \
        {"type": "motion", "group": "TapBody", "no": 2, "priority": 3}
    assert build_command("lipsync", value=1.5) == {"type": "lipsync", "value": 1.0}
    assert build_command("switch_model") == {"type": "switch_model"}
    assert parse_input_line("motion TapBody 0 3") == \
        {"type": "motion", "group": "TapBody", "no": 0, "priority": 3}
    assert parse_input_line("lipsync 0.75")["value"] == 0.75
    assert parse_input_line("switch_model 2")["index"] == 2
    print("OK  build_command / parse_input_line")

    # 2. 正确路径连接 + 广播接收
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
        sent = await server.send_command({"type": "expression", "name": "F01"})
        assert sent == 1, sent
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        assert msg == {"type": "expression", "name": "F01"}, msg
        print("OK  broadcast dict 指令送达")

        sent = await server.send_command(("motion", {"group": "TapBody", "no": 0, "priority": 3}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        assert msg["type"] == "motion" and msg["group"] == "TapBody" and msg["no"] == 0
        print("OK  tuple 指令送达")

        server.echo = True
        await ws.send("ping-from-client")
        echo = await asyncio.wait_for(ws.recv(), timeout=3)
        assert echo == "ping-from-client", echo
        print("OK  echo 回显")

    # 3. 错误路径拒绝
    rejected = False
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/wrong") as ws:
            try:
                await asyncio.wait_for(ws.recv(), timeout=2)
            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                rejected = True
    except websockets.exceptions.InvalidStatus:
        rejected = True
    assert rejected, "错误路径应当被拒绝"
    print("OK  错误路径被拒绝")

    await server.stop()
    await task
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) is None else 1)