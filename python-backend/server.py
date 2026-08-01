#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — L2D 控制系统 WebSocket 服务端骨架（Phase 2）
================================================================

监听 `ws://0.0.0.0:3000/ws`，接受 OwO-Desktop (C++) 客户端连接，
把 LLM / TTS 管线产出的 JSON 指令广播给所有已连接客户端。

特性：
  - 多客户端支持（广播 / 定向发送）
  - `send_command()`：向所有（或指定）客户端广播指令，供其他模块调用
  - 终端交互输入：支持完整 JSON 与简化 `type key value` 语法
  - 内置 echo 测试模式：回显客户端消息 + 对新客户端自动播放测试指令序列
  - `chat <文本>`：跑通「LLM → 情绪映射 → TTS → 口型」完整链路（未配置时自动 mock）
  - 支持对话历史（最近 N 条）、模型上下文注入（model_scanner）、
    LLM 与情绪映射并行（asyncio.gather）、播放期持续口型推送

协议（与 ../src/NetworkManager.cpp 严格一致）：

  {"type": "expression", "name": "F01"}
  {"type": "motion",     "group": "TapBody", "no": 0, "priority": 3}
  {"type": "lipsync",    "value": 0.75}
  {"type": "switch_model"}                      # index 缺省 = -1，切至下一模型
  {"type": "switch_model", "index": 2}          # 精确跳转（0-based）

  协议扩展（Phase 2 设计文档 2.2 节）：
  {"type": "animation", "name": "greeting"}
  {"type": "param",     "id": "ParamAngleX", "value": 15.0}
  {"type": "background","file": "bg_night.png"}

用法：
  python server.py                   # 默认 0.0.0.0:3000，交互模式
  python server.py --echo            # echo 测试模式（回显 + 自动播放测试序列）
  python server.py --send "motion TapBody 0 3"   # 启动后先广播一条指令
  python server.py --port 4000 --path /ws
"""

from __future__ import annotations  # 使 `X | None` 等标注在 Python 3.9 也可用

import argparse
import asyncio
import json
import logging
import sys
import threading
from typing import Any

import websockets

logger = logging.getLogger(__name__)

# 全局单例：供其他模块（llm_client / tts_client / 自定义 AI 管线）调用
SERVER: "L2DServer | None" = None


# ---------------------------------------------------------------------------
# 指令构造与解析
# ---------------------------------------------------------------------------
def build_command(cmd_type: str, **kwargs: Any) -> dict:
    """按协议构造一条合法指令字典，并做字段校验与默认值回退。

    返回的 dict 可直接 json.dumps 后发送给 C++ 客户端。
    """
    cmd_type = str(cmd_type).lower()
    if cmd_type == "expression":
        if "name" not in kwargs:
            raise ValueError("expression 指令缺少 name 字段")
        return {"type": "expression", "name": str(kwargs["name"])}

    if cmd_type == "motion":
        if "group" not in kwargs:
            raise ValueError("motion 指令缺少 group 字段")
        return {
            "type": "motion",
            "group": str(kwargs["group"]),
            "no": int(kwargs.get("no", 0)),
            "priority": int(kwargs.get("priority", 3)),
        }

    if cmd_type == "lipsync":
        value = float(kwargs.get("value", 0.0))
        value = max(0.0, min(1.0, value))   # 钳制到 [0.0, 1.0]
        return {"type": "lipsync", "value": value}

    if cmd_type == "switch_model":
        cmd = {"type": "switch_model"}
        if "index" in kwargs:
            cmd["index"] = int(kwargs["index"])
        # index 缺省时由 C++ 端 j.value("index", -1) 兜底 → 下一模型
        return cmd

    # ---- 协议扩展（Phase 2 设计文档 2.2 节）----
    if cmd_type == "animation":
        if "name" not in kwargs:
            raise ValueError("animation 指令缺少 name 字段")
        return {"type": "animation", "name": str(kwargs["name"])}

    if cmd_type == "param":
        if "id" not in kwargs:
            raise ValueError("param 指令缺少 id 字段")
        return {"type": "param", "id": str(kwargs["id"]),
                "value": float(kwargs.get("value", 0.0))}

    if cmd_type == "background":
        if "file" not in kwargs:
            raise ValueError("background 指令缺少 file 字段")
        return {"type": "background", "file": str(kwargs["file"])}

    raise ValueError(f"未知指令类型: {cmd_type}")


def parse_input_line(line: str) -> dict:
    """解析终端输入为指令字典。

    支持两种语法：
      1. 完整 JSON：{"type":"expression","name":"F01"}
      2. 简化语法：
           expression F01
           motion TapBody 0 3
           lipsync 0.75
           switch_model
           switch_model 2
           animation greeting
           param ParamAngleX 15.0
           background bg_night.png
    """
    line = line.strip()
    if not line:
        return {}

    if line.startswith("{"):
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败: {exc}")
        if "type" not in data:
            raise ValueError("JSON 指令缺少 type 字段")
        return data

    parts = line.split()
    kind = parts[0].lower()
    args = parts[1:]

    if kind == "expression":
        if len(args) < 1:
            raise ValueError("用法: expression <名称>")
        return build_command("expression", name=args[0])

    if kind == "motion":
        if len(args) < 1:
            raise ValueError("用法: motion <group> [no] [priority]")
        no = int(args[1]) if len(args) > 1 else 0
        priority = int(args[2]) if len(args) > 2 else 3
        return build_command("motion", group=args[0], no=no, priority=priority)

    if kind == "lipsync":
        if len(args) < 1:
            raise ValueError("用法: lipsync <0.0~1.0>")
        return build_command("lipsync", value=float(args[0]))

    if kind == "switch_model":
        index = int(args[0]) if len(args) > 0 else -1
        return build_command("switch_model", index=index)

    if kind == "animation":
        if len(args) < 1:
            raise ValueError("用法: animation <名称>")
        return build_command("animation", name=args[0])

    if kind == "param":
        if len(args) < 2:
            raise ValueError("用法: param <参数ID> <数值>")
        return build_command("param", id=args[0], value=float(args[1]))

    if kind == "background":
        if len(args) < 1:
            raise ValueError("用法: background <文件名>")
        return build_command("background", file=args[0])

    raise ValueError(f"未知指令类型: {kind}（输入 help 查看帮助）")


# ---------------------------------------------------------------------------
# WebSocket 服务端
# ---------------------------------------------------------------------------
class L2DServer:
    """L2D 控制服务端。

    维护已连接客户端集合，提供广播 / 定向发送、终端交互、echo 测试模式。
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 3000,
                 path: str = "/ws", echo: bool = False,
                 allow_any_path: bool = False,
                 no_interactive: bool = False,
                 send_cmds: list[str] | None = None,
                 model_scanner: Any = None,
                 llm_config: Any = None,
                 tts_config: Any = None,
                 chat_history_max: int = 6):
        self.host = host
        self.port = port
        self.path = path
        self.echo = echo                     # echo 测试模式开关（运行期可改）
        self.allow_any_path = allow_any_path
        self.no_interactive = no_interactive
        self.send_cmds = send_cmds or []

        # Phase 2 增强：模型扫描器 / LLM 配置 / TTS 配置 / 对话历史
        self.model_scanner = model_scanner
        self.llm_config = llm_config
        self.tts_config = tts_config
        self.chat_history_max = max(1, int(chat_history_max))
        self._chat_history: list[dict] = []   # [{"role": ..., "content": ...}]

        self.clients: dict[int, Any] = {}    # client_id -> websocket
        self._next_client_id = 0
        self._server = None                  # websockets.serve 的 Server 对象
        self._stop_event: asyncio.Event | None = None
        self._shutdown = False

    # ------------------------------------------------------------------
    # 客户端登记
    # ------------------------------------------------------------------
    def _register(self, websocket) -> int:
        self._next_client_id += 1
        cid = self._next_client_id
        self.clients[cid] = websocket
        return cid

    def _unregister(self, cid: int) -> None:
        self.clients.pop(cid, None)

    @staticmethod
    def _peer(websocket) -> str:
        addr = getattr(websocket, "remote_address", None)
        return str(addr) if addr else "?"

    # ------------------------------------------------------------------
    # 连接处理
    # ------------------------------------------------------------------
    async def _handle_client(self, websocket, *args) -> None:
        """单个客户端连接的主处理函数（*args 兼容 websockets 旧版 path 参数）。"""
        if not self._check_path(websocket, args):
            await websocket.close(code=1008, reason="invalid path")
            return

        cid = self._register(websocket)
        logger.info("[+] 客户端 %s 已连接（来源: %s），当前在线 %d",
                    cid, self._peer(websocket), len(self.clients))

        if self.echo:
            # echo 测试模式：对新客户端自动播放一段测试指令序列
            asyncio.create_task(self._autotest_sequence(websocket, cid))

        try:
            async for message in websocket:
                await self._on_message(websocket, cid, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 连接内异常不应终止服务
            logger.debug("客户端 %s 连接异常: %s", cid, exc)
        finally:
            self._unregister(cid)
            logger.info("[-] 客户端 %s 断开，当前在线 %d", cid, len(self.clients))

    def _check_path(self, websocket, args) -> bool:
        """校验请求路径是否为预期路径（如 /ws）。"""
        if self.allow_any_path:
            return True
        path = self._request_path(websocket, args)
        if path is None:
            logger.warning("无法获取请求路径，拒绝连接")
            return False
        if path != self.path:
            logger.warning("拒绝非 %s 路径的连接: %s", self.path, path)
            return False
        return True

    @staticmethod
    def _request_path(websocket, args) -> str | None:
        """兼容不同 websockets 版本取请求路径。"""
        if args:
            return str(args[0])                      # websockets <= 9
        path = getattr(websocket, "path", None)
        if isinstance(path, str):
            return path                              # websockets 10~13
        request = getattr(websocket, "request", None)
        if request is not None:
            return getattr(request, "path", None)    # websockets 14+
        return None

    async def _on_message(self, websocket, cid: int, message) -> None:
        """收到客户端消息。默认仅记录；echo 模式下原样回显。"""
        logger.info("[←] 客户端 %s 发来消息: %s", cid, message)
        if self.echo:
            await websocket.send(message)            # 回显
            logger.info("[→] 已回显给客户端 %s", cid)

    # ------------------------------------------------------------------
    # 广播 / 定向发送
    # ------------------------------------------------------------------
    async def send_command(self, command: Any, target_ids=None,
                           exclude_ids=None) -> int:
        """向客户端广播指令，返回成功送达数。

        :param command: dict 指令，或 (type, kwargs) 元组，或 JSON 字符串
        :param target_ids: 指定客户端 id 集合；None = 全部客户端
        :param exclude_ids: 排除的客户端 id 集合
        """
        if isinstance(command, str):
            try:
                payload_obj = json.loads(command)
            except json.JSONDecodeError as exc:
                raise ValueError(f"无效 JSON 指令: {command!r}: {exc}")
            if "type" not in payload_obj:
                raise ValueError("指令缺少 type 字段")
        elif isinstance(command, tuple):
            payload_obj = build_command(command[0], **(command[1] or {}))
        elif isinstance(command, dict):
            if "type" not in command:
                raise ValueError("指令缺少 type 字段")
            payload_obj = dict(command)
        else:
            raise TypeError(f"不支持的指令类型: {type(command)!r}")

        payload = json.dumps(payload_obj, ensure_ascii=False)

        targets = list(self.clients.items())
        if target_ids is not None:
            allowed = set(target_ids)
            targets = [(cid, ws) for cid, ws in targets if cid in allowed]
        if exclude_ids is not None:
            blocked = set(exclude_ids)
            targets = [(cid, ws) for cid, ws in targets if cid not in blocked]

        sent = 0
        dead: list[int] = []
        for cid, ws in targets:
            try:
                await ws.send(payload)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("发送到客户端 %s 失败: %s", cid, exc)
                dead.append(cid)
        for cid in dead:
            self._unregister(cid)
        return sent

    # ------------------------------------------------------------------
    # echo 测试模式
    # ------------------------------------------------------------------
    async def _autotest_sequence(self, websocket, cid: int) -> None:
        """对单个客户端播放一段演示指令序列（参考 ../test/test_ws_server.py）。

        依次演示：预热动作 → 表情+动作组合 → 口型扫描 → 模型切换。
        """
        try:
            logger.info("[autotest] 客户端 %s 预热动作 ...", cid)
            await websocket.send(json.dumps(
                {"type": "motion", "group": "TapBody", "no": 0, "priority": 3}))
            await asyncio.sleep(0.15)

            logger.info("[autotest] 客户端 %s 表情 + 动作组合 ...", cid)
            for name in ("F01", "F02", "F03"):
                await websocket.send(json.dumps({"type": "expression", "name": name}))
                await websocket.send(json.dumps(
                    {"type": "motion", "group": "TapBody", "no": 0, "priority": 3}))
                await asyncio.sleep(0.4)

            logger.info("[autotest] 客户端 %s 口型扫描（0→1→0）...", cid)
            for i in range(21):
                value = round(i / 20.0, 3) if i <= 10 else round((20 - i) / 10.0, 3)
                await websocket.send(json.dumps({"type": "lipsync", "value": value}))
                await asyncio.sleep(0.08)

            logger.info("[autotest] 客户端 %s 模型切换 ...", cid)
            await websocket.send(json.dumps({"type": "switch_model"}))     # 下一模型
            await asyncio.sleep(0.5)
            await websocket.send(json.dumps({"type": "switch_model", "index": 0}))

            logger.info("[autotest] 客户端 %s 测试序列完成", cid)
        except websockets.exceptions.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("客户端 %s autotest 中断: %s", cid, exc)

    # ------------------------------------------------------------------
    # 终端交互
    # ------------------------------------------------------------------
    def _start_interactive(self) -> None:
        """以守护线程读取终端输入，经 call_soon_threadsafe 投递到事件循环。

        使用独立线程避免阻塞事件循环；对 Windows 控制台友好，
        且守护线程不会阻塞进程退出。
        """
        if self.no_interactive:
            return
        loop = asyncio.get_running_loop()

        def _reader() -> None:
            try:
                for line in sys.stdin:
                    if self._shutdown:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        loop.call_soon_threadsafe(self._schedule_line, line)
                    except Exception:  # noqa: BLE001
                        break
            except Exception as exc:  # noqa: BLE001
                logger.warning("终端读取结束: %s", exc)

        thread = threading.Thread(target=_reader, name="stdin-reader", daemon=True)
        thread.start()
        logger.info("终端交互已就绪，输入 help 查看可用指令")

    def _schedule_line(self, line: str) -> None:
        """在事件循环线程内调用（call_soon_threadsafe 回调）。"""
        asyncio.create_task(self._handle_command_line(line))

    async def _handle_command_line(self, line: str) -> None:
        """处理一行终端输入。"""
        line = (line or "").strip()
        if not line:
            return

        low = line.lower()
        if low in ("exit", "quit", "bye"):
            logger.info("收到退出指令，正在关闭服务 ...")
            await self.stop()
            return
        if low in ("help", "h", "?"):
            self._print_help()
            return
        if low.startswith("echo"):
            arg = line[4:].strip().lower()
            if arg in ("on", "1", "true"):
                self.echo = True
                logger.info("echo 测试模式已开启")
            elif arg in ("off", "0", "false"):
                self.echo = False
                logger.info("echo 测试模式已关闭")
            else:
                logger.info("echo 测试模式当前为 %s",
                            "开启" if self.echo else "关闭")
            return
        if low in ("clients", "list"):
            logger.info("当前在线客户端 (%d): %s",
                        len(self.clients), list(self.clients) or "无")
            return
        if low == "chat" or low.startswith("chat "):
            text = line[5:].strip() if low.startswith("chat ") else ""
            await self._handle_chat_pipeline(text)
            return

        try:
            cmd = parse_input_line(line)
        except (ValueError, TypeError) as exc:
            logger.error("指令解析失败: %s", exc)
            return
        if not cmd:
            return
        await self._dispatch(cmd)

    async def _dispatch(self, cmd: dict) -> None:
        try:
            count = await self.send_command(cmd)
            logger.info("[>] 指令已广播: %s (送达 %d 个客户端)",
                        json.dumps(cmd, ensure_ascii=False), count)
        except Exception as exc:  # noqa: BLE001
            logger.error("发送失败: %s", exc)

    def _print_help(self) -> None:
        logger.info(
            "可用指令:\n"
            "  expression <名称>                切换表情, 如 expression F01\n"
            "  motion <group> [no] [priority]   触发动作, 如 motion TapBody 0 3\n"
            "  lipsync <0.0~1.0>                口型张合度, 如 lipsync 0.75\n"
            "  switch_model [index]             切换模型, 缺省 index = 下一模型\n"
            "  animation <名称>                 播放预设动画序列\n"
            "  param <参数ID> <数值>            直接控制模型参数, 如 param ParamAngleX 15.0\n"
            "  background <文件名>              切换背景, 如 background bg_night.png\n"
            "  chat <文本>                      完整管线演示: LLM→情绪→TTS→口型（含对话历史）\n"
            "  echo on/off                      开/关 echo 测试模式\n"
            "  clients                          查看在线客户端\n"
            "  exit / quit                      退出服务\n"
            "  也可以直接输入完整 JSON 指令, 如 {\"type\":\"expression\",\"name\":\"F01\"}"
        )

    # ------------------------------------------------------------------
    # 完整管线演示：LLM → 情绪映射 → TTS + 口型 → 广播
    # ------------------------------------------------------------------
    def _append_history(self, role: str, content: str) -> None:
        """追加一条对话历史，只保留最近 N 条（借鉴 SoulLink chat.py 的截断思路）。"""
        content = (content or "").strip()
        if not content:
            return
        self._chat_history.append({"role": role, "content": content})
        if len(self._chat_history) > self.chat_history_max:
            self._chat_history = self._chat_history[-self.chat_history_max:]

    async def _handle_chat_pipeline(self, text: str) -> None:
        """跑通 Phase 2 的完整链路。

        未配置真实 LLM / TTS 时自动使用 mock，方便离线联调。

        Phase 2 增强：
        - 支持对话历史（最近 chat_history_max 条，默认 6）
        - 配置了 model_scanner 时，把可用 expression/motion 清单注入 LLM 提示
        - 聊天回复与情绪映射并行（asyncio.gather）：
            LLM 调用期间先广播中性表情（角色"倾听中"），避免表情冻结；
            情绪映射结果（expression / motion）并行动作广播。
        - TTS 播放期间通过 iter_lipsync 持续推送口型
        """
        if not text:
            logger.error("chat 指令需要文本内容, 如: chat 今天天气怎么样？")
            return

        # 延迟导入：保持服务端启动轻量，且 openai/edge-tts 未装也不影响
        from emotion_mapper import expression_for, map_emotion
        from llm_client import LLMClient
        from tts_client import TTSClient

        # 0. LLM（含情绪标签），优先使用 config.yaml 解析出的配置
        llm = LLMClient(config=self.llm_config) if self.llm_config else LLMClient()

        # 配置了 model_scanner 时，把可用动作/表情清单注入 LLM 提示
        if self.model_scanner is not None and self.model_scanner.available:
            self.model_scanner.scan()
            if self.model_scanner.switch_models:
                llm.set_model_context(
                    expressions=self.model_scanner.current_expressions(),
                    motions=self.model_scanner.current_motions(),
                    model_prompt=self.model_scanner.current_custom_prompt(),
                )
                logger.info("[models] 注入模型上下文: %s",
                            ", ".join(self.model_scanner.switch_models[0].expressions or ["(无表情)"]))

        # 1. 对话历史（最近 N 条）
        self._append_history("user", text)
        history = list(self._chat_history[-self.chat_history_max:])

        # 2. 聊天回复与情绪映射并行（asyncio.gather）：
        #    LLM 调用期间先广播中性表情（角色"倾听中"），避免表情冻结
        neutral_cmd = expression_for("neutral")
        llm_task = asyncio.create_task(llm.chat(user_text=text, history=history))
        await self._dispatch(neutral_cmd)
        result = await llm_task
        logger.info("[LLM] %s (emotion=%s intensity=%.2f)",
                    result.reply, result.emotion, result.intensity)

        # 3. 情绪 → expression / motion；并行动作广播（asyncio.gather）
        cmds = map_emotion(result, intensity=result.intensity)
        if cmds:
            await asyncio.gather(*(self._dispatch(c) for c in cmds))
            logger.info("[情绪] 已并行广播 %d 条指令: %s",
                        len(cmds), [c["type"] for c in cmds])

        # 4. TTS + 口型
        tts_kwargs = self._tts_kwargs() if self.tts_config else {}
        tts = TTSClient(**tts_kwargs)
        tts_result = await tts.synthesize(result.reply)
        logger.info("[TTS] 合成 %.2fs 音频, %d 帧口型 (帧间隔 %dms, 引擎 %s)",
                    tts_result.duration_ms / 1000.0,
                    len(tts_result.lipsync), tts_result.frame_ms,
                    tts_result.engine)

        # 播放期间持续推送口型（iter_lipsync 按帧时间戳推进）
        await self.send_command({"type": "lipsync", "value": 0.0})
        async for frame in tts.iter_lipsync(tts_result):
            await self.send_command({"type": "lipsync", "value": frame.value})

        # 口型回零，等待 C++ 端 200ms 超时逻辑接管
        await asyncio.sleep(0.05)
        await self.send_command({"type": "lipsync", "value": 0.0})

        # 5. 记录助手回复到历史
        self._append_history("assistant", result.reply)
        logger.info("[chat] 管线演示完成")

    def _tts_kwargs(self) -> dict:
        """把 config.py 解析出的 TTSConfig 转为 TTSClient 构造参数。"""
        tts = self.tts_config
        return {
            "engine": tts.engine,
            "voice": tts.voice,
            "rate": tts.rate,
            "sample_rate": tts.sample_rate,
            "base_url": tts.base_url,
            "api_key": tts.api_key,
            "model": tts.model,
            "speed": tts.speed,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """启动服务并进入主循环，直到 stop() 被调用。"""
        self._stop_event = asyncio.Event()
        try:
            self._server = await websockets.serve(
                self._handle_client, self.host, self.port)
        except OSError as exc:
            logger.error("监听 %s:%d 失败: %s", self.host, self.port, exc)
            raise

        logger.info("L2D 控制服务已启动: ws://%s:%d%s (echo=%s)",
                    self.host, self.port, self.path, self.echo)
        self._start_interactive()

        # 启动时先发送 --send 指定的指令
        for cmd in self.send_cmds:
            await self._handle_command_line(cmd)

        try:
            async with self._server:
                await self._stop_event.wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """关闭服务与所有客户端连接（幂等）。"""
        self._shutdown = True
        if self._stop_event is not None:
            self._stop_event.set()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        for cid, ws in list(self.clients.items()):
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self.clients.clear()
        logger.info("服务已关闭")


# ---------------------------------------------------------------------------
# 模块级便捷函数（供 llm_client / tts_client / 自定义 AI 管线调用）
# ---------------------------------------------------------------------------
async def send_command(command: Any, target_ids=None, exclude_ids=None) -> int:
    """向所有已连接客户端广播指令。

    示例：
        await send_command({"type": "expression", "name": "F01"})
        await send_command(("motion", {"group": "TapBody", "no": 0, "priority": 3}))
        await send_command('{"type": "lipsync", "value": 0.5}')
    """
    if SERVER is None:
        raise RuntimeError("服务器尚未启动，无法发送指令")
    return await SERVER.send_command(command, target_ids=target_ids,
                                     exclude_ids=exclude_ids)


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
def parse_args(argv=None, defaults: dict | None = None) -> argparse.Namespace:
    """解析命令行参数。

    :param defaults: 由 config.yaml 解析出的默认值（{host, port, path, model_dir}）。
        CLI 参数优先于 config.yaml，config.yaml 优先于环境变量与内置默认值。
    """
    defaults = defaults or {}
    parser = argparse.ArgumentParser(
        description="L2D 控制系统 WebSocket 服务端（Phase 2）")
    parser.add_argument("--host", default=defaults.get("host", "0.0.0.0"),
                        help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=defaults.get("port", 3000),
                        help="监听端口 (默认 3000)")
    parser.add_argument("--path", default=defaults.get("path", "/ws"),
                        help="WebSocket 路径 (默认 /ws)")
    parser.add_argument("--model-dir", default=defaults.get("model_dir"),
                        help="Live2D 模型目录（供 model_scanner 扫描，可选）")
    parser.add_argument("--echo", action="store_true",
                        help="echo 测试模式：回显客户端消息 + 对新客户端自动播放测试序列")
    parser.add_argument("--allow-any-path", action="store_true",
                        help="接受任意路径的连接 (默认仅接受 --path)")
    parser.add_argument("--no-interactive", action="store_true",
                        help="不启动终端交互输入")
    parser.add_argument("--send", dest="send_cmds", action="append", metavar="CMD",
                        help="启动后广播一条指令，如 --send \"expression F01\"；可多次指定")
    parser.add_argument("--log-level", default="INFO",
                        help="日志级别 (DEBUG/INFO/WARNING)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    # 加载可选 config.yaml（字段级继承），未提供时回退环境变量与默认值
    from config import load_config

    cfg = load_config()
    args = parse_args(argv, defaults={
        "host": cfg.server.host,
        "port": cfg.server.port,
        "path": cfg.server.path,
        "model_dir": cfg.model_dir,
    })
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # 模型扫描器（可选；目录不存在或解析失败时自动禁用）
    scanner = None
    try:
        from model_scanner import ModelScanner
        scanner = ModelScanner(args.model_dir)
        if not scanner.available:
            logger.warning("模型目录不存在，model_scanner 已禁用: %s",
                           scanner.base_dir)
            scanner = None
        else:
            scanner.scan()
            if scanner.switch_models:
                logger.info("可用模型（switch 索引）: %s",
                            ", ".join(scanner.model_names()))
            else:
                logger.info("模型目录内未发现 <目录名>/<目录名>.model3.json，"
                            "switch 索引为空: %s", scanner.base_dir)
    except Exception as exc:  # noqa: BLE001 - 扫描失败不应阻断服务启动
        logger.warning("model_scanner 初始化失败，已禁用: %s", exc)
        scanner = None

    # 构建 LLM / TTS 配置（config.yaml > 环境变量 > 默认值）
    from llm_client import LLMConfig as LLMClientConfig
    llm_config = LLMClientConfig.from_dict(cfg.llm.chat.to_dict())

    global SERVER
    SERVER = L2DServer(
        host=args.host,
        port=args.port,
        path=args.path,
        echo=args.echo,
        allow_any_path=args.allow_any_path,
        no_interactive=args.no_interactive,
        send_cmds=args.send_cmds or [],
        model_scanner=scanner,
        llm_config=llm_config,
        tts_config=cfg.tts,
    )
    try:
        asyncio.run(SERVER.run())
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，服务退出。")
    except OSError as exc:
        logger.error("启动失败: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
