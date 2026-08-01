"""python-backend Phase 2 新增功能测试（自包含，不依赖 pytest / 网络）。

覆盖：config.yaml 字段级继承、model_scanner 索引、emotion_mapper 关键词兜底
与 intensity 联动、llm_client 缓存与 API 失败兜底、tts_client OpenAI 兼容引擎。
运行：.venv/Scripts/python.exe test_phase2.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# 1) config.yaml 字段级继承
# ---------------------------------------------------------------------------
def test_config():
    import config as config_mod
    from config import load_config

    if config_mod.yaml is None:      # 未安装 PyYAML 时跳过该测试
        print("SKIP config（未安装 PyYAML）")
        return

    with tempfile.TemporaryDirectory() as tmp:
        conf = Path(tmp) / "config.yaml"
        conf.write_text(
            "server:\n"
            "  host: 127.0.0.9\n"
            "  port: 4321\n"
            "llm:\n"
            "  api:\n"
            "    apiKey: sk-test\n"
            "    model: gpt-4o-mini\n"
            "    temperature: 0.15\n"
            "  chat:\n"
            "    model: gpt-4o\n"          # 缺省 temperature → 继承 api 的 0.15
            "tts:\n"
            "  engine: openai\n"
            "  voice: nova\n"
            "model:\n"
            "  directory: /tmp/mymodels\n",
            encoding="utf-8",
        )
        cfg = load_config(str(conf))
        assert cfg.server.host == "127.0.0.9"
        assert cfg.server.port == 4321
        assert cfg.llm.api.api_key == "sk-test"
        assert cfg.llm.api.temperature == 0.15
        # 字段级继承：chat.model 显式指定，chat.temperature 继承 api
        assert cfg.llm.chat.model == "gpt-4o"
        assert cfg.llm.chat.temperature == 0.15
        assert cfg.llm.chat.api_key == "sk-test"
        assert cfg.tts.engine == "openai"
        assert cfg.tts.voice == "nova"
        assert cfg.model_dir == "/tmp/mymodels"
    print("OK  config 字段级继承")


# ---------------------------------------------------------------------------
# 2) model_scanner
# ---------------------------------------------------------------------------
def test_model_scanner():
    from model_scanner import ModelScanner

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # C++ 兼容：<目录>/<目录名>.model3.json
        haru = root / "Haru" / "Haru.model3.json"
        haru.parent.mkdir(parents=True)
        haru.write_text(json.dumps({
            "FileReferences": {
                "Expressions": [{"Name": "F01", "File": "exp/F01.exp3.json"},
                                {"Name": "F02", "File": "exp/F02.exp3.json"}],
                "Motions": {
                    "Idle": [{"File": "m/idle.motion3.json"}],
                    "TapBody": [{"File": "m/t1.motion3.json"},
                                {"File": "m/t2.motion3.json"}],
                },
            }
        }), encoding="utf-8")

        rice = root / "Rice" / "Rice.model3.json"
        rice.parent.mkdir(parents=True)
        rice.write_text(json.dumps({"FileReferences": {"Expressions": []}}), encoding="utf-8")
        (root / "Rice" / "model_prompt.txt").write_text(
            "此模型头部转动范围较小。", encoding="utf-8")

        # 嵌套模型：不在 C++ 兼容索引内（父目录名 ≠ model3 基名）
        nested = root / "murasame" / "model" / "murasame.model3.json"
        nested.parent.mkdir(parents=True)
        nested.write_text(json.dumps({"FileReferences": {}}), encoding="utf-8")
        root_model = root / "murasame" / "murasame.model3.json"
        root_model.parent.mkdir(parents=True, exist_ok=True)
        root_model.write_text(json.dumps({"FileReferences": {}}), encoding="utf-8")

        scanner = ModelScanner(str(root))
        scanner.scan()

        # 全部发现 4 个（含嵌套）
        assert len(scanner.models) == 4, [m.name for m in scanner.models]
        # switch 索引仅 3 个（嵌套的 murasame/model/... 被排除）
        assert len(scanner.switch_models) == 3
        # 大小写敏感字典序（对应 C++ strcmp）：Haru < Rice < murasame
        names = [m.name for m in scanner.switch_models]
        assert names == ["Haru", "Rice", "murasame"], names

        haru_info = scanner.switch_models[0]
        assert haru_info.expressions == ["F01", "F02"]
        assert haru_info.motion_groups == {"Idle": 1, "TapBody": 2}

        rice_info = scanner.index_of("Rice")
        assert rice_info == 1
        assert "头部转动范围" in scanner.switch_models[1].custom_prompt

        frag = scanner.build_prompt_fragment(0)
        assert "F01" in frag and "TapBody(2)" in frag
    print("OK  model_scanner 索引与 Prompt 片段")


# ---------------------------------------------------------------------------
# 3) emotion_mapper：关键词兜底 / 新情绪 / intensity 联动
# ---------------------------------------------------------------------------
def test_emotion_mapper():
    from emotion_mapper import (keyword_fallback, map_emotion,
                                normalize_emotion, priority_for_intensity)

    # 关键词兜底（借鉴 SoulLink local_expression）
    assert keyword_fallback("今天好开心呀")[0] == "joy"
    assert keyword_fallback("我有点担心")[0] == "worried"
    assert keyword_fallback("") == ("neutral", 0.5)
    label, intensity = keyword_fallback("我害怕")
    assert label == "fear" and intensity >= 0.7

    # 新情绪归一化
    assert normalize_emotion("思考") == "thinking"
    assert normalize_emotion("love") == "love"
    assert normalize_emotion("annoyed") == "annoyed"

    # intensity 联动 motion priority
    assert priority_for_intensity(3, 0.9) == 4
    assert priority_for_intensity(3, 0.3) == 2
    assert priority_for_intensity(3, 0.6) == 3
    assert priority_for_intensity(5, 0.9) == 5    # 上限钳制

    # map_emotion：默认 intensity=1.0 → priority +1；低强度只发表情
    joy_cmds = map_emotion("joy")
    assert joy_cmds[0] == {"type": "expression", "name": "F01"}
    assert joy_cmds[1]["priority"] == 4           # 3 + 1（intensity 1.0 ≥ 0.75）
    low_cmds = map_emotion("joy", intensity=0.2)
    assert len(low_cmds) == 1                     # 只发表情
    print("OK  emotion_mapper 兜底/新情绪/intensity")


# ---------------------------------------------------------------------------
# 4) llm_client：缓存 / API 失败兜底 / 动态提示词
# ---------------------------------------------------------------------------
def test_llm_client():
    import llm_client

    # 4a. mock 模式 + 文本缓存命中
    from llm_client import LLMClient, LLMConfig
    client = LLMClient()
    async def run_mock():
        r1 = await client.chat(user_text="今天好开心呀")
        assert r1.emotion == "joy"
        assert r1.intensity >= 0.7
        r2 = await client.chat(user_text="今天好开心呀")   # 命中缓存
        assert r2 is r1
        assert client.cache_hits >= 1
    asyncio.run(run_mock())

    # 4b. 动态系统提示词注入
    client.set_model_context(expressions=["F01", "F02"],
                             motions=["Idle", "TapBody"],
                             model_prompt="开关型参数只输出 0 或 1")
    prompt = client._build_system_prompt()
    assert "表情控制器" in prompt
    assert "F01" in prompt and "TapBody" in prompt
    assert "开关型参数" in prompt
    assert "intensity" in prompt

    # 4c. API 失败 → 本地兜底（用假 openai 模块触发异常）
    fake_calls = {"n": 0}

    class _FakeCompletions:
        async def create(self, **kwargs):
            fake_calls["n"] += 1
            raise RuntimeError("network down")

    class _FakeChat:
        @property
        def completions(self):
            return _FakeCompletions()

    class _FakeOpenAIModule:
        class AsyncOpenAI:
            def __init__(self, **kwargs):
                pass

            @property
            def chat(self):
                return _FakeChat()

    saved = sys.modules.get("openai")
    sys.modules["openai"] = _FakeOpenAIModule()
    try:
        cfg = LLMConfig(api_key="sk-fake", base_url="https://x.example/v1")
        fail_client = LLMClient(config=cfg)
        async def run_fail():
            r = await fail_client.chat(user_text="我有点担心明天的考试")
            assert r.emotion == "worried"
            assert fake_calls["n"] == 1
            # 第二次同样输入 → 文本缓存命中，不再触发 API
            r2 = await fail_client.chat(user_text="我有点担心明天的考试")
            assert r2 is r and fake_calls["n"] == 1
        asyncio.run(run_fail())
    finally:
        if saved is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = saved
    print("OK  llm_client 缓存/兜底/动态提示词")


# ---------------------------------------------------------------------------
# 5) tts_client：OpenAI 兼容引擎（假 openai 模块） / 流式 / iter_lipsync
# ---------------------------------------------------------------------------
def test_tts_openai():
    import tts_client

    fake_audio = b"ID3" + b"\x00" * 5000   # 模拟 MP3 字节（约 300ms，保证有足够口型帧）
    streamed = []

    class _FakeResp:
        def __init__(self, content: bytes):
            self.content = content

    class _FakeSpeech:
        async def create(self, **kwargs):
            assert kwargs["response_format"] == "mp3"
            return _FakeResp(fake_audio)

        @property
        def with_streaming_response(self):
            return _FakeStreaming()

    class _FakeStreaming:
        def create(self, **kwargs):
            return _FakeStreamingCM()

    class _FakeStreamingCM:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def iter_bytes(self, chunk_size=None):
            return _FakeIterBytes()

    class _FakeIterBytes:
        def __init__(self):
            self._chunks = [b"aaa", b"bbb"]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._chunks:
                raise StopAsyncIteration
            return self._chunks.pop(0)

    class _FakeAudio:
        @property
        def speech(self):
            return _FakeSpeech()

    class _FakeOpenAIModule:
        class AsyncOpenAI:
            def __init__(self, **kwargs):
                pass

            @property
            def audio(self):
                return _FakeAudio()

    saved = sys.modules.get("openai")
    sys.modules["openai"] = _FakeOpenAIModule()
    try:
        from tts_client import TTSClient, TTSResult

        # 非流式合成
        async def run_synth():
            tts = TTSClient(engine="openai", api_key="sk-fake",
                            voice="nova", model="tts-1")
            result = await tts.synthesize("你好呀")
            assert result.engine == "openai"
            assert result.audio_bytes == fake_audio
            assert result.duration_ms >= 1
            assert len(result.lipsync) > 0
            # 两套口型算法之一（时间戳法）生成的帧
            assert result.lipsync[0].t_ms == 0
        asyncio.run(run_synth())

        # 流式合成（迭代产出音频块）
        async def run_stream():
            tts = TTSClient(engine="openai", api_key="sk-fake")
            async for chunk in tts.synthesize_stream("流式测试"):
                streamed.append(chunk)
        asyncio.run(run_stream())
        assert streamed == [b"aaa", b"bbb"]

        # 播放期持续口型（iter_lipsync 只产出前 3 帧，验证可中断）
        async def run_lipsync():
            tts = TTSClient(engine="openai", api_key="sk-fake")
            result = await tts.synthesize("你好")
            frames = []
            async for frame in tts.iter_lipsync(result):
                frames.append(frame)
                if len(frames) >= 3:
                    break
            assert len(frames) == 3
        asyncio.run(run_lipsync())
    finally:
        if saved is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = saved
    print("OK  tts_client OpenAI 兼容引擎 / 流式 / iter_lipsync")


def main() -> int:
    test_config()
    test_model_scanner()
    test_emotion_mapper()
    test_llm_client()
    test_tts_openai()
    print("ALL PHASE2 TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
