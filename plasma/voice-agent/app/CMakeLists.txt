cmake_minimum_required(VERSION 3.22)
project(RungicVoiceAssistant LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2 DBus)
find_package(LayerShellQt REQUIRED)
find_package(KF6WindowSystem REQUIRED)
find_package(KF6ColorScheme REQUIRED)
find_package(KF6Config REQUIRED)
# The design system (com.rungic.design, package rungic-design) is imported at run time.
qt_standard_project_setup(REQUIRES 6.5)
qt_add_executable(rungic-voice-assistant main.cpp agentclient.cpp agentclient.h overlay.cpp overlay.h)
qt_add_qml_module(rungic-voice-assistant URI com.rungic.voiceassistant VERSION 1.0
    QML_FILES qml/Main.qml qml/ChatPage.qml qml/ChatEntry.qml qml/Composer.qml qml/ConversationDrawer.qml
              qml/SettingsFrame.qml qml/SettingsPage.qml qml/CodexPage.qml qml/KeyPage.qml
              qml/ChatModel.qml qml/AssistantOverlay.qml qml/SuggestionsPage.qml qml/media.js)
target_link_libraries(rungic-voice-assistant PRIVATE Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2 Qt6::DBus
    LayerShellQt::Interface KF6::WindowSystem KF6::ColorScheme KF6::ConfigCore)
install(TARGETS rungic-voice-assistant DESTINATION bin)
install(FILES RungicVoiceAssistant.colors RungicVoiceAssistantLight.colors DESTINATION share/rungic-voice-assistant)
