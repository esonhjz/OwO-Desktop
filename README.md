<div align="center">

# 🐱 OwO-Desktop

**基于 Direct3D 11 与 Live2D Cubism Native SDK 的高性能无边框透明桌面精灵**

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows)](https://microsoft.com)
[![Language](https://img.shields.io/badge/C%2B%2B-17-00599C?logo=c%2B%2B)](https://isocpp.org/)
[![Graphics](https://img.shields.io/badge/Graphics-Direct3D%2011-00599C)](https://learn.microsoft.com/en-us/windows/win32/direct3d11/at-a-glance)
[![Live2D](https://img.shields.io/badge/Live2D-Cubism%20SDK%20Native-00A4E4)](https://www.live2d.com/)
[![Protocol](https://img.shields.io/badge/Network-WebSocket-FF6C37)](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)

*轻量 · 高效 · 低延迟控制 · 透明挂件*

</div>

---

## ✨ 核心特性

- 🪟 **无边框透明渲染**：原生 Direct3D 11 硬件加速渲染，支持精细裁切遮罩（2048 Mask Buffer）与边缘平滑。
- 🎮 **便捷键盘交互**：按 `Space` 顺序切换模型，数字键 `1` ~ `9` 精确指定模型。
- 🌐 **WebSocket 远程控制**：轻量化 JSON 指令协议，支持表情控制、动作触发、口型联动与模型切换。
- ⚡ **最新覆盖式设计**：指令接收采用无堆积覆盖机制，配合口型 200ms 超时自动闭合，保证高频控制极速无延迟。
- 🔄 **自动重连与抗网络抖动**：内置 WebSocket 客户端具备断线自动重连，掉线无需重启程序。

---

## 📂 项目结构

```text
OwO-Desktop/
├── CMakeLists.txt                  # CMake 构建脚本 (C++17, MSVC, D3D11)
├── src/                            # 核心业务逻辑
│   ├── main.cpp                    # WinMain 程序入口
│   ├── NetworkManager.hpp/.cpp     # WebSocket 客户端网络管理器
│   └── ControlCommand.hpp          # 远程控制指令数据结构
├── engine/                         # Live2D 引擎封装（D3D11 渲染层）
│   ├── Framework/                  # Live2D Cubism SDK Framework
│   └── Wrapper/                    # 窗口/模型/渲染核心封装
├── test/                           # 测试辅助脚本
│   └── test_ws_server.py           # WebSocket 模拟服务端 (Python)
├── assets/models/                  # 🚫 模型资源目录 (gitignored)
├── third_party/                    # 🚫 第三方依赖库 (gitignored)
│   ├── Live2D_SDK/Core/            #   Cubism Core SDK（闭源）
│   ├── DirectXTK/                  #   DirectX Tool Kit
│   ├── ixwebsocket/                #   IXWebSocket v11.4.6
│   └── nlohmann/                   #   nlohmann/json Header-Only
└── build/                          # 🚫 CMake 构建产物目录
```

> [!NOTE]
> 标有 🚫 的目录已在 `.gitignore` 中忽略，仅保留 `.gitkeep` 占位文件。克隆仓库后需按提示手动准备依赖与模型。

---

## 🚀 快速开始

```powershell
# 1. 准备依赖（请参阅下方「依赖准备」章节）
# 2. 将 Live2D 模型拷贝至 assets/models/<模型文件夹>/

# 3. 编译并运行
cmake -B build -S . -A x64
cmake --build build --config Release
.\build\bin\Release\DesktopLive2D.exe
```

---

## 🎮 控制与协议说明

### 1. 键盘按键映射

| 按键 | 功能描述 |
| :--- | :--- |
| <kbd>Space</kbd> | 顺序切换下一个模型 |
| <kbd>1</kbd> ~ <kbd>9</kbd> | 快捷跳转到第 N 个模型 |

### 2. WebSocket 远程控制协议

程序启动后会自动连接服务端 `ws://127.0.0.1:3000/ws`，支持发送 JSON 格式控制指令：

```json
{"type": "expression",   "name": "F01"}
{"type": "motion",       "group": "TapBody", "no": 0, "priority": 3}
{"type": "lipsync",      "value": 0.75}
{"type": "switch_model"}
{"type": "switch_model", "index": 2}
```

#### 指令参数说明

| 字段 `type` | 额外参数 | 参数说明与行为 |
| :--- | :--- | :--- |
| `expression` | `"name": "F01"` | 切换指定名称的表情（名称取决于模型配置） |
| `motion` | `"group": "TapBody"`, `"no": 0`, `"priority": 3` | 触发动作组与序号，`priority` 越高优先级越大 |
| `lipsync` | `"value": 0.75` | 口型张合度（`0.0`=完全闭合，`1.0`=完全张开）。停止发送 200ms 后自动回归 closed 状态 |
| `switch_model` | `["index": 2]` | 不填 `index` 时切换至下一个模型；填 `index` 时精确跳转指定序号 |

> [!TIP]
> **覆盖式设计**：高频发送口型或表情时，程序仅响应最新接收到的帧指令，无需担心消息队列堆积导致的卡顿或延迟。

### 3. 本地 WebSocket 测试脚本

内置 Python 交互式测试脚本，可直接发送指令测试桌宠联动：

```powershell
pip install websockets
python test\test_ws_server.py
```

---

## 🛠️ 依赖准备

因版权与仓库体积限制，`third_party/` 与 `assets/models/` 未包含在 git 跟踪中。拉取代码后需依次准备：

### 1. nlohmann/json
下载 Header-only 库至 `third_party/nlohmann/json.hpp`：

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/nlohmann/json/develop/single_include/nlohmann/json.hpp" -OutFile "third_party\nlohmann\json.hpp"
```

### 2. IXWebSocket
拉取 v11.4.6 指定版本：

```powershell
git clone https://github.com/machinezone/IXWebSocket.git third_party/ixwebsocket --depth 1 -b v11.4.6
# ⚠️ 删除内部 .git 文件夹，防止嵌套仓库被外层 git 忽略
cmd /c "rmdir /s /q third_party\ixwebsocket\.git"
```

> [!NOTE]
> 如遇国内访问网络限制，可替换为镜像地址：`https://gitee.com/mirrors/IXWebSocket.git`

### 3. Live2D Cubism SDK Core
前往 [Live2D 官方网站](https://www.live2d.com/en/sdk/download/native/) 下载 **Cubism SDK for Native**，提取 `Core/` 文件夹放入 `third_party/Live2D_SDK/Core/`。

目录层次应如下：
```text
third_party/Live2D_SDK/Core/
├── include/
│   └── Live2DCubismCore.h
└── lib/
    └── windows/x86_64/143/
        └── Live2DCubismCore_MD.lib
```

### 4. DirectXTK (DirectX Tool Kit)
从 [Microsoft DirectXTK GitHub](https://github.com/microsoft/DirectXTK) 下载并放入 `third_party/DirectXTK/`（需包含预编译 `.lib` 文件或 CMake 子工程）。

### 5. Live2D 模型资源
将 Live2D 模型解压并放入 `assets/models/` 目录下，示例如下：

```text
assets/models/
├── Haru/
│   ├── Haru.model3.json
│   ├── Haru.moc3
│   └── ...
└── Hiyori/
    └── ...
```

---

## 🏗️ 编译与构建环境

### 环境要求

- **操作系统**：Windows 10 / 11 (x64)
- **编译器**：Visual Studio 2022+ (MSVC C++17)
- **构建工具**：CMake 3.16+
- **版本控制**：Git

### 完整编译流程

```powershell
# 生成 Visual Studio 工程文件
cmake -B build -S . -A x64

# 执行 Release 编译
cmake --build build --config Release
```

构建成功后，可执行文件将位于：`build\bin\Release\DesktopLive2D.exe`

> [!TIP]
> CMake 脚本会自动优先寻找 `third_party/` 中的本地依赖文件；若本地未安装，将自动启用 `FetchContent` 在线拉取补全。

---

## 💻 技术栈

| 模块 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| **开发语言** | C++17 | 标准现代 C++ |
| **图形渲染** | Direct3D 11 | Windows 原生 3D 渲染 API |
| **模型引擎** | Live2D Cubism Native SDK | Live2D 官方原生 C++ SDK |
| **网络通讯** | [IXWebSocket](https://github.com/machinezone/IXWebSocket) (v11.4.6) | 轻量高效 WebSocket 客户端 |
| **数据解析** | [nlohmann/json](https://github.com/nlohmann/json) | Header-only JSON 解析器 |
| **数学工具** | [DirectXTK](https://github.com/microsoft/DirectXTK) | 微软 Direct3D 辅助工具包 |
| **构建系统** | CMake + MSVC | 跨编译器与 IDE 构建方案 |

---

<div align="center">

Made with ❤️ for Live2D Desktop Pets

</div>
