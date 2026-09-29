# An agent workspace's helpers (docs/research/91): input into its own KWin, its picture for the floating window, its background.
cmake_minimum_required(VERSION 3.22)
# C: the protocol code qt6_generate_wayland_protocol_client_sources writes is C.
project(RungicWorkspace LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui WaylandClient)
find_package(LayerShellQt REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(XKB REQUIRED IMPORTED_TARGET xkbcommon)
qt_standard_project_setup(REQUIRES 6.5)
# The protocols' code, generated once for both helpers.
add_library(rungic-workspace-protocols STATIC)
qt6_generate_wayland_protocol_client_sources(rungic-workspace-protocols FILES
    /usr/share/plasma-wayland-protocols/fake-input.xml
    /usr/share/plasma-wayland-protocols/zkde-screencast-unstable-v1.xml)
target_link_libraries(rungic-workspace-protocols PUBLIC Qt6::Core Qt6::Gui Qt6::WaylandClient)
target_include_directories(rungic-workspace-protocols PUBLIC ${CMAKE_CURRENT_BINARY_DIR})
qt_add_executable(rungic-workspace-input input.cpp)
target_link_libraries(rungic-workspace-input PRIVATE rungic-workspace-protocols PkgConfig::XKB)
qt_add_executable(rungic-workspace-stream stream.cpp)
target_link_libraries(rungic-workspace-stream PRIVATE rungic-workspace-protocols)
qt_add_executable(rungic-workspace-desktop desktop.cpp)
target_link_libraries(rungic-workspace-desktop PRIVATE Qt6::Gui LayerShellQt::Interface)
install(TARGETS rungic-workspace-input rungic-workspace-stream rungic-workspace-desktop DESTINATION libexec)
install(FILES com.rungic.WorkspaceInput.desktop com.rungic.WorkspaceStream.desktop DESTINATION share/applications)
install(PROGRAMS rungic-workspace rungic-workspace-env rungic-user DESTINATION bin)
install(FILES rungic-workspace@.service DESTINATION lib/systemd/user)
install(FILES defaults/kwinrc DESTINATION share/rungic-workspace/defaults)
