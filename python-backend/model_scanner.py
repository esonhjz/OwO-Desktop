#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
model_scanner.py — Live2D 模型目录扫描与索引（Phase 2 新增）
================================================================

借鉴 SoulLink_Live2D 的 `src/models/scanner.py`：
- 递归扫描模型目录，定位所有 `*.model3.json`
- 解析 model3.json 的 `FileReferences.Expressions` / `Motions`，
  提取可用表情名称与动作组（组名 → 动作条数）
- 读取可选的 `model_prompt.txt`（参考 SoulLink `model_prompt_example.txt`），
  作为模型专属规则注入 LLM
- 维护「switch_model 兼容索引」：与 OwO-Desktop C++ 端
  `LAppLive2DManager::LoadModels` 的加载顺序保持一致——
  仅统计 `<目录>/<目录名>.model3.json`，并按目录名做大小写敏感字典序排序
  （C++ 端用 `qsort` + `strcmp`），保证后端发送的 `switch_model index`
  与 C++ 端场景索引一一对应。

用法：

    from model_scanner import ModelScanner
    scanner = ModelScanner("../assets/models")
    scanner.scan()
    for model in scanner.switch_models:
        print(model.name, model.expressions, model.motion_groups)
"""

from __future__ import annotations  # 使 `X | None` 等标注在 Python 3.9 也可用

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认模型目录：相对本目录（OwO-Desktop/python-backend）的位置
DEFAULT_MODEL_DIR = "../assets/models"

# 模型专属 Prompt 文件名（参考 SoulLink model_prompt_example.txt 的约定）
MODEL_PROMPT_FILE = "model_prompt.txt"


@dataclass
class ModelInfo:
    """单个 Live2D 模型的信息。"""

    name: str                              # 模型基名（model3.json 去掉 .model3.json 后缀，通常=所在目录名）
    directory: str                         # 相对模型根目录的目录路径（POSIX 分隔）
    model_file: str                        # model3.json 文件名
    expressions: list = field(default_factory=list)      # 可用表情名
    motion_groups: dict = field(default_factory=dict)    # 动作组名 -> 动作条数
    motion_files: list = field(default_factory=list)     # 动作文件相对路径
    custom_prompt: str = ""                # model_prompt.txt 内容（模型专属规则）
    path: str = ""                         # model3.json 完整路径


class ModelScanner:
    """模型目录扫描器。

    - `models`：目录下发现的全部模型（含嵌套子目录里的 model3.json）
    - `switch_models`：与 C++ 端加载顺序一致的索引，用于 `switch_model index`
    """

    def __init__(self, base_dir: str | None = None):
        raw = (base_dir or os.environ.get("MODEL_DIR", "").strip()
               or DEFAULT_MODEL_DIR)
        self.base_dir = Path(raw).resolve()
        self.models: list[ModelInfo] = []          # 全部发现
        self.switch_models: list[ModelInfo] = []   # C++ 兼容索引
        self._scanned = False

    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """模型目录是否存在。"""
        return self.base_dir.exists()

    def scan(self, force: bool = False) -> list[ModelInfo]:
        """扫描模型目录并建立索引；返回全部模型列表。"""
        if self._scanned and not force:
            return self.models

        self.models = []
        self.switch_models = []
        if not self.available:
            logger.warning("模型目录不存在，跳过扫描: %s", self.base_dir)
            return self.models

        for m3 in sorted(self.base_dir.rglob("*.model3.json")):
            info = self._parse(m3)
            if info is not None:
                self.models.append(info)

        # C++ 兼容索引：仅统计 <目录>/<目录名>.model3.json，
        # 并按目录名做大小写敏感字典序（对应 C++ strcmp + qsort）。
        switch = [m for m in self.models
                  if Path(m.path).parent.name == m.name]
        switch.sort(key=lambda m: Path(m.path).parent.name)
        self.switch_models = switch

        self._scanned = True
        logger.info("模型扫描完成: 共 %d 个（switch 索引 %d 个）",
                    len(self.models), len(self.switch_models))
        return self.models

    def _parse(self, m3: Path) -> ModelInfo | None:
        """解析单个 model3.json 文件。"""
        try:
            data = json.loads(m3.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 单文件失败不应中断扫描
            logger.warning("解析模型失败 %s: %s", m3, exc)
            return None
        if not isinstance(data, dict):
            logger.warning("模型文件格式异常（非 JSON 对象）: %s", m3)
            return None

        refs = data.get("FileReferences", {}) or {}

        # 表情：FileReferences.Expressions[].Name
        expressions: list[str] = []
        for item in refs.get("Expressions", []) or []:
            if isinstance(item, dict) and item.get("Name"):
                expressions.append(str(item["Name"]))

        # 动作：FileReferences.Motions = { 组名: [条目] }
        motion_groups: dict[str, int] = {}
        motion_files: list[str] = []
        motions = refs.get("Motions", {}) or {}
        for group, items in motions.items():
            if not isinstance(items, list):
                continue
            motion_groups[str(group)] = len(items)
            for item in items:
                if isinstance(item, dict) and item.get("File"):
                    motion_files.append(str(item["File"]))

        # 模型专属 Prompt（可选）：与 model3.json 同级的 model_prompt.txt
        custom_prompt = ""
        prompt_file = m3.parent / MODEL_PROMPT_FILE
        if prompt_file.exists():
            try:
                custom_prompt = prompt_file.read_text(encoding="utf-8").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取模型专属 Prompt 失败 %s: %s", prompt_file, exc)

        rel = m3.parent.relative_to(self.base_dir)
        directory = str(rel).replace("\\", "/") if str(rel) != "." else ""

        return ModelInfo(
            # 基名 = 去掉 ".model3.json" 后缀（Path.stem 只会去掉 ".json"，
            # 会把 "Haru.model3.json" 错算成 "Haru.model3"，导致与所在目录名不匹配）。
            name=m3.name.removesuffix(".model3.json"),
            directory=directory,
            model_file=m3.name,
            expressions=expressions,
            motion_groups=motion_groups,
            motion_files=motion_files,
            custom_prompt=custom_prompt,
            path=str(m3),
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_model(self, index: int) -> ModelInfo | None:
        """按 switch 索引取模型；越界返回 None。"""
        if 0 <= index < len(self.switch_models):
            return self.switch_models[index]
        return None

    def index_of(self, name: str) -> int:
        """按模型名查 switch 索引；未找到返回 -1。"""
        for i, model in enumerate(self.switch_models):
            if model.name == name:
                return i
        return -1

    def model_names(self) -> list[str]:
        """switch 索引中的模型名列表。"""
        return [m.name for m in self.switch_models]

    def current(self, index: int = 0) -> ModelInfo | None:
        """取当前活动模型（默认索引 0）。"""
        return self.get_model(index) or (self.switch_models[0] if self.switch_models else None)

    def current_expressions(self, index: int = 0) -> list[str]:
        m = self.current(index)
        return list(m.expressions) if m else []

    def current_motions(self, index: int = 0) -> list[str]:
        m = self.current(index)
        return list(m.motion_groups.keys()) if m else []

    def current_custom_prompt(self, index: int = 0) -> str:
        m = self.current(index)
        return m.custom_prompt if m else ""

    # ------------------------------------------------------------------
    # Prompt 片段生成
    # ------------------------------------------------------------------
    def build_prompt_fragment(self, index: int = 0) -> str:
        """生成模型专属 Prompt 片段（供 LLM 动态注入）。

        组合：可用表情 / 动作组清单 + model_prompt.txt 的模型专属规则。
        """
        m = self.current(index)
        if m is None:
            return ""
        lines: list[str] = []
        if m.expressions:
            lines.append(f"当前模型可用的表情: {', '.join(m.expressions)}")
        if m.motion_groups:
            groups = ", ".join(f"{g}({n})" for g, n in m.motion_groups.items())
            lines.append(f"当前模型可用的动作组: {groups}")
        if m.custom_prompt:
            lines.append(f"【模型专属规则】\n{m.custom_prompt}")
        return "\n".join(lines)


if __name__ == "__main__":
    # 自测：python model_scanner.py [模型目录]
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    scanner = ModelScanner(sys.argv[1] if len(sys.argv) > 1 else None)
    scanner.scan()
    print(f"\nswitch 索引（C++ 兼容顺序）:")
    for i, m in enumerate(scanner.switch_models):
        print(f"  [{i}] {m.name}  表情={m.expressions}  动作组={m.motion_groups}")
    print(f"\n全部模型（含嵌套）: {[m.name for m in scanner.models]}")
    frag = scanner.build_prompt_fragment()
    print(f"\nPrompt 片段:\n{frag if frag else '(无模型)'}")
