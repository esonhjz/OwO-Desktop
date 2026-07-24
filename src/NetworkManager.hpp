#pragma once
#include <string>
#include <memory>
#include <atomic>
#include <mutex>
#include <thread>
#include <chrono>
#include "ControlCommand.hpp"

class LAppLive2DManager;

namespace desktop {

class NetworkManager {
public:
    static NetworkManager& GetInstance();

    bool Initialize(const std::string& serverUri);
    void Shutdown();
    void PollAndDispatch(LAppLive2DManager* live2DManager);
    bool IsConnected() const { return _connected.load(); }

private:
    NetworkManager();
    ~NetworkManager();
    NetworkManager(const NetworkManager&) = delete;
    NetworkManager& operator=(const NetworkManager&) = delete;

    void NetworkThreadFunc();

    std::atomic<bool> _expressionDirty{false};
    std::string _latestExpression;
    std::mutex _expressionMutex;

    std::atomic<bool> _motionDirty{false};
    MotionData _latestMotion;
    std::mutex _motionMutex;

    std::atomic<float> _lipSyncValue{0.0f};
    std::atomic<bool> _lipSyncDirty{false};
    std::chrono::steady_clock::time_point _lastLipSyncTime;
    float _currentLipSyncValue = 0.0f;

    std::atomic<int> _switchModelIndex{-1};

    std::atomic<bool> _connected{false};
    std::atomic<bool> _running{false};
    std::string _serverUri;
    std::unique_ptr<std::thread> _networkThread;

    struct Impl;
    std::unique_ptr<Impl> _impl;
};

} // namespace desktop
