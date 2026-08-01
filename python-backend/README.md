# python-backend — L2D 控制系统 Phase 2（Python AI 后端）

对应设计文档 [`docs/plan/l2d_control_system.md`](../docs/plan/l2d_control_system.md)
Phase 2。本目录实现「LLM 情感 → 表情/动作指令 → WebSocket 广播 → TTS → 口型」的 Python 侧链路，
与 OwO-Desktop (C++) 渲染端通过 WebSocket 对接。

> **状态**：Phase 2 已完成，真机联调通过（2026-08-02）。可独立运行与联调。不修改 OwO-Desktop 任何 C++ 代码。
>
> **借鉴来源**：部分设计借鉴了 [SoulLink_Live2D](https://github.com/guansss/SoulLink_Live2D)
> （MIT 开源项目，LLM 驱动的 Live2D 表情控制系统）。借鉴点与出处详见文末
> [借鉴来源与 MIT 署名](#借鉴来源与-mit-署名)。

---

## 目录结构

```
python-backend/
├── server.py          # WebSocket 服务端（ws://0.0.0.0:3000/ws），指令广播 + 终端交互 + echo 测试
├── emotion_mapper.py  # LLM 情绪标签 → expression / motion 指令映射（权重组合 + intensity 联动）
├── llm_client.py      # LLM 调用封装：强制输出含 emotion 的结构化 JSON，缓存 + 本地兜底；mock 模式
├── tts_client.py      # TTS 合成封装：mock / edge-tts / openai（OpenAI 兼容），流式 + 持续口型
├── model_scanner.py   # Live2D 模型目录扫描：解析 model3.json，维护 switch 索引，生成模型 Prompt
├── config.py          # 可选 config.yaml 配置加载（字段级继承，config.yaml > 环境变量 > 默认值）
├── config.example.yaml# config.yaml 示例（复制为 config.yaml 使用）
├── requirements.txt   # 依赖清单
├── test_integration.py# 既有集成测试（指令构造 / WS 广播 / echo / 路径校验）
├── test_phase2.py     # Phase 2 新增功能测试（config / scanner / mapper / llm / tts，离线 mock）
└── chat_live_demo.py  # 联调驱动演示脚本（等待客户端连接，跑完整 chat 链路）
```

## 各文件职责

| 文件 | 职责 | 关键对外接口 |
| :--- | :--- | :--- |
| `server.py` | 监听 `ws://0.0.0.0:3000/ws`，接受 OwO-Desktop 客户端连接；维护多客户端；广播/定向发送指令；终端交互输入；echo 测试模式；`chat <文本>` 跑通完整管线（含对话历史、模型上下文注入、并行情绪映射、播放期持续口型） | `L2DServer`, `send_command()`, `build_command()`, `parse_input_line()` |
| `emotion_mapper.py` | 把 LLM 情绪标签映射为 `expression`/`motion` 指令；支持多标签权重组合、intensity 联动 priority、本地关键词兜底 | `EMOTION_MAP`, `map_emotion()`, `keyword_fallback()`, `priority_for_intensity()` |
| `llm_client.py` | 调用 OpenAI 兼容 LLM；系统提示词动态注入模型清单，强制输出含 `emotion`/`intensity` 的 JSON；高频情绪缓存；API 失败回退本地兜底；未配置 `LLM_API_KEY` 时 mock 模式 | `LLMClient`, `LLMResult`, `LLMConfig`, `chat()` |
| `tts_client.py` | 合成语音（mock=WAV / edge-tts=MP3+词边界 / openai=OpenAI 兼容 MP3）；两套口型算法；流式合成；播放期持续口型 | `TTSClient`, `compute_volume_lipsync()`, `lipsync_from_word_boundaries()`, `iter_lipsync()`, `synthesize_stream()` |
| `model_scanner.py` | 扫描模型目录、解析 model3.json，提取表情/动作清单，维护与 C++ 端一致的 switch 索引，读取 `model_prompt.txt` 生成模型 Prompt | `ModelScanner`, `ModelInfo`, `build_prompt_fragment()` |
| `config.py` | 可选 config.yaml 加载；LLM `chat` 子段缺省继承 `llm.api`（字段级继承）；未提供时回退环境变量与默认值 | `Config`, `load_config()` |
| `chat_live_demo.py` | 联调驱动演示脚本：启动服务端 → 等待 OwO-Desktop 连接 → 自动调用 `_handle_chat_pipeline`，逐条打印广播指令与分类统计 | `main()` |

## 协议

指令格式与 `../src/NetworkManager.cpp` 严格一致，均为覆盖式单条 JSON：

```json
{"type": "expression",    "name": "F01"}
{"type": "motion",        "group": "TapBody", "no": 0, "priority": 3}
{"type": "lipsync",       "value": 0.75}
{"type": "switch_model"}
{"type": "switch_model",  "index": 2}
```

> **C++ 端只识别以上 4 种指令**（NetworkManager.cpp 的分发逻辑）。`animation` / `param` /
> `background` 后端可发送，但 C++ 端暂不消费（Phase 2 协议扩展预留）。

---

## 安装

需要 Python 3.9+（代码使用 `list[str]`、`|` 类型标注等新语法）。

```bash
cd python-backend
pip install -r requirements.txt
```

> `openai`、`edge-tts`、`PyYAML` 仅在使用真实 LLM / TTS / config.yaml 时需要；
> **mock 模式下只需 `websockets`**。若只做联调，可只装：`pip install websockets`

---

## 运行

### 1. 启动服务端（默认交互模式）

```bash
cd python-backend
python server.py
# 输出：L2D 控制服务已启动: ws://0.0.0.0:3000/ws (echo=False)
```

常用参数：

```bash
python server.py --echo                 # echo 测试模式：回显 + 对新客户端自动播放测试序列
python server.py --port 4000            # 自定义端口
python server.py --model-dir ../assets/models               # 显式指定模型目录
python server.py --send "motion TapBody 0 3"     # 启动后先广播一条指令
python server.py --no-interactive       # 服务模式（无终端交互，适合由其他程序拉起）
```

> 启动时会自动加载可选的 `config.yaml`（见下文「配置」），并尝试用 `model_scanner`
> 扫描模型目录（默认 `../assets/models`，可通过 `--model-dir` / `MODEL_DIR` /
> config.yaml 覆盖）。扫描失败或目录不存在会自动禁用，不影响服务启动。

### 2. 终端交互指令

启动后可输入（支持完整 JSON 或简化语法）：

```
expression F01                     → {"type":"expression","name":"F01"}
motion TapBody 0 3                 → {"type":"motion","group":"TapBody","no":0,"priority":3}
lipsync 0.75                       → {"type":"lipsync","value":0.75}
switch_model                       → {"type":"switch_model"}             （下一模型）
switch_model 2                     → {"type":"switch_model","index":2}
animation greeting                 → {"type":"animation","name":"greeting"}
param ParamAngleX 15.0             → {"type":"param","id":"ParamAngleX","value":15.0}
background bg_night.png            → {"type":"background","file":"bg_night.png"}
chat 今天心情如何？                 → 完整管线演示：LLM→情绪→TTS→口型（含对话历史）
echo on / off                      → 运行期开关 echo 测试模式
clients                            → 查看在线客户端
help / exit                        → 帮助 / 退出
```

也可以直接输入完整 JSON，如：`{"type":"expression","name":"F01"}`。

### 3. 与 OwO-Desktop (C++) 联调

1. 启动 `OwO-Desktop`（C++ 端默认连接 `ws://127.0.0.1:3000/ws`）。
2. 启动本服务端：`python server.py --echo`。
3. 观察 C++ 端透明窗口依次播放：预热动作 → 表情+动作组合 → 口型扫描 → 模型切换。
4. 在服务端输入 `chat 今天天气真好，好开心呀！`，可看到完整「LLM(mock) → 表情/动作 → TTS(mock) → 口型」链路。
5. 若模型目录扫描成功，`chat` 管线会把当前模型的可用表情/动作清单注入 LLM 提示词。

### 4. 联调驱动演示脚本（chat_live_demo.py）

临时联调脚本：启动服务端 → 等待客户端连接（30s 超时）→ 自动调用完整 chat 管线 →
逐条打印广播指令（毫秒时间戳）→ 管线结束后 3 秒自动关闭并输出分类统计。

```bash
# 先启动 DesktopLive2D.exe，再运行：
.venv\Scripts\python chat_live_demo.py
```

2026-08-02 真机联调即用本脚本驱动（详见下文「真机联调验证结果」）。

---

## 配置

### 1. config.yaml（可选，字段级继承）

把 `config.example.yaml` 复制为 `config.yaml` 并按需修改。解析优先级：
**config.yaml > 环境变量 > 默认值**。

```yaml
server:
  host: 0.0.0.0
  port: 3000
  path: /ws

llm:
  api:
    apiKey: ""                       # 为空则启用 mock 模式
    baseUrl: https://api.openai.com/v1
    model: gpt-4o-mini
    temperature: 0.2                 # 0.1~0.3 保证输出一致性（表情控制）
    timeout: 60
    jsonMode: false
  chat:                              # 对话专用：缺省字段自动继承 llm.api
    model: gpt-4o-mini

tts:
  engine: mock                       # mock | edge-tts | openai
  voice: zh-CN-XiaoxiaoNeural
  baseUrl: https://api.openai.com/v1
  apiKey: ""
  model: tts-1
  speed: 1.0

model:
  directory: ../assets/models
```

`llm.chat` 是「字段级继承」的典型：只写 `model` 时，`temperature` / `baseUrl` /
`apiKey` 等自动继承 `llm.api` 段（借鉴 SoulLink `src/config/manager.py`）。

### 2. 环境变量

#### LLM（llm_client.py）

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `LLM_API_KEY` | API 密钥；**为空则启用 mock 模式** | 空 |
| `LLM_BASE_URL` | OpenAI 兼容服务地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名 | `gpt-4o-mini` |
| `LLM_TEMPERATURE` | 采样温度（Phase 2 默认调至 0.2，建议 0.1~0.3） | `0.2` |
| `LLM_TIMEOUT` | 请求超时（秒） | `60` |
| `LLM_JSON_MODE` | 设为 `1` 时向 API 传 `response_format={"type":"json_object"}` | `0` |
| `LLM_MAX_TOKENS` | 最大输出 token 数（不设则不限） | 空 |

示例（Windows PowerShell）：

```powershell
$env:LLM_API_KEY="sk-xxx"; $env:LLM_BASE_URL="https://api.openai.com/v1"; $env:LLM_MODEL="gpt-4o-mini"
python server.py
```

LLM 输出格式（强制 JSON，Phase 2 新增 `intensity` 情绪强度）：

```json
{
  "reply": "很高兴见到你！",
  "emotion": "joy",
  "emotion_weights": {"joy": 0.8, "neutral": 0.2},
  "intensity": 0.8
}
```

> 高频情绪缓存：相同输入直接命中缓存；API 失败时回退本地关键词兜底
> （`emotion_mapper.keyword_fallback`），保证管线始终可用。

#### TTS（tts_client.py）

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `TTS_ENGINE` | `mock` / `edge-tts` / `openai` | `mock` |
| `TTS_VOICE` | 发音人（edge-tts 默认 `zh-CN-XiaoxiaoNeural`；openai 默认 `alloy`） | 见左 |
| `TTS_RATE` | 语速（仅 edge-tts） | `+0%` |
| `TTS_SAMPLE_RATE` | mock 模式采样率 | `24000` |
| `TTS_BASE_URL` | OpenAI 兼容 TTS 地址 | `https://api.openai.com/v1` |
| `TTS_API_KEY` | OpenAI 兼容 TTS 密钥（openai 引擎必需） | 空 |
| `TTS_MODEL` | TTS 模型（openai 引擎） | `tts-1` |
| `TTS_SPEED` | 语速倍数 0.25~4.0（openai 引擎） | `1.0` |

> openai 引擎按 `POST {baseUrl}/audio/speech`（response_format=mp3）实现；
> 输出为 MP3 未解码，口型用「文本音节 → 词边界」时间戳法（两套算法之一）。
> `synthesize_stream()` 支持流式合成；`iter_lipsync()` 供 TTS 播放期间持续推送口型。

#### 模型扫描（model_scanner.py）

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `MODEL_DIR` | Live2D 模型目录 | `../assets/models` |

> **switch_model 索引约定**：与 C++ 端 `LAppLive2DManager::LoadModels` 保持一致——
> 仅统计 `<目录>/<目录名>.model3.json`，并按目录名做大小写敏感字典序排序（C++ 用
> `qsort` + `strcmp`）。这样后端发送的 `switch_model index` 与 C++ 场景索引一一对应。
> 每个模型目录下可放 `model_prompt.txt`（参考 `model_prompt_example.txt`）作为
> 模型专属规则，会自动注入 LLM 提示词。

---

## 模块自测

各模块自带 `__main__` 自测，可直接运行验证逻辑：

```bash
python emotion_mapper.py   # 打印若干情绪映射结果 + 关键词兜底
python llm_client.py       # mock 调用 + JSON 提取 + 动态提示词注入校验
python tts_client.py       # mock 合成 + 两套口型算法 + iter_lipsync
python model_scanner.py    # 扫描模型目录 + switch 索引 + Prompt 片段
python config.py           # 打印当前生效配置
```

---

## 测试

```bash
.venv\Scripts\python test_integration.py   # 既有：指令构造 / WS 广播 / echo / 路径校验
.venv\Scripts\python test_phase2.py        # 新增：config 继承 / scanner / mapper / llm / tts（离线 mock）
```

`test_phase2.py` 全部离线运行，不依赖真实 LLM / TTS / 网络（LLM 与 TTS 的 API 调用
以假 `openai` 模块触发或拦截）。

---

## 真机联调验证结果（2026-08-02）

- **环境**：venv 依赖 websockets 17.0.1、PyYAML 6.0.3；`DesktopLive2D.exe` 客户端经
  `ws://127.0.0.1:3000/ws` 连接成功。
- **指令级验证**：autotest 4 指令序列（expression F01-F03、motion TapBody、lipsync
  0→1→0、switch_model ×2）全部送达客户端。
- **chat 完整链路**（由 `chat_live_demo.py` 驱动）：LLM mock 判定 joy / intensity 0.80
  → 广播 expression F01 + motion TapBody(priority 4) → TTS 合成 5.10s / 171 帧口型 →
  lipsync 推送 173 条，全程共 **176 条指令**逐条送达客户端；C++ 客户端窗口运行正常。
- **自动化测试**：`test_phase2.py` 五项全过，`test_integration.py` 通过，三个模块自测通过。

> 以上验证均基于 mock LLM / TTS。真实 LLM / TTS 需配置 API Key 后接入（见「配置」节）。

---

## 已知边界与说明

1. **口型 200ms 超时**：C++ 端停止收到 `lipsync` 200ms 后自动线性闭合。服务端在 `chat`
   管线结束时会主动补发一条 `lipsync 0.0` 加速回零；`iter_lipsync` 即使中断，
   口型也能由 C++ 超时逻辑平滑回零。
2. **表情/动作名依赖模型资源**：`emotion_mapper.EMOTION_MAP` 中默认的 `F01~F05`、
   `TapBody` 等需与模型 `.exp3.json` / `.model3.json` 对应。可结合 `model_scanner`
   的输出核对，或按模型调整映射表。
3. **edge-tts / openai 输出为 MP3**：未解码时无法做音量包络，口型由时间戳法生成。
4. **switch_model 索引**：后端索引与 C++ 加载顺序一致（见「模型扫描」节）；若 C++
   端更换模型目录，请重新扫描。
5. **Windows 终端**：交互输入通过守护线程读取，普通控制台使用正常；若在无控制台/
   重定向环境下运行，建议加 `--no-interactive`。
6. **websockets 版本**：代码兼容 websockets 10.x~14.x，对旧版 `handler(ws, path)`
   签名也做了适配；真机联调 venv 环境 websockets 17.0.1 实测通过。
7. **config.yaml 需 PyYAML**：未安装时 `config.py` 自动回退到环境变量/默认值，
   不影响服务启动。

---

## 借鉴来源与 MIT 署名

本模块的若干设计借鉴了 **SoulLink_Live2D**（MIT License，LLM 驱动的 Live2D 表情
控制系统）。借鉴的是**设计思路**，并针对本项目的 4 指令协议
（expression / motion / lipsync / switch_model）与 Python 架构做了重写适配，未逐字
复制其代码。借鉴点与出处：

| 借鉴设计 | SoulLink 出处 | 本项目的适配实现 |
| :--- | :--- | :--- |
| Prompt 工程：角色明确（表情控制器）、动态注入可用参数/动作清单、强制 JSON、强调效果明显 | `docs/LLM_EXPRESSION_PRINCIPLE.md`、`src/generators/expression.py::_generate_system_prompt` | `llm_client.build_system_prompt()`：注入 expression/motion 清单与模型专属规则，强制输出含 `intensity` 的 JSON |
| 参数 clamp / 眼睛二值 / 联合动作增强 | `src/generators/expression.py::_clamp_parameters` | 本协议由 emotion_mapper 输出指令，暂不需要参数 clamp；`intensity → motion priority` 联动为对应适配 |
| 本地关键词 → 情绪 → 预设兜底 | `src/generators/local_expression.py::_extract_emotion` | `emotion_mapper.keyword_fallback()`：文本 → (情绪, 强度)；`llm_client._chat_fallback()` API 失败回退链 |
| OpenAI 兼容 TTS（`POST {base_url}/audio/speech`，mp3，流式） | `src/generators/tts.py` | `tts_client` openai 引擎：`_synthesize_openai()` / `synthesize_stream()` |
| 模型目录扫描、解析 model3.json、索引 motions/expressions | `src/models/scanner.py` | `model_scanner.ModelScanner`，并额外对齐 C++ 端 switch 索引顺序 |
| 字段级继承配置（llm.api.expression/chat 分离，chat 继承 api 默认值） | `config.yaml`、`src/config/manager.py` | `config.py`：`llm.chat` 缺省字段继承 `llm.api`；解析优先级 config.yaml > 环境变量 > 默认值 |
| 模型专属 Prompt（开关型参数、范围约束、表情组合建议） | `model_prompt_example.txt` | `model_scanner` 读取模型目录下的 `model_prompt.txt` 并注入 LLM 提示词 |
| 对话历史截断（最近 N 条）、temperature 设置 | `src/generators/chat.py` | `server._handle_chat_pipeline()`：最近 `chat_history_max` 条（默认 6） |
| 缓存高频情绪、本地预设兜底、temperature 0.1~0.3、聊天与表情并行 | `docs/LLM_EXPRESSION_PRINCIPLE.md`（性能优化建议 / 并发处理） | `llm_client` 文本+情绪双缓存、`asyncio.gather` 并行广播、temperature 默认 0.2 |

SoulLink_Live2D 版权信息：本项目仅借鉴设计思路，不包含其版权代码片段；如需引用
其文档/代码，请保留其 MIT License 声明（[SoulLink_Live2D](https://github.com/guansss/SoulLink_Live2D)）。

---

## 验证与虚拟环境

- 推荐在项目内创建虚拟环境后安装依赖：python -m venv .venv，再 .venv\Scripts\python -m pip install -r requirements.txt（沙箱/受限环境下可用镜像源）。
- 集成测试（不依赖 pytest，直接运行）：.venv\Scripts\python test_integration.py，覆盖指令构造、广播送达、echo 回显与路径校验。
- Phase 2 新增功能测试：.venv\Scripts\python test_phase2.py，离线 mock 运行，覆盖 config / scanner / mapper / llm / tts。
- 真机联调（2026-08-02）：见上文「真机联调验证结果」；`chat_live_demo.py` 为联调驱动演示脚本。
- 各模块均带 __main__ 自测，mock 模式下无需 openai/edge-tts。
