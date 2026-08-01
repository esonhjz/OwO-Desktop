#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_client.py — TTS 语音合成 + LipSync 值生成（Phase 2 增强）
================================================================

职责：
  - 封装 TTS 合成，输出 **音频数据 + 单词/音节时间戳**
  - 根据 **音量包络** 或 **时间戳** 生成 lipsync 值序列（0.0~1.0），
    供 server.py 按帧频推送给 OwO-Desktop C++ 客户端
  - 提供 **mock 模式**：离线合成模拟语音波形，无需任何外部服务即可联调

Phase 2 增强（借鉴 SoulLink `src/generators/tts.py` 的 OpenAI 兼容 TTS 设计）：
- 新增 **openai 引擎**：`POST {base_url}/audio/speech`，输出 MP3
  （经 OpenAI 兼容 SDK 调用；base_url 可指向任意兼容服务）
- **流式合成**：`synthesize_stream()` 逐块产出音频字节，供边播边收
- **播放期持续口型**：`iter_lipsync()` 按帧时间戳持续产出 lipsync 帧，
  server 可在 TTS 播放期间持续推送（C++ 端 200ms 超时自动闭合兜底）
- 保留既有的 **两套口型算法**：音量包络（compute_volume_lipsync）与
  时间戳（lipsync_from_word_boundaries）

协议约定（与 ../src/NetworkManager.cpp 严格一致）：

    {"type": "lipsync", "value": 0.75}   # 0.0=闭合，1.0=完全张开

环境变量：
  TTS_ENGINE       —— mock | edge-tts | openai（默认 mock）
  TTS_VOICE        —— 发音人（默认 zh-CN-XiaoxiaoNeural；openai 引擎默认 alloy）
  TTS_RATE         —— 语速，如 +0%、-10%（仅 edge-tts）
  TTS_SAMPLE_RATE  —— mock 模式采样率（默认 24000）
  TTS_BASE_URL     —— OpenAI 兼容 TTS 服务地址（默认 https://api.openai.com/v1）
  TTS_API_KEY      —— OpenAI 兼容 TTS 密钥（openai 引擎必需）
  TTS_MODEL        —— TTS 模型（默认 tts-1）
  TTS_SPEED        —— 语速倍数 0.25~4.0（openai 引擎，默认 1.0）

用法示例：

    from tts_client import TTSClient

    tts = TTSClient()
    result = await tts.synthesize("你好，很高兴见到你！")
    async for frame in tts.iter_lipsync(result):   # 播放期间持续推送口型
        await send_command({"type": "lipsync", "value": frame.value})
"""

from __future__ import annotations  # 使 `X | None` 等标注在 Python 3.9 也可用

import asyncio
import io
import logging
import math
import os
import wave
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class WordBoundary:
    """一个单词/音节的起止时间戳。"""

    start_ms: int
    end_ms: int
    word: str


@dataclass
class LipsyncFrame:
    """一帧口型采样点。"""

    t_ms: int      # 相对音频起始的时间（毫秒）
    value: float   # 0.0~1.0 口型张合度


@dataclass
class TTSResult:
    """一次 TTS 合成的完整结果。"""

    text: str
    audio_bytes: bytes = b""                    # 音频数据（mock=WAV；edge-tts/openai=MP3）
    sample_rate: int = 0                        # 音频采样率（MP3 未解码时为 0）
    duration_ms: int = 0                        # 音频时长（毫秒）
    word_boundaries: list = field(default_factory=list)   # 单词时间戳
    lipsync: list = field(default_factory=list)            # LipsyncFrame 序列
    frame_ms: int = 30                          # 口型帧间隔（毫秒）
    engine: str = "mock"
    audio_path: str = ""                        # 落盘路径（非空表示已保存）


# ---------------------------------------------------------------------------
# 音量包络 → lipsync
# ---------------------------------------------------------------------------
def compute_volume_lipsync(audio_bytes: bytes, sample_rate: int,
                           frame_ms: int = 30,
                           attack: float = 0.5, release: float = 0.2,
                           noise_floor: float = 0.02) -> list[LipsyncFrame]:
    """根据音频音量包络（RMS）生成 lipsync 值序列。

    每 frame_ms 一帧：先按帧计算 RMS 音量，再归一化并用 attack/release
    平滑，模拟说话时口型随音量张合的效果。

    :param audio_bytes: PCM16（WAV）音频字节
    :param sample_rate: 采样率
    :param frame_ms: 帧间隔（毫秒），对应 C++ 端约 30fps 的推送节奏
    :param attack: 上升平滑系数（0~1，越大响应越快）
    :param release: 下降平滑系数
    :param noise_floor: 低于该归一化值的帧直接置 0（抑制底噪导致的张嘴）
    """
    import array

    # 只处理偶数长度的 PCM 字节，忽略尾部奇数残留
    usable = audio_bytes[: len(audio_bytes) // 2 * 2]
    samples = array.array("h")
    samples.frombytes(usable)
    if not samples:
        return [LipsyncFrame(0, 0.0)]

    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    rms_list: list[float] = []
    n = len(samples)
    for i in range(0, n, frame_size):
        chunk = samples[i:i + frame_size]
        acc = sum(s * s for s in chunk)
        rms_list.append(math.sqrt(acc / len(chunk)))
    if not rms_list:
        return [LipsyncFrame(0, 0.0)]

    peak = max(rms_list)
    # 归一化并放大 1.25 倍再钳制，使中等音量也能达到较高的口型开合
    scaled = [min(1.0, v / peak * 1.25) if peak > 0 else 0.0 for v in rms_list]

    # attack / release 平滑
    prev = 0.0
    smoothed: list[float] = []
    for v in scaled:
        if v > prev:
            prev = prev + attack * (v - prev)
        else:
            prev = prev + release * (v - prev)
        smoothed.append(prev)

    frames: list[LipsyncFrame] = []
    t_ms = 0
    for v in smoothed:
        value = v if v >= noise_floor else 0.0
        frames.append(LipsyncFrame(t_ms, round(min(1.0, value), 3)))
        t_ms += frame_ms
    return frames


# ---------------------------------------------------------------------------
# 时间戳 → lipsync
# ---------------------------------------------------------------------------
def lipsync_from_word_boundaries(word_boundaries: Iterable[WordBoundary],
                                 duration_ms: int,
                                 frame_ms: int = 30,
                                 base: float = 0.08,
                                 peak: float = 1.0) -> list[LipsyncFrame]:
    """根据单词/音节时间戳生成 lipsync 值序列。

    处于词边界区间内的帧按正弦包络打开口型，其余帧回落到 base。
    用于真实 TTS 仅提供时间戳、无法直接解码音频波形时的口型驱动。

    :param word_boundaries: WordBoundary 列表
    :param duration_ms: 音频总时长（毫秒）
    :param frame_ms: 帧间隔（毫秒）
    :param base: 静音段口型基线（微张）
    :param peak: 词边界内口型峰值
    """
    bounds = list(word_boundaries or [])
    if duration_ms <= 0:
        duration_ms = (bounds[-1].end_ms if bounds else 1000)
    frames: list[LipsyncFrame] = []
    t = 0
    while t < duration_ms:
        value = base
        for b in bounds:
            if b.start_ms <= t < b.end_ms:
                span = max(1, b.end_ms - b.start_ms)
                pos = (t - b.start_ms) / span
                value = base + (peak - base) * abs(math.sin(math.pi * pos))
                break
        frames.append(LipsyncFrame(t, round(min(1.0, value), 3)))
        t += frame_ms
    return frames


def build_lipsync(audio_bytes: bytes | None = None, sample_rate: int = 0,
                  word_boundaries: Iterable[WordBoundary] | None = None,
                  duration_ms: int = 0, frame_ms: int = 30,
                  prefer: str = "envelope") -> list[LipsyncFrame]:
    """统一的 lipsync 生成入口。

    - prefer="envelope" 且提供可解码的 PCM 波形 → 音量包络法
    - 否则回退到时间戳法（需要 word_boundaries + duration_ms）
    """
    if audio_bytes and sample_rate > 0 and prefer == "envelope":
        return compute_volume_lipsync(audio_bytes, sample_rate, frame_ms=frame_ms)
    return lipsync_from_word_boundaries(word_boundaries, duration_ms, frame_ms=frame_ms)


# ---------------------------------------------------------------------------
# mock 音频合成（无第三方依赖，确定性输出便于联调）
# ---------------------------------------------------------------------------
def synthesize_mock_audio(text: str, sample_rate: int = 24000,
                          duration_ms: int = 0,
                          out_path: str = "") -> tuple[bytes, int]:
    """合成一段确定性「模拟语音」WAV（PCM16 单声道）。

    以文本字符编码为随机种子，按字符构造「音节 → 音量包络」的近似语音，
    时长随文本长度估算（每字符约 150ms，最短 1.2s）。

    :return: (wav 字节, 时长毫秒)
    """
    text = (text or " ").strip() or "a"
    if not duration_ms:
        duration_ms = max(1200, int(len(text) * 150))
    total = int(sample_rate * duration_ms / 1000)
    per_char = max(1, total / len(text))

    import array
    samples = array.array("h")
    for i in range(total):
        ch = text[min(len(text) - 1, int(i / per_char))]
        base_freq = 130.0 + (ord(ch) % 40)                 # 130~170Hz 随字符变化
        pos = (i % per_char) / per_char
        envelope = abs(math.sin(math.pi * pos))            # 音节包络
        tremolo = 0.85 + 0.15 * math.sin(2 * math.pi * 3.0 * i / sample_rate)
        val = (
            math.sin(2 * math.pi * base_freq * i / sample_rate) * 0.6
            + math.sin(2 * math.pi * base_freq * 2 * i / sample_rate) * 0.3
            + math.sin(2 * math.pi * base_freq * 3 * i / sample_rate) * 0.1
        )
        samples.append(int(val * envelope * tremolo * 14000))
    data = samples.tobytes()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(data)
    if out_path:
        with open(out_path, "wb") as f:
            f.write(buf.getvalue())
    return buf.getvalue(), duration_ms


def _mock_word_boundaries(text: str, duration_ms: int) -> list[WordBoundary]:
    """把文本切成约 2 字符的音节，按等时长生成模拟词边界。"""
    text = (text or " ").strip() or "a"
    if len(text) <= 2:
        units = [text]
    else:
        units = [text[i:i + 2] for i in range(0, len(text), 2)]
    per = duration_ms / len(units)
    return [WordBoundary(int(i * per), int((i + 1) * per), unit)
            for i, unit in enumerate(units)]


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
class TTSClient:
    """TTS 合成封装。

    engine=mock（默认）：离线合成模拟音频 + 音量包络 lipsync；
    engine=edge-tts：使用微软 Edge TTS，输出 MP3 + 词边界时间戳 → 时间戳法 lipsync；
    engine=openai：OpenAI 兼容 TTS（POST {base_url}/audio/speech，MP3），
      未解码 MP3 时以文本音节估算时长与词边界 → 时间戳法 lipsync。
    """

    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"   # edge-tts 默认
    DEFAULT_OPENAI_VOICE = "alloy"           # openai 兼容 TTS 默认
    DEFAULT_OPENAI_MODEL = "tts-1"

    def __init__(self, engine: str | None = None, voice: str | None = None,
                 rate: str | None = None, sample_rate: int = 24000,
                 base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, speed: float = 1.0):
        self.engine = (engine or os.environ.get("TTS_ENGINE", "mock")).lower()
        self.base_url = (base_url or os.environ.get("TTS_BASE_URL", "")
                         ).strip().rstrip("/")
        self.api_key = api_key or os.environ.get("TTS_API_KEY", "")
        self.model = model or os.environ.get("TTS_MODEL", self.DEFAULT_OPENAI_MODEL)
        try:
            self.speed = float(speed if speed is not None
                               else os.environ.get("TTS_SPEED", "1.0"))
        except (TypeError, ValueError):
            self.speed = 1.0
        self.rate = rate or os.environ.get("TTS_RATE", "+0%")
        self.sample_rate = int(os.environ.get("TTS_SAMPLE_RATE", str(sample_rate)))

        if self.engine in ("openai", "api") and not voice:
            self.voice = os.environ.get("TTS_VOICE", self.DEFAULT_OPENAI_VOICE)
        else:
            self.voice = voice or os.environ.get("TTS_VOICE", self.DEFAULT_VOICE)

    @property
    def is_mock(self) -> bool:
        return self.engine in ("mock", "none", "")

    @property
    def is_openai(self) -> bool:
        return self.engine in ("openai", "api")

    # ------------------------------------------------------------------
    # 对外主入口
    # ------------------------------------------------------------------
    async def synthesize(self, text: str, out_path: str = "",
                         frame_ms: int = 30) -> TTSResult:
        """合成语音并计算 lipsync 值序列。

        :param text: 要合成的文本
        :param out_path: 可选，音频落盘路径（WAV/MP3）
        :param frame_ms: 口型帧间隔（毫秒）
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("待合成文本为空")

        if self.is_mock:
            return await self._synthesize_mock(text, out_path, frame_ms)
        if self.engine == "edge-tts":
            return await self._synthesize_edge_tts(text, out_path, frame_ms)
        if self.is_openai:
            return await self._synthesize_openai(text, out_path, frame_ms)
        raise ValueError(
            f"未知 TTS 引擎: {self.engine}（可用: mock / edge-tts / openai）")

    # ------------------------------------------------------------------
    # mock 合成
    # ------------------------------------------------------------------
    async def _synthesize_mock(self, text, out_path, frame_ms) -> TTSResult:
        audio, duration_ms = synthesize_mock_audio(text, self.sample_rate, out_path=out_path)
        boundaries = _mock_word_boundaries(text, duration_ms)
        lipsync = compute_volume_lipsync(audio, self.sample_rate, frame_ms=frame_ms)
        return TTSResult(
            text=text,
            audio_bytes=audio,
            sample_rate=self.sample_rate,
            duration_ms=duration_ms,
            word_boundaries=boundaries,
            lipsync=lipsync,
            frame_ms=frame_ms,
            engine="mock",
            audio_path=out_path,
        )

    # ------------------------------------------------------------------
    # edge-tts 合成（输出 MP3 + 词边界时间戳）
    # ------------------------------------------------------------------
    async def _synthesize_edge_tts(self, text, out_path, frame_ms) -> TTSResult:
        # 延迟导入：仅使用 edge-tts 引擎时才需要该依赖
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        audio_chunks: list[bytes] = []
        boundaries: list[WordBoundary] = []
        async for chunk in communicate.stream():
            ctype = chunk.get("type")
            if ctype == "audio":
                audio_chunks.append(chunk.get("data", b""))
            elif ctype in ("WordBoundary", "SentenceBoundary"):
                offset = int(chunk.get("offset", 0))      # 单位：100ns
                duration = int(chunk.get("duration", 0))
                boundaries.append(WordBoundary(
                    start_ms=offset // 10000,
                    end_ms=(offset + duration) // 10000,
                    word=chunk.get("text", ""),
                ))

        audio = b"".join(audio_chunks)
        if boundaries:
            duration_ms = max(1, boundaries[-1].end_ms)
        else:
            # 无时间戳时按 MP3 字节数粗略估算（~128kbps ≈ 16 B/ms）
            duration_ms = max(1, int(len(audio) / 16))
        if out_path:
            with open(out_path, "wb") as f:
                f.write(audio)

        # edge-tts 输出为 MP3，未经解码无法做音量包络 → 使用时间戳法
        lipsync = lipsync_from_word_boundaries(boundaries, duration_ms, frame_ms=frame_ms)
        return TTSResult(
            text=text,
            audio_bytes=audio,
            sample_rate=0,               # MP3 未解码，采样率未知
            duration_ms=duration_ms,
            word_boundaries=boundaries,
            lipsync=lipsync,
            frame_ms=frame_ms,
            engine="edge-tts",
            audio_path=out_path,
        )

    # ------------------------------------------------------------------
    # OpenAI 兼容 TTS 合成（POST {base_url}/audio/speech → MP3）
    # ------------------------------------------------------------------
    def _build_openai_client(self):
        """延迟构造 OpenAI 兼容客户端（复用 openai SDK，无需新增依赖）。"""
        if not self.api_key:
            raise ValueError(
                "OpenAI 兼容 TTS 需要 TTS_API_KEY（或 config.yaml 的 tts.apiKey）")
        import openai
        return openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=60,
        )

    async def _synthesize_openai(self, text, out_path, frame_ms) -> TTSResult:
        client = self._build_openai_client()
        resp = await client.audio.speech.create(
            model=self.model,
            input=text,
            voice=self.voice,
            speed=self.speed,
            response_format="mp3",
        )
        audio = resp.content or b""
        if out_path:
            with open(out_path, "wb") as f:
                f.write(audio)

        # MP3 未解码 → 时长按字节估算（~128kbps ≈ 16 B/ms）；
        # 口型用「文本音节 → 词边界」时间戳法（两套算法之一）。
        duration_ms = max(1, int(len(audio) / 16))
        boundaries = _mock_word_boundaries(text, duration_ms)
        lipsync = lipsync_from_word_boundaries(boundaries, duration_ms, frame_ms=frame_ms)
        return TTSResult(
            text=text,
            audio_bytes=audio,
            sample_rate=0,
            duration_ms=duration_ms,
            word_boundaries=boundaries,
            lipsync=lipsync,
            frame_ms=frame_ms,
            engine="openai",
            audio_path=out_path,
        )

    # ------------------------------------------------------------------
    # 流式合成（OpenAI 兼容引擎）
    # ------------------------------------------------------------------
    async def synthesize_stream(self, text: str, voice: str | None = None,
                                chunk_size: int = 1024):
        """流式合成音频（OpenAI 兼容引擎），逐块产出音频字节。

        借鉴 SoulLink `tts.py::generate_stream` 的流式设计，针对本项目
        协议重写（经 openai SDK 的 with_streaming_response）。
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("待合成文本为空")
        if not self.is_openai:
            raise ValueError("synthesize_stream 仅支持 openai 引擎")
        client = self._build_openai_client()
        selected_voice = voice or self.voice

        async with client.audio.speech.with_streaming_response.create(
            model=self.model,
            input=text,
            voice=selected_voice,
            speed=self.speed,
            response_format="mp3",
        ) as response:
            async for chunk in response.iter_bytes(chunk_size):
                yield chunk

    # ------------------------------------------------------------------
    # 播放期持续口型（供 server 在 TTS 播放期间持续推送 lipsync）
    # ------------------------------------------------------------------
    async def iter_lipsync(self, result: TTSResult,
                           tick_ms: int | None = None):
        """按帧时间戳持续产出口型帧。

        相邻帧按时间差 sleep，避免一次性全量推送；与 server 的 chat 管线
        原实现一致，但封装为可复用生成器。C++ 端 200ms 无更新自动闭合，
        即使推送中断口型也能平滑回零。

        :param result: synthesize() 返回的结果
        :param tick_ms: 可选，固定推送间隔（毫秒）；缺省按帧时间戳自然推进
        """
        last_t = 0
        for frame in result.lipsync:
            if tick_ms:
                await asyncio.sleep(tick_ms / 1000.0)
            else:
                dt = max(0.0, (frame.t_ms - last_t) / 1000.0)
                last_t = frame.t_ms
                if dt:
                    await asyncio.sleep(dt)
            yield frame


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def save_wav(audio_bytes: bytes, path: str) -> None:
    """把 WAV 字节落盘（便于后续试听/波形分析）。"""
    with open(path, "wb") as f:
        f.write(audio_bytes)


async def stream_lipsync(frames: Iterable[LipsyncFrame], tick_ms: int = 100):
    """按帧频异步产出 lipsync 帧（模块级便捷函数，兼容既有引用）。

    用于后续集成：一边播放音频一边把口型帧推送到 C++ 端。
    tick_ms 为模拟的推送间隔（毫秒）。
    """
    for frame in frames:
        yield frame
        await asyncio.sleep(tick_ms / 1000.0)


if __name__ == "__main__":
    # 自测：python tts_client.py
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async def _main():
        tts = TTSClient()   # mock 模式
        result = await tts.synthesize("你好，很高兴见到你！")
        logging.info("时长=%dms, 词边界=%d, 口型帧=%d, 引擎=%s",
                     result.duration_ms, len(result.word_boundaries),
                     len(result.lipsync), result.engine)
        logging.info("前 5 帧口型: %s", [(f.t_ms, f.value) for f in result.lipsync[:5]])

        # 验证时间戳法
        frames = lipsync_from_word_boundaries(
            [WordBoundary(0, 300, "你"), WordBoundary(300, 600, "好")], 900)
        logging.info("时间戳法前 5 帧: %s", [(f.t_ms, f.value) for f in frames[:5]])

        # 验证播放期持续口型生成器
        collected = []
        async for frame in tts.iter_lipsync(result):
            collected.append(frame)
            if len(collected) >= 3:
                break
        logging.info("iter_lipsync 持续推送 %d 帧: %s",
                     len(collected), [(f.t_ms, f.value) for f in collected])

    asyncio.run(_main())
