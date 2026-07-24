#include "NetworkManager.hpp"

#include <ixwebsocket/IXWebSocket.h>
#include <ixwebsocket/IXNetSystem.h>
#include <json.hpp>

#include <CubismFramework.hpp>
#include <CubismDefaultParameterId.hpp>
#include <Id/CubismIdManager.hpp>
#include <Model/CubismModel.hpp>

#include "LAppLive2DManager.hpp"
#include "LAppModel.hpp"
#include "LAppPal.hpp"

using json = nlohmann::json;

namespace desktop {

struct NetworkManager::Impl {
    std::unique_ptr<ix::WebSocket> webSocket;
};

NetworkManager& NetworkManager::GetInstance() {
    static NetworkManager instance;
    return instance;
}

NetworkManager::NetworkManager()
    : _impl(std::make_unique<Impl>()) {
    ix::initNetSystem();
}

NetworkManager::~NetworkManager() {
    Shutdown();
    ix::uninitNetSystem();
}

bool NetworkManager::Initialize(const std::string& serverUri) {
    _serverUri = serverUri;
    _running.store(true);
    _networkThread = std::make_unique<std::thread>(
        &NetworkManager::NetworkThreadFunc, this);
    LAppPal::PrintLogLn("[NetworkManager] Connecting to %s", serverUri.c_str());
    return true;
}

void NetworkManager::Shutdown() {
    _running.store(false);
    if (_impl && _impl->webSocket) {
        _impl->webSocket->stop();
    }
    if (_networkThread && _networkThread->joinable()) {
        _networkThread->join();
    }
    _connected.store(false);
    LAppPal::PrintLogLn("[NetworkManager] Shutdown complete");
}

void NetworkManager::NetworkThreadFunc() {
    _impl->webSocket = std::make_unique<ix::WebSocket>();

    _impl->webSocket->setOnMessageCallback(
        [this](const ix::WebSocketMessagePtr& msg) {
            if (msg->type == ix::WebSocketMessageType::Message) {
                try {
                    auto j = json::parse(msg->str);
                    if (!j.contains("type")) return;
                    std::string type = j["type"].get<std::string>();

                    if (type == "expression" && j.contains("name")) {
                        std::lock_guard<std::mutex> lock(_expressionMutex);
                        _latestExpression = j["name"].get<std::string>();
                        _expressionDirty.store(true);
                    } else if (type == "motion" && j.contains("group")) {
                        std::lock_guard<std::mutex> lock(_motionMutex);
                        _latestMotion.group = j["group"].get<std::string>();
                        _latestMotion.no = j.value("no", 0);
                        _latestMotion.priority = j.value("priority", 3);
                        _motionDirty.store(true);
                    } else if (type == "lipsync" && j.contains("value")) {
                        _lipSyncValue.store(j["value"].get<float>());
                        _lipSyncDirty.store(true);
                        _lastLipSyncTime = std::chrono::steady_clock::now();
                    } else if (type == "switch_model") {
                        int idx = j.value("index", -1);
                        _switchModelIndex.store(idx);
                        LAppPal::PrintLogLn("[NetworkManager] Switch model request: index=%d", idx);
                    }
                } catch (const std::exception& e) {
                    LAppPal::PrintLogLn("[NetworkManager] JSON error: %s", e.what());
                }
            } else if (msg->type == ix::WebSocketMessageType::Open) {
                _connected.store(true);
                LAppPal::PrintLogLn("[NetworkManager] WebSocket connected");
            } else if (msg->type == ix::WebSocketMessageType::Close ||
                       msg->type == ix::WebSocketMessageType::Error) {
                _connected.store(false);
            }
        });

    _impl->webSocket->setUrl(_serverUri);
    _impl->webSocket->enableAutomaticReconnection();
    _impl->webSocket->start();

    while (_running.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
    _impl->webSocket->stop();
}

void NetworkManager::PollAndDispatch(LAppLive2DManager* live2DManager) {
    if (!live2DManager) return;

    // Model switching (does not need model pointer)
    int switchIdx = _switchModelIndex.exchange(-1);
    if (switchIdx >= 0) {
        LAppPal::PrintLogLn("[NetworkManager] Switching to model %d", switchIdx);
        live2DManager->ChangeScene(switchIdx);
        return;
    }

    LAppModel* model = live2DManager->GetModel(0);
    if (!model || !model->GetModel()) return;

    try {
        if (_expressionDirty.load()) {
            std::string exprName;
            { std::lock_guard<std::mutex> lock(_expressionMutex); exprName = _latestExpression; }
            _expressionDirty.store(false);
            if (!exprName.empty()) model->SetExpression(exprName.c_str());
        }

        if (_motionDirty.load()) {
            MotionData md;
            { std::lock_guard<std::mutex> lock(_motionMutex); md = _latestMotion; }
            _motionDirty.store(false);
            if (!md.group.empty()) model->StartMotion(md.group.c_str(), md.no, md.priority);
        }

        if (!_lipSyncDirty.load()) return;

        auto now = std::chrono::steady_clock::now();
        if (_lipSyncDirty.load()) {
            _currentLipSyncValue = _lipSyncValue.load();
            _lipSyncDirty.store(false);
            _lastLipSyncTime = now;
        } else {
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                now - _lastLipSyncTime).count();
            if (elapsed > 200 && _currentLipSyncValue > 0.0f) {
                _currentLipSyncValue -= (1.0f / 9.0f);
                if (_currentLipSyncValue < 0.0f) _currentLipSyncValue = 0.0f;
            }
        }

        const Csm::CubismId* mouthOpenYId =
            Csm::CubismFramework::GetIdManager()->GetId(
                Csm::DefaultParameterId::ParamMouthOpenY);
        model->GetModel()->SetParameterValue(
            mouthOpenYId, static_cast<Csm::csmFloat32>(_currentLipSyncValue));
    } catch (...) {
    }
}

} // namespace desktop
