<div align="center">

# 🐱 OwO-Desktop

**A Windows Live2D desktop character application with Direct3D 11 rendering and WebSocket control**

[English](README.md) | [中文](README_zh.md)

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows)](https://www.microsoft.com/windows)
[![Language](https://img.shields.io/badge/Language-C%2B%2B17-00599C?logo=c%2B%2B)](https://isocpp.org/)
[![Graphics](https://img.shields.io/badge/Graphics-Direct3D%2011-0078D4)](https://learn.microsoft.com/windows/win32/direct3d11/at-a-glance)
[![Protocol](https://img.shields.io/badge/Protocol-WebSocket-FF6C37)](https://developer.mozilla.org/docs/Web/API/WebSocket)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

OwO-Desktop turns structured backend commands into Live2D character expressions, motions, and lip-sync. It combines a C++ Windows client with a Python backend for LLM-driven emotion mapping, TTS, and model scanning.

## Highlights

- Borderless, transparent desktop window using Direct3D 11 and the Live2D Cubism Native SDK.
- Keyboard model switching: `Space` cycles models; `1` through `9` select a model directly.
- A small WebSocket JSON protocol for expressions, motions, lip-sync, and model switching.
- Latest-command handling for expressions and motions, preventing stale commands from accumulating after the conversation has changed.
- Automatic WebSocket reconnection and a 200 ms lip-sync timeout that closes the mouth after updates stop.
- A Python backend with a WebSocket server, LLM emotion mapping, TTS-driven lip-sync, model scanning, and offline mock-mode tests.

## Architecture

```text
User message
  -> Python backend
     -> LLM response and emotion mapping
     -> TTS and lip-sync frames
  -> WebSocket JSON commands
  -> C++ client
  -> Live2D expression, motion, and lip-sync
```

The backend and client share four command types:

```json
{"type": "expression", "name": "F01"}
{"type": "motion", "group": "TapBody", "no": 0, "priority": 3}
{"type": "lipsync", "value": 0.75}
{"type": "switch_model", "index": 2}
```

`expression` and `motion` use latest-command semantics. The client stores the latest received value and applies it on the render side, rather than replaying a backlog of stale commands.

## Repository Layout

```text
OwO-Desktop/
├── src/                    # Application-side C++ control and networking code
│   ├── NetworkManager.*     # WebSocket client, reconnection, latest-command handling
│   └── ControlCommand.hpp   # Shared JSON command representation
├── python-backend/          # WebSocket server, LLM/TTS integration, model scanning, tests
├── test/                    # C++ client WebSocket test helper
├── engine/                  # Live2D integration layer
├── assets/models/           # Local model assets (not tracked)
└── third_party/             # Local dependencies (not tracked)
```

## Quick Start

### Prerequisites

- Windows 10 or 11 (x64)
- Visual Studio 2022 or later with C++17 support
- CMake 3.16 or later
- Live2D Cubism SDK for Native Core
- DirectXTK, IXWebSocket, and nlohmann/json
- A compatible Live2D model in `assets/models/`

The copyrighted model assets and local third-party dependencies are intentionally not tracked in this repository.

### Build the Client

```powershell
cmake -B build -S . -A x64
cmake --build build --config Release
.\build\bin\Release\DesktopLive2D.exe
```

The client connects to `ws://127.0.0.1:3000/ws` by default.

### Run the Python Backend

```powershell
cd python-backend
pip install -r requirements.txt
python server.py --echo
```

The default mock mode needs only `websockets`. For real LLM or TTS providers, configure the backend as documented in [python-backend/README.md](python-backend/README.md).

## Testing

The project includes a simple WebSocket test server for the C++ client:

```powershell
pip install websockets
python test\test_ws_server.py
```

Backend checks can run in offline mock mode:

```powershell
cd python-backend
python test_integration.py
python test_phase2.py
```

## Scope and Third-Party Components

This repository's application-layer work includes the WebSocket control protocol, client/server integration, reconnect behavior, latest-command handling, the Python backend, and integration tests.

The following are third-party components or assets and remain under their own licenses and terms:

- `engine/Framework/`, `FrameworkShaders/`, and `SampleShaders/`
- Live2D Cubism SDK/Core and Live2D model assets
- DirectXTK, IXWebSocket, and nlohmann/json

## License

Original code in this repository is licensed under the [MIT License](LICENSE). The MIT License does **not** apply to third-party SDKs, dependencies, shaders, or model assets. Please review and comply with the relevant licenses before redistributing those components.
