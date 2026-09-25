cmake_minimum_required(VERSION 3.22)
project(MotoVoiceAssistant LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2 DBus ShaderTools)
find_package(LayerShellQt REQUIRED)
find_package(KF6WindowSystem REQUIRED)
qt_standard_project_setup(REQUIRES 6.5)
qt_add_executable(moto-voice-assistant main.cpp agentclient.cpp agentclient.h overlay.cpp overlay.h)
qt_add_qml_module(moto-voice-assistant URI dev.moto.voiceassistant VERSION 1.0
    QML_FILES qml/Main.qml qml/ConversationsPage.qml qml/ChatPage.qml qml/ChatItem.qml qml/TalkButton.qml
              qml/ChatModel.qml qml/AssistantOverlay.qml qml/OverlayItem.qml qml/Bloom.qml qml/LightPill.qml qml/GlowLabel.qml)
# The overlay's light (docs/67).
qt_add_shaders(moto-voice-assistant "overlay-shaders" PREFIX "/"
    FILES shaders/bloom.frag shaders/pill.frag shaders/glowtext.frag)
target_link_libraries(moto-voice-assistant PRIVATE Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2 Qt6::DBus
    LayerShellQt::Interface KF6::WindowSystem)
install(TARGETS moto-voice-assistant DESTINATION bin)
