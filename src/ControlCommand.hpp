/**
 * @file ControlCommand.hpp
 * @brief Control command types for Live2D model control via WebSocket.
 *
 * All commands use latest-overwrite semantics.
 */

#pragma once
#include <string>

namespace desktop {

enum class CommandType { Expression, Motion, LipSync };

struct MotionData {
    std::string group;
    int no = 0;
    int priority = 3;
};

struct ControlCommand {
    CommandType type;
    std::string name;
    MotionData motion;
};

} // namespace desktop