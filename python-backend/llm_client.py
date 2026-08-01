#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_client.py — LLM 调用封装（Phase 2 增强）
================================================================

职责：
  - 以 **OpenAI 兼容接口** 调用 LLM（环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）
  - 通过系统提示词 **强制输出含 emotion 情感标签的结构化 JSON**，供 emotion_mapper 映射
  - 未配置 LLM_API_KEY 时自动进入 **mock 模式**（关键词猜测情绪），方便离线联调

Phase 2 增强（借鉴 SoulLink `docs/LLM_EXPRESSION_PRINCIPLE.md` 与
`src/generators/expression.py` 的 Prompt 工程 / 缓存 / 兜底设计）：
- **角色明确**：系统提示词把 LLM 定义为「表情控制器与对话助手」
- **动态注入**：可注入当前模型可用 expression / motion 清单与模型专属
  Prompt 片段（见 model_scanner.py）
- **强制 JSON**：要求只输出 JSON 对象，并做健壮解析（extract_json）
- **情绪强度**：新增 `intensity` 字段（0.0~1.0），提示词强调情绪要足够明显
- **temperature 默认 0.2**（0.1~0.3 区间内，保证输出一致性）
- **高频情绪缓存**：按用户消息与主导情绪缓存 LLM 结果，重复输入直接命中
- **本地兜底**：API 失败时按关键词回退 emotion_mapper 的 keyword_fallback

返回结构（LLMResult）：

    LLMResult(
        reply="很高兴见到你！",
        emotion="joy",
        emotion_weights={"joy": 0.8, "neutral": 0.2},
        raw=<LLM 原始输出>,
        intensity=0.8,
    )

环境变量：
  LLM_API_KEY      —— API 密钥；为空则启用 mock 模式
  LLM_BASE_URL     —— OpenAI 兼容服务地址（默认 https://api.openai.com/v1）
  LLM_MODEL        —— 模型名（默认 gpt-4o-mini）
  LLM_TEMPERATURE  —— 采样温度（默认 0.2）
  LLM_TIMEOUT      —— 请求超时秒数（默认 60）
  LLM_JSON_MODE    —— 设为 1 时向 API 传 response_format={"type":"json_object"}（需服务端支持）
  LLM_MAX_TOKENS   —— 最大输出 token 数（默认不限制）

用法示例：

    from llm_client import LLMClient, LLMResult

    client = LLMClient()
    client.set_model_context(expressions=["F01"], motions=["TapBody", "Idle"])
    result = await client.chat(user_text="今天心情如何？")
    print(result.reply, result.emotion, result.emotion_weights, result.intensity)
"""

from __future__ import annotations  # 使 `X | None` 等标注在 Python 3.9 也可用

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

# 供 mock / 兜底模式的情绪归一化复用
from emotion_mapper import keyword_fallback, normalize_emotion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except ValueError:
        return default


def _env_int(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class LLMConfig:
    """OpenAI 兼容接口配置。

    字段默认值从环境变量读取；也可通过 `from_dict()` 用 config.yaml 解析
    结果构造（config.yaml 优先于环境变量，见 config.py）。
    """

    api_key: str = field(default_factory=lambda: _env_str("LLM_API_KEY"))
    base_url: str = field(default_factory=lambda: _env_str(
        "LLM_BASE_URL", "https://api.openai.com/v1"))
    model: str = field(default_factory=lambda: _env_str("LLM_MODEL", "gpt-4o-mini"))
    temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))
    timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 60))
    json_mode: bool = field(default_factory=lambda: _env_str("LLM_JSON_MODE", "0") == "1")
    max_tokens: int | None = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", None))
    # 模型上下文（可由 model_scanner 注入，用于动态系统提示词）
    expressions: list = field(default_factory=list)
    motions: list = field(default_factory=list)
    model_prompt: str = ""

    @property
    def is_configured(self) -> bool:
        """是否配置了 API 密钥；未配置时 LLMClient 将使用 mock 模式。"""
        return bool(self.api_key)

    @classmethod
    def from_dict(cls, data: dict | None = None) -> "LLMConfig":
        """从 config.yaml 解析出的 dict 构建；缺省字段回退环境变量与默认值。"""
        d = dict(data or {})
        json_mode = d.get("json_mode")
        if json_mode is None:
            json_mode = _env_str("LLM_JSON_MODE", "0") == "1"
        return cls(
            api_key=d.get("api_key") or _env_str("LLM_API_KEY"),
            base_url=d.get("base_url") or _env_str("LLM_BASE_URL", "https://api.openai.com/v1"),
            model=d.get("model") or _env_str("LLM_MODEL", "gpt-4o-mini"),
            temperature=d.get("temperature") or _env_float("LLM_TEMPERATURE", 0.2),
            timeout=d.get("timeout") or _env_float("LLM_TIMEOUT", 60),
            json_mode=bool(json_mode),
            max_tokens=d.get("max_tokens") or _env_int("LLM_MAX_TOKENS", None),
        )


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class LLMResult:
    """一次 LLM 调用的结构化结果。"""

    reply: str                          # 面向用户的回复文本
    emotion: str                        # 主导情绪标签（已归一化）
    emotion_weights: dict = field(default_factory=dict)   # {标签: 权重}
    raw: str = ""                       # LLM 原始输出（供调试）
    intensity: float = 0.7              # 情绪强度 0.0~1.0（Phase 2 新增）


# 情绪标签取值（与 emotion_mapper.EMOTION_MAP 保持一致）
EMOTION_VOCAB = (
    "joy / angry / sorrow / surprised / neutral / excited / disgust / "
    "fear / shy / love / thinking / sleepy / worried / confused / annoyed"
)


def build_system_prompt(expressions: list | None = None,
                        motions: list | None = None,
                        model_prompt: str = "") -> str:
    """构造系统提示词（角色明确 + 动态清单 + 强制 JSON + 情绪强度）。

    借鉴 SoulLink `expression.py::_generate_system_prompt` 的动态注入思路，
    针对本项目的 4 指令协议重写：LLM 只输出情感标签，具体指令由
    emotion_mapper 映射（协议不变）。
    """
    lines = [
        "你是一个桌面 Live2D 虚拟形象的表情控制器与对话助手。",
        "你的回复要自然、简洁、有个性（一般 50 字以内），并准确表达情绪。",
        "请仅输出一个 JSON 对象，不要输出任何其他文字、注释或 Markdown 代码块标记。格式如下：",
        '{',
        '  "reply": "面向用户的回复文本",',
        '  "emotion": "joy",',
        '  "emotion_weights": {"joy": 0.8, "neutral": 0.2},',
        '  "intensity": 0.8',
        '}',
        "字段说明：",
        "- reply: 字符串，助手对用户的实际回复。",
        f"- emotion: 字符串，回复整体对应的主情感标签，取值范围: {EMOTION_VOCAB}。",
        "- emotion_weights: 对象，各情感标签的权重，键为上述标签，值 0.0~1.0，",
        "  可包含多个标签（多情感加权组合，反映情绪的混合成分）。",
        "- intensity: 数值 0.0~1.0，表示情绪强度。情绪越强烈该值越接近 1.0，",
        "  平淡时接近 0.3。情绪强度要足够明显，避免始终输出中性的 0.5。",
    ]
    # 动态注入当前模型可用资源（model_scanner 提供）
    if expressions:
        lines.append(f"当前模型可用的表情名称: {', '.join(str(e) for e in expressions)}")
    if motions:
        lines.append(f"当前模型可用的动作组: {', '.join(str(m) for m in motions)}")
    if expressions or motions:
        lines.append(
            "emotion 标签仍从上述取值列表中选择；可用清单仅用于让表情更贴合"
            "当前模型（emotion → expression/motion 指令由本地映射器完成）。"
        )
    # 模型专属规则（model_prompt.txt，可选）
    if model_prompt:
        lines.append(f"\n【模型专属规则】\n{model_prompt}")
    return "\n".join(lines)


# 兼容既有引用：模块级默认系统提示词由上述函数构造（无动态清单时）
SYSTEM_PROMPT = build_system_prompt()


# ---------------------------------------------------------------------------
# JSON 解析工具
# ---------------------------------------------------------------------------
def extract_json(text: str) -> dict:
    """从 LLM 输出中稳健地提取 JSON 对象。

    容忍 Markdown 代码块标记与首尾杂文本；仍失败则抛 ValueError。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 返回空文本")

    # 去掉 ```json ... ``` 代码块标记
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 兜底：截取第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出中解析 JSON: {text[:200]!r}...")


# ---------------------------------------------------------------------------
# mock 模式的情绪猜测（兼容入口，核心实现见 emotion_mapper.keyword_fallback）
# ---------------------------------------------------------------------------
_MOCK_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "joy":       ["开心", "高兴", "快乐", "太好了", "哈哈", "喜欢", "happy", "glad", "love", "yay"],
    "angry":     ["生气", "愤怒", "气死", "可恶", "讨厌", "angry", "mad", "annoyed"],
    "sorrow":    ["难过", "伤心", "悲伤", "哭泣", "失落", "sad", "cry", "sorry"],
    "surprised": ["惊讶", "吃惊", "震惊", "天哪", "哇", "surprise", "shock", "wow"],
    "excited":   ["兴奋", "激动", "太棒", "万岁", "excited", "awesome", "amazing"],
    "disgust":   ["恶心", "呕吐", "disgust", "gross"],
    "fear":      ["害怕", "恐惧", "救命", "fear", "scared", "help"],
    "shy":       ["害羞", "不好意思", "脸红", "shy", "embarrassed"],
    "love":      ["喜欢", "爱你", "心动", "love", "like"],
    "thinking":  ["思考", "考虑", "嗯", "thinking", "hmm"],
    "sleepy":    ["困", "累", "sleepy", "tired"],
    "worried":   ["担心", "紧张", "worried", "nervous"],
    "confused":  ["困惑", "疑惑", "confused", "puzzled"],
    "annoyed":   ["烦躁", "烦", "annoyed", "irritated"],
}


def guess_emotion_from_text(text: str) -> str:
    """按关键词粗略猜测文本情绪（仅用于 mock 模式兼容入口）。"""
    if not text:
        return "neutral"
    low = text.lower()
    scored: dict[str, int] = {}
    for emotion, keywords in _MOCK_EMOTION_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw.lower() in low)
        if hits:
            scored[emotion] = hits
    if not scored:
        return "neutral"
    return max(scored, key=scored.get)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
class LLMClient:
    """LLM 调用封装。

    - 配置了 LLM_API_KEY 时走真实 OpenAI 兼容接口；
    - 未配置时自动降级为 mock 模式，无需任何第三方依赖；
    - 真实接口失败时回退本地关键词兜底（高频情绪缓存优先）。
    """

    CACHE_MAX = 64

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()
        # 高频情绪 / 重复文本缓存
        self._text_cache: dict[str, LLMResult] = {}
        self._emotion_cache: dict[str, LLMResult] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def is_mock(self) -> bool:
        return not self.config.is_configured

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    # ------------------------------------------------------------------
    # 模型上下文注入（model_scanner 调用）
    # ------------------------------------------------------------------
    def set_model_context(self, expressions: list | None = None,
                          motions: list | None = None,
                          model_prompt: str | None = None) -> None:
        """注入当前模型可用表情 / 动作清单与模型专属 Prompt。

        后续 chat() 调用会自动把这些信息拼入系统提示词。
        """
        if expressions is not None:
            self.config.expressions = [str(e) for e in expressions]
        if motions is not None:
            self.config.motions = [str(m) for m in motions]
        if model_prompt is not None:
            self.config.model_prompt = str(model_prompt)

    def _build_system_prompt(self) -> str:
        """用当前配置构造系统提示词（含动态注入的模型上下文）。"""
        return build_system_prompt(
            expressions=self.config.expressions,
            motions=self.config.motions,
            model_prompt=self.config.model_prompt,
        )

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------
    def _cache_put(self, text: str, result: LLMResult) -> None:
        if not text:
            return
        self._text_cache[text] = result
        if result.emotion:
            self._emotion_cache[result.emotion] = result
        # 简单 LRU 式淘汰：超出上限时清空文本缓存（高频情绪缓存保留）
        if len(self._text_cache) > self.CACHE_MAX:
            self._text_cache = {}
            logger.debug("LLM 文本缓存已清空（超出 %d 条上限）", self.CACHE_MAX)

    def _text_cache_get(self, text: str) -> LLMResult | None:
        if not text:
            return None
        hit = self._text_cache.get(text)
        if hit is not None:
            self._cache_hits += 1
        return hit

    def _emotion_cache_get(self, emotion: str) -> LLMResult | None:
        return self._emotion_cache.get(emotion)

    # ------------------------------------------------------------------
    # 对外主入口
    # ------------------------------------------------------------------
    async def chat(self, user_text: str | None = None,
                   messages: list | None = None,
                   history: list | None = None,
                   **kwargs) -> LLMResult:
        """生成带情感标签的回复。

        :param user_text: 用户当前消息（优先使用）
        :param messages: 备选：OpenAI 风格 messages 列表，取最后一条 user 内容
        :param history: 可选的历史消息列表（元素为 {"role": ..., "content": ...}）
        """
        text = user_text if user_text is not None else self._last_user_text(messages)

        # 高频重复文本缓存：相同输入直接命中，避免重复调用
        cached = self._text_cache_get(text)
        if cached is not None:
            logger.debug("LLM 文本缓存命中: %r", (text or "")[:30])
            return cached

        if self.is_mock:
            return await self._chat_mock(text, history)

        try:
            return await self._chat_real(text, messages, history, **kwargs)
        except Exception as exc:  # noqa: BLE001 - API 失败必须回退，保证管线可用
            logger.warning("LLM API 调用失败，回退本地关键词兜底: %s", exc)
            return await self._chat_fallback(text, history, exc)

    # ------------------------------------------------------------------
    # 真实接口
    # ------------------------------------------------------------------
    async def _chat_real(self, user_text, messages, history, **kwargs) -> LLMResult:
        # 延迟导入 openai：仅真实调用时依赖，mock 模式下可不安装
        import openai

        client = openai.AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url or None,
            timeout=self.config.timeout,
        )

        msgs: list[dict] = [{"role": "system", "content": self._build_system_prompt()}]
        if history:
            msgs.extend(list(history))
        if user_text is not None:
            msgs.append({"role": "user", "content": user_text})
        else:
            msgs.append({"role": "user", "content": self._last_user_text(messages) or "你好"})

        create_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": msgs,
            "temperature": self.config.temperature,
        }
        if self.config.max_tokens:
            create_kwargs["max_tokens"] = self.config.max_tokens
        # 服务端支持 JSON mode 时，强制结构化输出（由 LLM_JSON_MODE=1 开启）
        if self.config.json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**create_kwargs)
        raw = (response.choices[0].message.content or "").strip()
        data = extract_json(raw)
        result = self._to_result(data, raw)
        self._cache_put(user_text, result)
        return result

    # ------------------------------------------------------------------
    # 本地兜底（API 失败时）
    # ------------------------------------------------------------------
    async def _chat_fallback(self, user_text: str | None, history,
                             exc: Exception) -> LLMResult:
        """API 失败时的回退链：重复文本缓存 → 关键词情绪 → 高频情绪缓存。

        借鉴 SoulLink「API 失败时使用本地预设兜底」的设计，针对本项目的
        4 指令协议重写：本地只输出情感标签，由 emotion_mapper 生成指令。
        """
        text = (user_text or "").strip() or "（空消息）"

        # 1) 精确文本缓存
        cached = self._text_cache_get(text)
        if cached is not None:
            return cached

        # 2) 关键词猜测情绪，命中高频情绪缓存则直接复用
        label, intensity = keyword_fallback(text)
        cached = self._emotion_cache_get(label)
        if cached is not None:
            return cached

        # 3) 构造本地兜底结果
        reply = f"[兜底] {text}（情绪判定：{label}）"
        result = LLMResult(
            reply=reply,
            emotion=label,
            emotion_weights={label: intensity, "neutral": round(1.0 - intensity, 2)},
            raw="",
            intensity=intensity,
        )
        self._cache_put(text, result)
        return result

    # ------------------------------------------------------------------
    # mock 接口
    # ------------------------------------------------------------------
    async def _chat_mock(self, user_text: str | None, history) -> LLMResult:
        text = (user_text or "").strip() or "（空消息）"
        label, intensity = keyword_fallback(text)
        reply = f"[mock] 收到消息：{text}（情绪判定：{label}）"
        result = LLMResult(
            reply=reply,
            emotion=label,
            emotion_weights={label: intensity, "neutral": round(1.0 - intensity, 2)},
            raw="",
            intensity=intensity,
        )
        self._cache_put(text, result)
        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _to_result(self, data: dict, raw: str) -> LLMResult:
        reply = str(data.get("reply", "")).strip()
        if not reply:
            reply = str(data)  # 兜底：reply 缺失时展示原始 JSON

        emotion = normalize_emotion(data.get("emotion"))
        weights = data.get("emotion_weights") or {}
        if isinstance(weights, dict):
            cleaned: dict[str, float] = {}
            for key, value in weights.items():
                if value is None:
                    continue
                try:
                    cleaned[normalize_emotion(key)] = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    continue
            weights = cleaned
        weights.setdefault(emotion, 1.0)

        # 情绪强度（0.0~1.0，钳制）
        try:
            intensity = max(0.0, min(1.0, float(data.get("intensity", 0.7))))
        except (TypeError, ValueError):
            intensity = 0.7

        return LLMResult(reply=reply, emotion=emotion, emotion_weights=weights,
                         raw=raw, intensity=intensity)

    @staticmethod
    def _last_user_text(messages) -> str:
        """从 OpenAI 风格 messages 中取出最后一条 user 文本。"""
        if not messages:
            return ""
        last = messages[-1]
        if isinstance(last, dict):
            content = last.get("content", "")
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if isinstance(p, dict)]
                return " ".join(parts)
            return str(content)
        return str(last)


# ---------------------------------------------------------------------------
# 模块级便捷入口
# ---------------------------------------------------------------------------
_default_client: LLMClient | None = None


def get_client(config: LLMConfig | None = None) -> LLMClient:
    """获取（缓存的）LLMClient 实例。"""
    global _default_client
    if config is None:
        if _default_client is None:
            _default_client = LLMClient()
        return _default_client
    return LLMClient(config)


async def chat(user_text: str, history: list | None = None,
               config: LLMConfig | None = None) -> LLMResult:
    """便捷异步函数：一步完成一次带情感标签的对话。"""
    return await get_client(config).chat(user_text=user_text, history=history)


if __name__ == "__main__":
    # 自测：python llm_client.py
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async def _main():
        client = LLMClient()
        result = await client.chat(user_text="今天天气真好，好开心呀！")
        logging.info("mock 结果: reply=%r emotion=%r weights=%r intensity=%r",
                     result.reply, result.emotion, result.emotion_weights,
                     result.intensity)
        # 验证 JSON 提取
        for sample in (
            '{"reply": "hi", "emotion": "joy"}',
            '```json\n{"reply": "hi", "emotion": "sorrow", "intensity": 0.9}\n```',
            '好的，结果如下：\n{"reply": "ok", "emotion": "neutral"}',
        ):
            logging.info("extract_json(%r) -> %s", sample, extract_json(sample))
        # 验证动态系统提示词注入
        client.set_model_context(expressions=["F01", "F02"],
                                 motions=["Idle", "TapBody"],
                                 model_prompt="此模型头部转动范围较小。")
        prompt = client._build_system_prompt()
        assert "F01" in prompt and "TapBody" in prompt and "头部转动范围" in prompt
        logging.info("系统提示词动态注入 OK")

    asyncio.run(_main())
