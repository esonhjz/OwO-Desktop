# OwO-Desktop（中文）

[English](README.md) | [中文](README_zh.md)

基于 Direct3D 11、Live2D Cubism Native SDK 与 WebSocket 控制的 Windows 桌面 Live2D 角色应用。英文 README 是主文档；本页保留中文快速说明。

## 功能

- 无边框透明窗口与 Direct3D 11 渲染。
- `Space` 顺序切换模型，`1` 到 `9` 直接选择模型。
- 通过 WebSocket 接收 JSON 控制指令：表情、动作、口型与模型切换。
- 表情和动作采用 latest-command 语义，避免旧指令积压后在不合适的时刻播放。
- 客户端断线后自动重连；口型停止更新 200 ms 后自动闭合。
- `python-backend/` 提供 LLM 情绪映射、TTS 口型、模型扫描和本地 WebSocket 服务端。

## 架构

```text
User message
  -> Python backend (LLM / emotion mapping / TTS)
  -> WebSocket JSON commands
  -> C++ client
  -> Live2D expression, motion, and lip-sync
```

应用层使用四类控制指令：

```json
{"type": "expression", "name": "F01"}
{"type": "motion", "group": "TapBody", "no": 0, "priority": 3}
{"type": "lipsync", "value": 0.75}
{"type": "switch_model", "index": 2}
```

## 快速开始

1. 准备 Live2D Cubism Core、DirectXTK、IXWebSocket、nlohmann/json 与一个可使用的 Live2D 模型。
2. 将模型放到 `assets/models/<model-name>/`。
3. 生成并编译：

```powershell
cmake -B build -S . -A x64
cmake --build build --config Release
.\build\bin\Release\DesktopLive2D.exe
```

客户端默认连接 `ws://127.0.0.1:3000/ws`。后端可以按以下方式启动：

```powershell
cd python-backend
pip install -r requirements.txt
python server.py --echo
```

详细的后端配置、mock 模式、TTS 选项和测试说明见 [python-backend/README.md](python-backend/README.md)。

## 贡献边界

本仓库包含应用层的控制协议、WebSocket 客户端与服务端整合、表情/动作/口型控制、重连与 latest-command 逻辑，以及测试。`engine/Framework/`、`FrameworkShaders/`、`SampleShaders/` 和 `third_party/` 中的内容属于第三方 SDK、框架或依赖，保留其原有许可证与版权。

## 许可证

本仓库中由作者原创的代码以 [MIT License](LICENSE) 发布。Live2D Cubism、DirectXTK、IXWebSocket、nlohmann/json 和 Live2D 模型资源不受该 MIT License 覆盖；使用它们时请遵守各自的许可证与使用条款。
