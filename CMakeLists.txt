cmake_minimum_required(VERSION 3.16)

project(DesktopLive2D LANGUAGES C CXX)

# Require C++17
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler options for MSVC
if(MSVC)
    add_compile_options(/utf-8 /MP)
endif()

# =========================================================================
# License Compliance & Proprietary SDK Verification
# =========================================================================
set(LIVE2D_CORE_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/include/Live2DCubismCore.h")

if(NOT EXISTS "${LIVE2D_CORE_HEADER}")
    message(FATAL_ERROR
        "\n========================================================================\n"
        "[FATAL ERROR] Live2D Cubism SDK Core header not found!\n"
        "Missing path: ${LIVE2D_CORE_HEADER}\n\n"
        "To build this project, please follow these steps:\n"
        "1. Download 'Cubism SDK for Native (D3D11)' from the official Live2D website:\n"
        "   https://www.live2d.com/en/sdk/download/native/\n"
        "2. Extract the archive and copy the 'Core/' folder to:\n"
        "   ${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/\n"
        "3. Re-run CMake configure.\n"
        "========================================================================\n"
    )
endif()

# Locate Core Include and Library Directory
set(LIVE2D_CORE_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/include")

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(ARCH_NAME "x64")
    set(CORE_ARCH_NAME "x86_64")
else()
    set(ARCH_NAME "Win32")
    set(CORE_ARCH_NAME "x86")
endif()

# Search candidate toolset paths for Core (143 -> 142 -> 141)
set(CORE_LIB_CANDIDATES
    "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/lib/windows/${CORE_ARCH_NAME}/143"
    "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/lib/windows/${CORE_ARCH_NAME}/142"
    "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/lib/windows/${CORE_ARCH_NAME}/141"
    "${CMAKE_CURRENT_SOURCE_DIR}/third_party/Live2D_SDK/Core/lib/windows/${CORE_ARCH_NAME}"
)

find_library(LIVE2D_CORE_LIB
    NAMES Live2DCubismCore_MD Live2DCubismCore_MDd Live2DCubismCore_MT Live2DCubismCore_MTd
    HINTS ${CORE_LIB_CANDIDATES}
)

if(NOT LIVE2D_CORE_LIB)
    message(FATAL_ERROR "[FATAL ERROR] Live2DCubismCore library not found under third_party/Live2D_SDK/Core/lib/windows/")
endif()

message(STATUS "[Desktop Live2D] Found Live2DCubismCore library: ${LIVE2D_CORE_LIB}")

# =========================================================================
# DirectXTK Library Setup
# =========================================================================
set(DIRECTXTK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/DirectXTK")
set(DIRECTXTK_INCLUDE_DIR "${DIRECTXTK_DIR}/Inc")

find_library(DIRECTXTK_LIB
    NAMES DirectXTK
    HINTS
        "${DIRECTXTK_DIR}/Bin/Desktop_2022/${ARCH_NAME}/Release"
        "${DIRECTXTK_DIR}/Bin/Desktop_2022/${ARCH_NAME}/Debug"
        "${DIRECTXTK_DIR}/Bin/Desktop_2019/${ARCH_NAME}/Release"
        "${DIRECTXTK_DIR}/Bin/Desktop_2017/${ARCH_NAME}/Release"
)

if(NOT DIRECTXTK_LIB)
    message(FATAL_ERROR "[FATAL ERROR] DirectXTK library not found under third_party/DirectXTK/Bin/")
endif()

message(STATUS "[Desktop Live2D] Found DirectXTK library: ${DIRECTXTK_LIB}")

# =========================================================================
# Source Files Discovery
# =========================================================================

# Collect engine sources (Framework + Wrapper)
file(GLOB_RECURSE ENGINE_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/engine/*.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/engine/*.c"
)

# Collect custom app business sources
file(GLOB_RECURSE APP_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.c"
)

# Target executable (Win32 GUI application)
add_executable(${PROJECT_NAME} WIN32
    ${ENGINE_SOURCES}
    ${APP_SOURCES}
)

target_include_directories(${PROJECT_NAME} PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${CMAKE_CURRENT_SOURCE_DIR}/engine"
    "${CMAKE_CURRENT_SOURCE_DIR}/engine/Framework"
    "${CMAKE_CURRENT_SOURCE_DIR}/engine/Wrapper"
    "${LIVE2D_CORE_INCLUDE_DIR}"
    "${DIRECTXTK_INCLUDE_DIR}"
)

# Link Windows System Libraries & Live2D Core / DirectXTK
target_link_libraries(${PROJECT_NAME} PRIVATE
    ${LIVE2D_CORE_LIB}
    ${DIRECTXTK_LIB}
    d3d11.lib
    d3dcompiler.lib
    dxgi.lib
    user32.lib
    gdi32.lib
)

# Copy asset models & required shaders to build output directory automatically
add_custom_command(
    TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/assets/models"
        "$<TARGET_FILE_DIR:${PROJECT_NAME}>/assets/models"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/engine/Framework/Rendering/D3D11/Shaders"
        "$<TARGET_FILE_DIR:${PROJECT_NAME}>/FrameworkShaders"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/engine/Shaders/SampleShaders"
        "$<TARGET_FILE_DIR:${PROJECT_NAME}>/SampleShaders"
)

# Set properties
set_target_properties(${PROJECT_NAME} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bin"
    VS_DEBUGGER_WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
)
