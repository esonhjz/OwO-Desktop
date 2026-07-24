/**
 * @file AgentNetworkClient.cpp
 * @brief Implementation placeholder for future WebSocket communication and Agent control.
 */

#include "AgentNetworkClient.hpp"

namespace desktop {

AgentNetworkClient::AgentNetworkClient()
    : _isConnected(false)
{
}

AgentNetworkClient::~AgentNetworkClient()
{
}

bool AgentNetworkClient::Initialize(const std::string& serverUri)
{
    _serverUri = serverUri;
    // Reserved: Establish WebSocket handshake with external AI Agent server
    _isConnected = false;
    return true;
}

void AgentNetworkClient::Update()
{
    if (!_isConnected)
    {
        return;
    }
    // Reserved: Poll incoming WebSocket frames, parse JSON commands, and trigger _commandHandler
}

void AgentNetworkClient::SetCommandHandler(CommandHandler handler)
{
    _commandHandler = handler;
}

bool AgentNetworkClient::SendAgentEvent(const std::string& eventType, const std::string& jsonPayload)
{
    if (!_isConnected)
    {
        return false;
    }
    // Reserved: Send event string / JSON back to AI Agent server
    return true;
}

} // namespace desktop
