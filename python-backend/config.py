#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py — 可选 config.yaml 配置加载（Phase 2 新增）
================================================================

借鉴 SoulLink_Live2D 的 `src/config/manager.py`「字段级继承」设计：
LLM 的 `chat` 子段可缺省，自动继承 `llm.api` 段的默认值（temperature、
model、baseUrl 等）。

解析优先级（逐字段）：
    config.yaml  >  环境变量  >  默认值

提供的数据结构（Config）：
    Config.server.host / port / path
    Config.llm.api            —— LLM 基础段（OpenAI 兼容）
    Config.llm.chat           —— 对话专用段（字段级继承 api）
    Config.tts.*              —— TTS（mock / edge-tts / openai）
    Config.model_dir          —— Live2D 模型目录（供 model_scanner）

> config.yaml 是可选的：未提供（或未安装 PyYAML）时返回全默认配置，
> 各模块内部仍各自读取环境变量兜底，保持与既有行为一致。

用法：

    from config import load_config
    cfg = load_config()                      # 自动发现 ./config.yaml
    cfg = load_config("my_conf.yaml")        # 显式指定
"""

from __future__ import annotations  # 使 `X | None` 等标注在 Python 3.9 也可用

import logging
import os
from dataclasses import dataclass, field
from typing import Any

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover - 仅在未安装时走兜底
    yaml = None

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_MODEL_DIR = "../assets/models"
DEFAULT_TTS_VOICE = "zh-CN-XiaoxiaoNeural"


# ---------------------------------------------------------------------------
# 环境变量小工具
# ---------------------------------------------------------------------------
def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _get(data: dict, keys: list[str], default: Any = None) -> Any:
    """沿 keys 路径逐级取嵌套 dict 的值；任一层缺失/非 dict 返回 default。"""
    cur: Any = data
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _str_or_env(section: dict, key: str, env_name: str, default: str) -> str:
    """字段优先取 section[key]，否则回退环境变量，再回退默认值。"""
    if section is not None and section.get(key) not in (None, ""):
        return str(section[key])
    return _env(env_name, default)


def _float_or_env(section: dict, key: str, env_name: str, default: float) -> float:
    if section is not None and key in section and section[key] is not None:
        try:
            return float(section[key])
        except (TypeError, ValueError):
            pass
    return _env_float(env_name, default)


def _int_or_env(section: dict, key: str, env_name: str, default: int) -> int:
    if section is not None and key in section and section[key] is not None:
        try:
            return int(section[key])
        except (TypeError, ValueError):
            pass
    return _env_int(env_name, default)


# ---------------------------------------------------------------------------
# 配置数据结构
# ---------------------------------------------------------------------------
@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 3000
    path: str = "/ws"


@dataclass
class LLMEndpointConfig:
    """单个 OpenAI 兼容端点配置。"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    timeout: float = 60.0
    json_mode: bool = False
    max_tokens: int | None = None

    @property
    def configured(self) -> bool:
        """是否配置了 API 密钥。"""
        return bool(self.api_key)

    def to_dict(self) -> dict:
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "json_mode": self.json_mode,
            "max_tokens": self.max_tokens,
        }


@dataclass
class LLMConfig:
    api: LLMEndpointConfig = field(default_factory=LLMEndpointConfig)
    chat: LLMEndpointConfig = field(default_factory=LLMEndpointConfig)


@dataclass
class TTSConfig:
    engine: str = "mock"                    # mock | edge-tts | openai
    voice: str = DEFAULT_TTS_VOICE
    rate: str = "+0%"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "tts-1"
    speed: float = 1.0
    sample_rate: int = 24000


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    model_dir: str = DEFAULT_MODEL_DIR
    config_path: str = ""


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------
def discover_config_path(explicit: str | None = None) -> str:
    """定位 config.yaml：显式路径优先，其次工作目录下的默认文件名。"""
    if explicit:
        return explicit
    if os.path.exists(DEFAULT_CONFIG_PATH):
        return DEFAULT_CONFIG_PATH
    return ""


def load_config(path: str | None = None) -> Config:
    """加载配置。config.yaml 不存在 / 解析失败 / 未装 PyYAML 时返回默认配置。

    注意：解析失败只记日志不抛错，保证服务端总能启动。
    """
    cfg = Config()
    cfg.config_path = discover_config_path(path)
    if not cfg.config_path:
        return cfg

    try:
        if yaml is None:
            raise RuntimeError("未安装 PyYAML，无法解析 config.yaml（pip install PyYAML）")
        with open(cfg.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        data = raw if isinstance(raw, dict) else {}
    except Exception as exc:  # noqa: BLE001 - 配置失败不应阻断启动
        print(f"[config] ⚠️ 加载 config.yaml 失败: {exc}，使用默认配置")
        return cfg

    # ---- server 段 ----
    srv = _get(data, ["server"], {}) or {}
    cfg.server.host = _str_or_env(srv, "host", "SERVER_HOST", "0.0.0.0")
    cfg.server.port = _int_or_env(srv, "port", "SERVER_PORT", 3000)
    cfg.server.path = _str_or_env(srv, "path", "SERVER_PATH", "/ws")

    # ---- llm.api 基础段 ----
    api = _get(data, ["llm", "api"], {}) or {}
    api_cfg = LLMEndpointConfig(
        api_key=_str_or_env(api, "apiKey", "LLM_API_KEY", ""),
        base_url=_str_or_env(api, "baseUrl", "LLM_BASE_URL", "https://api.openai.com/v1"),
        model=_str_or_env(api, "model", "LLM_MODEL", "gpt-4o-mini"),
        temperature=_float_or_env(api, "temperature", "LLM_TEMPERATURE", 0.2),
        timeout=_float_or_env(api, "timeout", "LLM_TIMEOUT", 60.0),
        json_mode=bool(api.get("jsonMode")) if "jsonMode" in api
        else _env("LLM_JSON_MODE", "0") == "1",
        max_tokens=_int_or_env(api, "maxTokens", "LLM_MAX_TOKENS", 0) or None,
    )
    cfg.llm.api = api_cfg

    # ---- llm.chat 段（字段级继承：缺省字段继承 llm.api / 环境变量）----
    chat = _get(data, ["llm", "chat"], {}) or {}
    cfg.llm.chat = LLMEndpointConfig(
        api_key=_str_or_env(chat, "apiKey", "LLM_API_KEY", api_cfg.api_key),
        base_url=_str_or_env(chat, "baseUrl", "LLM_BASE_URL", api_cfg.base_url),
        model=_str_or_env(chat, "model", "LLM_MODEL", api_cfg.model),
        temperature=_float_or_env(chat, "temperature", "LLM_TEMPERATURE", api_cfg.temperature),
        timeout=_float_or_env(chat, "timeout", "LLM_TIMEOUT", api_cfg.timeout),
        json_mode=bool(chat.get("jsonMode")) if "jsonMode" in chat else api_cfg.json_mode,
        max_tokens=_int_or_env(chat, "maxTokens", "LLM_MAX_TOKENS", 0) or None,
    )

    # ---- tts 段 ----
    tts = _get(data, ["tts"], {}) or {}
    cfg.tts = TTSConfig(
        engine=_str_or_env(tts, "engine", "TTS_ENGINE", "mock").lower(),
        voice=_str_or_env(tts, "voice", "TTS_VOICE", DEFAULT_TTS_VOICE),
        rate=_str_or_env(tts, "rate", "TTS_RATE", "+0%"),
        base_url=_str_or_env(tts, "baseUrl", "TTS_BASE_URL", "https://api.openai.com/v1"),
        api_key=_str_or_env(tts, "apiKey", "TTS_API_KEY", ""),
        model=_str_or_env(tts, "model", "TTS_MODEL", "tts-1"),
        speed=_float_or_env(tts, "speed", "TTS_SPEED", 1.0),
        sample_rate=_int_or_env(tts, "sampleRate", "TTS_SAMPLE_RATE", 24000),
    )

    # ---- model 目录 ----
    mdl = _get(data, ["model"], {}) or {}
    cfg.model_dir = _str_or_env(mdl, "directory", "MODEL_DIR", DEFAULT_MODEL_DIR)

    if logger is not None:
        logger.info("配置已加载: %s", cfg.config_path)
    return cfg


if __name__ == "__main__":
    import logging

    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    c = load_config()
    print(f"server: {c.server.host}:{c.server.port}{c.server.path}")
    print(f"llm.api : model={c.llm.api.model} temp={c.llm.api.temperature}")
    print(f"llm.chat: model={c.llm.chat.model} temp={c.llm.chat.temperature}")
    print(f"tts: engine={c.tts.engine} voice={c.tts.voice} model={c.tts.model}")
    print(f"model_dir: {c.model_dir}")
    print(f"config_path: {c.config_path or '(未找到，使用默认/环境变量)'}")
