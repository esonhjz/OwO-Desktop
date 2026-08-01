#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emotion_mapper.py — LLM 情绪标签 → Live2D 指令映射（Phase 2 增强）
================================================================

参考 SoulLink 的「情感标签化 + 权重组合」思路：

1. **情感标签化**：LLM 在生成回复时强制附带情绪标签（joy / angry / sorrow /
   surprised / neutral 等），本模块把这些标签翻译为 OwO-Desktop 能识别的
   `expression` 与 `motion` 指令。
2. **权重与组合**：情绪不是非黑即白。LLM 可返回多标签权重（如
   `{"joy": 0.7, "neutral": 0.3}`），本模块会把每个标签的候选动作按权重
   累加得分，得分最高的候选动作胜出——即「表情取主导情绪、动作按权重组合」。

Phase 2 增强（借鉴 SoulLink `src/generators/local_expression.py`）：
- 扩充情绪种类与中文关键词库（新增 love / thinking / sleepy / worried /
  confused / annoyed，并扩展既有情绪的别名）
- `keyword_fallback(text)`：文本关键词 → (情绪标签, 强度)，作为 LLM API
  失败时的本地兜底，也供 mock 模式使用
- **intensity 维度**：映射时根据情绪强度联动 motion priority
  （强度 ≥0.75 提升 1 档，≤0.4 降低 1 档）

协议约定（与 ../src/NetworkManager.cpp 严格一致）：

    {"type": "expression", "name": "F01"}
    {"type": "motion",     "group": "TapBody", "no": 0, "priority": 3}

> 默认的 `expression` 名称（F01~F05）与 `motion` 组名（TapBody / Idle）依赖
> 具体模型资源（.exp3.json / .model3.json），可在 EMOTION_MAP 中按需调整。

用法示例：

    from emotion_mapper import map_emotion, keyword_fallback

    commands = map_emotion("joy")                 # 字符串标签
    commands = map_emotion({"joy": 0.7, "neutral": 0.3})   # 多标签权重
    commands = map_emotion(llm_result)            # LLMClient 的返回结果
    label, intensity = keyword_fallback("今天好开心呀")   # 本地兜底
"""

from __future__ import annotations  # 使 `X | None` 等标注在 Python 3.9 也可用

import json
from typing import Any

# ---------------------------------------------------------------------------
# 情绪标签 → 表情 / 动作 映射表
# ---------------------------------------------------------------------------
# 每个条目：
#   expression   —— 主表情名（对应模型 .exp3.json 中的条目）
#   motion       —— 默认动作（对应 .model3.json 中的动作组）
#   candidates   —— 候选动作及权重，用于 SoulLink 式权重组合
#   aliases      —— 同义词 / 中文别名，用于归一化
EMOTION_MAP: dict[str, dict[str, Any]] = {
    "joy": {
        "expression": "F01",
        "motion": {"group": "TapBody", "no": 0, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 0, "priority": 3}, "weight": 1.0},
            {"motion": {"group": "TapBody", "no": 2, "priority": 3}, "weight": 0.4},
        ],
        "aliases": ["happy", "delighted", "cheerful", "glad", "laugh", "smile",
                    "开心", "高兴", "快乐", "愉快", "哈哈", "笑", "开心呀"],
    },
    "angry": {
        "expression": "F02",
        "motion": {"group": "TapBody", "no": 1, "priority": 4},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 1, "priority": 4}, "weight": 1.0},
        ],
        "aliases": ["mad", "rage", "furious", "annoyed", "irritated",
                    "生气", "愤怒", "恼怒", "暴躁", "气死", "火大", "可恶"],
    },
    "sorrow": {
        "expression": "F03",
        "motion": {"group": "TapBody", "no": 3, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 3, "priority": 3}, "weight": 1.0},
        ],
        "aliases": ["sad", "cry", "grief", "depressed", "miserable",
                    "难过", "悲伤", "伤心", "哭泣", "失落", "哭", "委屈"],
    },
    "surprised": {
        "expression": "F04",
        "motion": {"group": "TapBody", "no": 2, "priority": 4},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 2, "priority": 4}, "weight": 1.0},
        ],
        "aliases": ["shock", "amazed", "astonished", "wow", "what",
                    "惊讶", "吃惊", "震惊", "意外", "天哪", "哇"],
    },
    "neutral": {
        "expression": "F00",
        "motion": {"group": "Idle", "no": 0, "priority": 2},
        "candidates": [
            {"motion": {"group": "Idle", "no": 0, "priority": 2}, "weight": 1.0},
        ],
        "aliases": ["calm", "normal", "default", "serene", "ok",
                    "平静", "平淡", "默认", "正常"],
    },
    "excited": {
        "expression": "F01",
        "motion": {"group": "TapBody", "no": 2, "priority": 4},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 2, "priority": 4}, "weight": 1.0},
            {"motion": {"group": "TapBody", "no": 0, "priority": 3}, "weight": 0.6},
        ],
        "aliases": ["thrilled", "ecstatic", "pumped", "awesome", "amazing",
                    "兴奋", "激动", "雀跃", "太棒", "万岁"],
    },
    "disgust": {
        "expression": "F02",
        "motion": {"group": "TapBody", "no": 1, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 1, "priority": 3}, "weight": 1.0},
        ],
        "aliases": ["gross", "sick", "repelled", "yuck",
                    "恶心", "厌恶", "嫌弃", "呕吐"],
    },
    "fear": {
        "expression": "F04",
        "motion": {"group": "TapBody", "no": 1, "priority": 4},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 1, "priority": 4}, "weight": 1.0},
        ],
        "aliases": ["scared", "terrified", "panic", "afraid",
                    "害怕", "恐惧", "惊慌", "救命"],
    },
    "shy": {
        "expression": "F00",
        "motion": {"group": "TapBody", "no": 3, "priority": 2},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 3, "priority": 2}, "weight": 1.0},
        ],
        "aliases": ["bashful", "embarrassed", "timid",
                    "害羞", "不好意思", "脸红", "腼腆", "羞"],
    },
    # ---- Phase 2 新增情绪（借鉴 SoulLink local_expression 关键词库）----
    "love": {
        "expression": "F01",
        "motion": {"group": "TapBody", "no": 0, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 0, "priority": 3}, "weight": 1.0},
        ],
        "aliases": ["like", "heart", "crush", "adore",
                    "喜欢", "爱", "心动", "恋爱", "爱你"],
    },
    "thinking": {
        "expression": "F00",
        "motion": {"group": "Idle", "no": 0, "priority": 2},
        "candidates": [
            {"motion": {"group": "Idle", "no": 0, "priority": 2}, "weight": 1.0},
        ],
        "aliases": ["ponder", "consider", "hmm", "um",
                    "思考", "考虑", "琢磨", "嗯", "想"],
    },
    "sleepy": {
        "expression": "F00",
        "motion": {"group": "Idle", "no": 0, "priority": 2},
        "candidates": [
            {"motion": {"group": "Idle", "no": 0, "priority": 2}, "weight": 1.0},
        ],
        "aliases": ["tired", "exhausted", "drowsy", "yawning",
                    "困", "累", "困了", "打哈欠"],
    },
    "worried": {
        "expression": "F03",
        "motion": {"group": "TapBody", "no": 3, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 3, "priority": 3}, "weight": 1.0},
        ],
        "aliases": ["nervous", "anxious", "uneasy", "concerned",
                    "担心", "紧张", "焦虑", "不安", "担忧"],
    },
    "confused": {
        "expression": "F04",
        "motion": {"group": "TapBody", "no": 2, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 2, "priority": 3}, "weight": 1.0},
        ],
        "aliases": ["puzzled", "perplexed", "baffled",
                    "困惑", "疑惑", "不懂", "迷茫", "糊涂"],
    },
    "annoyed": {
        "expression": "F02",
        "motion": {"group": "TapBody", "no": 1, "priority": 3},
        "candidates": [
            {"motion": {"group": "TapBody", "no": 1, "priority": 3}, "weight": 1.0},
        ],
        "aliases": ["irritated", "frustrated", "vexed",
                    "烦躁", "烦", "不耐烦", "不爽"],
    },
}

DEFAULT_EMOTION = "neutral"

# 动作触发阈值：情绪强度低于该值时只发表情、不触发动作
MOTION_MIN_INTENSITY = 0.4

# 由 EMOTION_MAP 构建别名索引：别名/规范名 → 规范名
ALIAS_INDEX: dict[str, str] = {}
for _label, _entry in EMOTION_MAP.items():
    ALIAS_INDEX[_label] = _label
    for _alias in _entry.get("aliases", []):
        ALIAS_INDEX[str(_alias).strip().lower()] = _label


# ---------------------------------------------------------------------------
# 文本关键词 → (情绪, 强度) 本地兜底
# ---------------------------------------------------------------------------
# 借鉴 SoulLink `src/generators/local_expression.py::_extract_emotion`：
# 按关键词表顺序取首个命中，命中即返回 (情绪标签, 强度)。
_KEYWORD_FALLBACK: list[tuple[str, str, float]] = [
    # (关键词, 情绪标签, 强度)
    ("开心", "joy", 0.8), ("高兴", "joy", 0.7), ("快乐", "joy", 0.8),
    ("哈哈", "joy", 0.9), ("笑", "joy", 0.7), ("喜欢", "love", 0.8),
    ("爱你", "love", 0.9), ("太棒", "excited", 0.9), ("万岁", "excited", 0.9),
    ("兴奋", "excited", 0.8), ("激动", "excited", 0.8),
    ("生气", "angry", 0.8), ("愤怒", "angry", 0.9), ("气死", "angry", 0.9),
    ("可恶", "angry", 0.8), ("烦躁", "annoyed", 0.6), ("烦", "annoyed", 0.5),
    ("恶心", "disgust", 0.8), ("呕吐", "disgust", 0.9),
    ("难过", "sorrow", 0.7), ("伤心", "sorrow", 0.8), ("悲伤", "sorrow", 0.7),
    ("哭", "sorrow", 0.9), ("委屈", "sorrow", 0.7),
    ("惊讶", "surprised", 0.8), ("吃惊", "surprised", 0.7), ("天哪", "surprised", 0.9),
    ("害怕", "fear", 0.8), ("恐惧", "fear", 0.9), ("救命", "fear", 0.9),
    ("害羞", "shy", 0.7), ("不好意思", "shy", 0.5), ("脸红", "shy", 0.8),
    ("思考", "thinking", 0.6), ("嗯", "thinking", 0.5), ("考虑", "thinking", 0.6),
    ("困", "sleepy", 0.7), ("累", "sleepy", 0.6), ("打哈欠", "sleepy", 0.8),
    ("担心", "worried", 0.6), ("紧张", "worried", 0.7), ("焦虑", "worried", 0.8),
    ("困惑", "confused", 0.6), ("疑惑", "confused", 0.5), ("不懂", "confused", 0.6),
]

# 兜底命中时若情绪不在上表（如纯英文关键词），再按别名表做二次猜测
_KEYWORD_FALLBACK_EN: list[tuple[str, str, float]] = [
    ("happy", "joy", 0.8), ("glad", "joy", 0.7), ("love", "love", 0.8),
    ("excited", "excited", 0.8), ("angry", "angry", 0.8), ("mad", "angry", 0.8),
    ("sad", "sorrow", 0.8), ("cry", "sorrow", 0.9),
    ("surprised", "surprised", 0.8), ("shock", "surprised", 0.8),
    ("scared", "fear", 0.8), ("afraid", "fear", 0.8), ("help", "fear", 0.8),
    ("shy", "shy", 0.7), ("thinking", "thinking", 0.6), ("hmm", "thinking", 0.5),
    ("sleepy", "sleepy", 0.7), ("tired", "sleepy", 0.6),
    ("worried", "worried", 0.6), ("nervous", "worried", 0.7),
    ("confused", "confused", 0.6), ("puzzled", "confused", 0.6),
    ("annoyed", "annoyed", 0.6), ("gross", "disgust", 0.8),
]


def keyword_fallback(text: Any) -> tuple[str, float]:
    """文本关键词 → (情绪标签, 强度)。本地兜底 / mock 模式使用。

    借鉴 SoulLink `local_expression.py::_extract_emotion`：按顺序取首个
    命中关键词，返回其预设情绪与强度；无命中回退到 (neutral, 0.5)。
    """
    if not text:
        return DEFAULT_EMOTION, 0.5
    low = str(text).strip().lower()
    if not low:
        return DEFAULT_EMOTION, 0.5
    for keyword, label, intensity in _KEYWORD_FALLBACK:
        if keyword in low:
            return normalize_emotion(label), intensity
    for keyword, label, intensity in _KEYWORD_FALLBACK_EN:
        if keyword in low:
            return normalize_emotion(label), intensity
    return DEFAULT_EMOTION, 0.5


# ---------------------------------------------------------------------------
# 情绪归一化
# ---------------------------------------------------------------------------
def normalize_emotion(label: Any) -> str:
    """把任意情绪标签 / 别名归一化为规范标签；未知标签回退到 neutral。"""
    if label is None:
        return DEFAULT_EMOTION
    key = str(label).strip().lower()
    if not key:
        return DEFAULT_EMOTION
    return ALIAS_INDEX.get(key, DEFAULT_EMOTION)


def _sort_weighted(pairs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """按权重降序排序；权重相同则按标签名稳定排序。"""
    if not pairs:
        return [(DEFAULT_EMOTION, 1.0)]
    return sorted(pairs, key=lambda x: (-x[1], x[0]))


def normalize_emotion_input(emotion_input: Any) -> list[tuple[str, float]]:
    """把各种形态的情绪输入归一化为 [(标签, 权重), ...]（权重降序）。

    支持输入形态：
      - 字符串:                    "joy"
      - 权重 dict:                 {"joy": 0.7, "neutral": 0.3}
      - LLM 输出 dict:             {"emotion": "joy", "emotion_weights": {...}}
      - LLMResult 对象:            含 .emotion / .emotion_weights 属性
      - 列表:                      [("joy", 0.7), ("neutral", 0.3)]
    """
    if emotion_input is None:
        return [(DEFAULT_EMOTION, 1.0)]

    # 对象形态（如 LLMClient.LLMResult）
    if hasattr(emotion_input, "emotion"):
        weights = getattr(emotion_input, "emotion_weights", None) or {}
        if isinstance(weights, dict) and weights:
            return normalize_emotion_input(weights)
        return [(normalize_emotion(getattr(emotion_input, "emotion")), 1.0)]

    # 字符串形态
    if isinstance(emotion_input, str):
        return [(normalize_emotion(emotion_input), 1.0)]

    # 字典形态
    if isinstance(emotion_input, dict):
        # LLM 输出结构：{"emotion": "joy", "emotion_weights": {...}}
        if "emotion" in emotion_input and isinstance(emotion_input.get("emotion"), str):
            weights = emotion_input.get("emotion_weights") or {}
            if isinstance(weights, dict) and weights:
                return normalize_emotion_input(weights)
            return [(normalize_emotion(emotion_input["emotion"]), 1.0)]
        # 权重结构：{"joy": 0.7, "neutral": 0.3}
        pairs = []
        for key, value in emotion_input.items():
            label = normalize_emotion(key)
            try:
                weight = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                weight = 1.0
            pairs.append((label, weight))
        return _sort_weighted(pairs)

    # 列表 / 元组形态
    if isinstance(emotion_input, (list, tuple)):
        pairs = []
        for item in emotion_input:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((normalize_emotion(item[0]), float(item[1])))
            elif isinstance(item, dict) and "label" in item:
                pairs.append((normalize_emotion(item["label"]),
                              float(item.get("weight", 1.0))))
            elif isinstance(item, str):
                pairs.append((normalize_emotion(item), 1.0))
        return _sort_weighted(pairs)

    return [(DEFAULT_EMOTION, 1.0)]


# ---------------------------------------------------------------------------
# 映射函数
# ---------------------------------------------------------------------------
def expression_for(emotion: Any) -> dict:
    """根据情绪标签生成 expression 指令。"""
    label = normalize_emotion(emotion)
    entry = EMOTION_MAP.get(label, EMOTION_MAP[DEFAULT_EMOTION])
    return {"type": "expression", "name": entry["expression"]}


def motion_for(emotion: Any) -> dict | None:
    """根据情绪标签生成默认 motion 指令。"""
    label = normalize_emotion(emotion)
    entry = EMOTION_MAP.get(label, EMOTION_MAP[DEFAULT_EMOTION])
    return {"type": "motion", **dict(entry["motion"])}


def combine_motion(emotion_weights: list[tuple[str, float]]) -> dict | None:
    """SoulLink 式权重组合：把所有情绪标签的候选动作按权重累加得分，
    得分最高的候选动作胜出。

    :param emotion_weights: [(标签, 权重), ...]（normalize_emotion_input 的输出）
    :return: motion 指令；没有任何候选动作时返回 None
    """
    scores: dict[str, float] = {}
    for label, weight in emotion_weights:
        entry = EMOTION_MAP.get(label)
        if not entry:
            continue
        for candidate in entry.get("candidates", []):
            motion = candidate.get("motion")
            if not motion:
                continue
            key = json.dumps(motion, sort_keys=True)
            scores[key] = scores.get(key, 0.0) + float(candidate.get("weight", 1.0)) * weight
    if not scores:
        return None
    best_key = max(scores, key=scores.get)
    return {"type": "motion", **json.loads(best_key)}


def priority_for_intensity(base_priority: int, intensity: float) -> int:
    """情绪强度联动动作优先级（Phase 2 增强）。

    - intensity ≥ 0.75：提升 1 档（情绪强烈，动作更抢镜）
    - intensity ≤ 0.40：降低 1 档（情绪平淡，动作退居背景）
    - 其余保持不变
    """
    base = int(base_priority)
    try:
        intensity = max(0.0, min(1.0, float(intensity)))
    except (TypeError, ValueError):
        intensity = 0.7
    if intensity >= 0.75:
        return max(0, min(5, base + 1))
    if intensity <= 0.40:
        return max(0, base - 1)
    return base


def map_emotion(emotion_input: Any, intensity: float | None = None,
                include_motion: bool = True,
                min_motion_intensity: float = MOTION_MIN_INTENSITY) -> list[dict]:
    """把情绪输入映射为一组 Live2D 指令（最多 [expression, motion]）。

    :param emotion_input: 字符串 / 权重 dict / LLM 输出 dict / LLMResult
    :param intensity: 情绪强度 0.0~1.0；缺省时尝试从 emotion_input 读取
        （如 LLMResult.intensity），仍无则取 1.0。
        低于 min_motion_intensity 时只发表情；映射时联动 motion priority。
    :param include_motion: 是否生成 motion 指令
    :param min_motion_intensity: 触发动作的最低强度阈值
    :return: 指令字典列表，可直接交给 server.send_command() 广播
    """
    weighted = normalize_emotion_input(emotion_input)
    if not weighted:
        weighted = [(DEFAULT_EMOTION, 1.0)]

    if intensity is None:
        intensity = getattr(emotion_input, "intensity", None)
    if intensity is None:
        intensity = 1.0
    try:
        intensity = max(0.0, min(1.0, float(intensity)))
    except (TypeError, ValueError):
        intensity = 1.0

    dominant_label = weighted[0][0]
    commands: list[dict] = [expression_for(dominant_label)]

    if include_motion and intensity >= min_motion_intensity:
        motion = combine_motion(weighted)
        if motion is None:
            motion = motion_for(dominant_label)
        if motion:
            if "priority" in motion:
                motion["priority"] = priority_for_intensity(motion["priority"], intensity)
            commands.append(motion)
    return commands


# ---------------------------------------------------------------------------
# 便捷入口：供 server.py 的 chat 管线直接使用
# ---------------------------------------------------------------------------
def emotion_label_from(emotion_input: Any) -> str:
    """取主导情绪标签（权重最高者），用于日志 / 调试。"""
    weighted = normalize_emotion_input(emotion_input)
    return weighted[0][0] if weighted else DEFAULT_EMOTION


if __name__ == "__main__":
    # 自测：python emotion_mapper.py
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("joy      -> %s", map_emotion("joy"))
    logging.info("weighted -> %s", map_emotion({"joy": 0.7, "neutral": 0.3}))
    logging.info("sorrow   -> %s", map_emotion("sorrow", intensity=0.2))
    logging.info("thinking -> %s", map_emotion("thinking"))
    logging.info("love low -> %s", map_emotion("love", intensity=0.3))
    logging.info("unknown  -> %s", map_emotion("whatever"))
    logging.info("fallback(今天好开心呀) -> %s", keyword_fallback("今天好开心呀"))
    logging.info("fallback(我有点担心)   -> %s", keyword_fallback("我有点担心"))
