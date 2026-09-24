cmake_minimum_required(VERSION 3.22)
# C: the protocol code qt6_generate_wayland_protocol_client_sources writes is C.
project(MotoAgentScreen LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick WaylandClient)
find_package(LayerShellQt REQUIRED)
qt_standard_project_setup(REQUIRES 6.5)
set(PROTOCOLS /usr/share/plasma-wayland-protocols)
qt_add_executable(moto-agent-screen-window main.cpp agentscreen.cpp agentscreen.h floater.cpp floater.h)
qt6_generate_wayland_protocol_client_sources(moto-agent-screen-window FILES
    ${PROTOCOLS}/zkde-screencast-unstable-v1.xml ${PROTOCOLS}/fake-input.xml)
qt_add_qml_module(moto-agent-screen-window URI dev.moto.agentscreen VERSION 1.0 QML_FILES qml/Main.qml)
target_link_libraries(moto-agent-screen-window PRIVATE Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::WaylandClient
    LayerShellQt::Interface)
install(TARGETS moto-agent-screen-window DESTINATION libexec)
