# 🖥️ Project Feibi - Desktop Live2D Client

这是一个完全解耦、符合开源合规要求、专属于 **Windows (Win32 + Direct3D11)** 的 C++ Live2D 桌面端客户端架构。

---

## 📁 目录架构 (Project Structure)

```text
desktop/
├── CMakeLists.txt              # 现代化 CMake 构建脚本 (C++17, MSVC, D3D11)
├── .gitignore                  # 严格隔离闭环 SDK、二进制及版权资产文件
├── README.md                   # 项目架构说明
├── src/                        # C++ 业务逻辑层
│   ├── main.cpp                # 应用程序主入口
│   ├── AgentNetworkClient.hpp  # WebSocket 网络通信与 Agent 逻辑控制解耦层 (预留)
│   └── AgentNetworkClient.cpp
├── engine/                     # 重构后的 Live2D SDK 引擎层
│   ├── Framework/              # 官方 Framework 源码 (已彻底剔除 OpenGL, Vulkan, Metal)
│   └── Wrapper/                # Live2D D3D11 渲染与模型管理封装层
├── third_party/                # 第三方依赖隔离目录 (.gitignore 严格忽略)
│   ├── Live2D_SDK/
│   │   └── Core/               # 闭环官方 SDK 组件 (Live2DCubismCore.h, Live2DCubismCore_MD.lib)
│   └── DirectXTK/              # DirectXTK 纹理加载库
└── assets/                     # 资产目录 (.gitignore 严格忽略)
    └── models/                 # 本地 Live2D 角色模型文件 (Phoebe-Jubi, murasame 等)
```

---

## 🛠️ 构建指南 (Build Instructions)

### 前置要求
* Windows 10 / 11
* Visual Studio 2022 / MSVC Compiler
* CMake 3.16+

### 合规检查说明
项目构建时会自动检测 `${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/include/Live2DCubismCore.h`。若缺失该文件，CMake 会输出友好的提示信息告知手动补充官方 SDK Core 组件。

### 构建步骤
```bash
# 1. 生成 CMake 构建工程
cmake -B build -S .

# 2. 编译项目 (Release 配置)
cmake --build build --config Release
```

编译生成的可执行文件位于：
`build/bin/Release/DesktopLive2D.exe`

---

## ✨ 核心特性

1. **完全解耦后端**：彻底删除了所有非 D3D11 的渲染后端（OpenGL, Vulkan, Metal），代码量大幅减少，项目纯粹轻量。
2. **合规防护 (.gitignore)**：闭环的官方 Core 组件、`*.lib` / `*.dll` 以及模型资产完全隔离并忽略，防止版权争议文件误提交。
3. **透明无边框窗口**：窗口采用 `WS_EX_LAYERED | WS_EX_TOPMOST | WS_POPUP`，配置了 `RGB(0,0,0)` ColorKey 扣除，D3D11 每帧清空为全透明背景 `(0.0f, 0.0f, 0.0f, 0.0f)`。
4. **Agent 控制预留**：`src/AgentNetworkClient` 解耦模块为未来的 WebSocket 网络通信与 AI Agent 远程操控打好了架构基础。
