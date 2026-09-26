# SPDX-License-Identifier: GPL-2.0-or-later
# The recording quick setting's QML module (com.rungic.quicksetting.record, docs/73): a quick
# setting package of its own, loaded by Plasma Mobile's shell like any other; plasma-mobile's own
# recording tile is left unchanged and hidden (rungic-recording-quicksetting.sh).
cmake_minimum_required(VERSION 3.22)
# C: the protocol code qt6_generate_wayland_protocol_client_sources writes is C.
project(RungicRecording LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
find_package(ECM REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
set(QT_MAJOR_VERSION 6)
find_package(Qt6 REQUIRED COMPONENTS Core Gui GuiPrivate Qml Quick WaylandClient)
include(KDEInstallDirs6)
include(KDECMakeSettings)
include(ECMQmlModule)
find_package(KF6 REQUIRED COMPONENTS CoreAddons I18n Notifications)
find_package(PlasmaWaylandProtocols REQUIRED)

ecm_add_qml_module(rungicrecordplugin URI "com.rungic.quicksetting.record" GENERATE_PLUGIN_SOURCE)
target_sources(rungicrecordplugin PRIVATE recordutil.cpp recordutil.h screenstream.cpp screenstream.h)
qt6_generate_wayland_protocol_client_sources(rungicrecordplugin FILES
    ${PLASMA_WAYLAND_PROTOCOLS_DIR}/zkde-screencast-unstable-v1.xml)
target_link_libraries(rungicrecordplugin PRIVATE Qt::Core Qt::Gui Qt::GuiPrivate Qt::WaylandClient Qt::Qml Qt::Quick
    KF6::CoreAddons KF6::I18n KF6::Notifications)
ecm_finalize_qml_module(rungicrecordplugin)
