/**
 * @file main.cpp
 * @brief Application entry point for Desktop Live2D agent renderer.
 */

#include <windows.h>
#include "LAppDelegate.hpp"
#include "NetworkManager.hpp"

int APIENTRY WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                     LPSTR lpCmdLine, int nCmdShow)
{
    // Initialize WebSocket for remote control from Python backend
    desktop::NetworkManager::GetInstance().Initialize("ws://127.0.0.1:3000/ws");

    // Initialize Win32 window, D3D11 device, and Live2D Cubism SDK
    if (!LAppDelegate::GetInstance()->Initialize())
    {
        desktop::NetworkManager::GetInstance().Shutdown();
        LAppDelegate::ReleaseInstance();
        return 0;
    }

    // Execute application main render loop
    LAppDelegate::GetInstance()->Run();

    // Cleanup resources on exit
    desktop::NetworkManager::GetInstance().Shutdown();
    LAppDelegate::ReleaseInstance();

    return 0;
}