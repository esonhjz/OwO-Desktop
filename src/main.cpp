/**
 * @file main.cpp
 * @brief Application entry point for Desktop Live2D agent renderer.
 */

#include <windows.h>
#include "LAppDelegate.hpp"
#include "AgentNetworkClient.hpp"

int APIENTRY WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow)
{
    // Initialize Agent Network Client for future WebSocket control
    desktop::AgentNetworkClient agentClient;
    agentClient.Initialize("ws://localhost:8080");

    // Initialize Win32 window, D3D11 device, and Live2D Cubism SDK
    if (!LAppDelegate::GetInstance()->Initialize())
    {
        LAppDelegate::ReleaseInstance();
        return 0;
    }

    // Execute application main render loop
    LAppDelegate::GetInstance()->Run();

    // Cleanup resources on exit
    LAppDelegate::ReleaseInstance();

    return 0;
}
