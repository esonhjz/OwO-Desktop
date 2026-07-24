/**
 * @file AgentNetworkClient.hpp
 * @brief Reserved client logic for WebSocket communication and AI Agent remote control.
 */

#pragma once

#include <string>
#include <functional>

namespace desktop {

/**
 * @class AgentNetworkClient
 * @brief Manages network connection with external AI Agent via WebSocket.
 */
class AgentNetworkClient
{
public:
    using CommandHandler = std::function<void(const std::string& action, const std::string& payload)>;

    AgentNetworkClient();
    ~AgentNetworkClient();

    /**
     * @brief Initialize network socket / connection.
     * @param serverUri Address of the AI Agent WebSocket server (e.g. ws://localhost:8080)
     */
    bool Initialize(const std::string& serverUri);

    /**
     * @brief Poll network messages and dispatch agent control events.
     */
    void Update();

    /**
     * @brief Register a callback for incoming Agent commands (expression change, motion trigger, speech, etc.).
     */
    void SetCommandHandler(CommandHandler handler);

    /**
     * @brief Send state/event data back to the AI Agent.
     */
    bool SendAgentEvent(const std::string& eventType, const std::string& jsonPayload);

    bool IsConnected() const { return _isConnected; }

private:
    bool _isConnected;
    std::string _serverUri;
    CommandHandler _commandHandler;
};

} // namespace desktop
