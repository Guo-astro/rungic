# An agent workspace's helpers (docs/research/91): input into its own KWin, its picture for the floating window, its background,
# and its keeper (its apps frozen while nobody uses it, the workspace closed after long).
cmake_minimum_required(VERSION 3.22)
# C: the protocol code qt6_generate_wayland_protocol_client_sources writes is C.
project(RungicWorkspace LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui WaylandClient DBus Network)
find_package(LayerShellQt REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(XKB REQUIRED IMPORTED_TARGET xkbcommon)
pkg_check_modules(WAYLAND_CLIENT REQUIRED IMPORTED_TARGET wayland-client)
pkg_get_variable(WAYLAND_PROTOCOLS wayland-protocols pkgdatadir)
qt_standard_project_setup(REQUIRES 6.5)
# The protocols' code, generated once for both helpers.
add_library(rungic-workspace-protocols STATIC)
qt6_generate_wayland_protocol_client_sources(rungic-workspace-protocols FILES
    /usr/share/plasma-wayland-protocols/fake-input.xml
    /usr/share/plasma-wayland-protocols/zkde-screencast-unstable-v1.xml
    ${WAYLAND_PROTOCOLS}/staging/ext-idle-notify/ext-idle-notify-v1.xml)
target_link_libraries(rungic-workspace-protocols PUBLIC Qt6::Core Qt6::Gui Qt6::WaylandClient)
target_include_directories(rungic-workspace-protocols PUBLIC ${CMAKE_CURRENT_BINARY_DIR})
qt_add_executable(rungic-workspace-input input.cpp)
target_link_libraries(rungic-workspace-input PRIVATE rungic-workspace-protocols PkgConfig::XKB)
qt_add_executable(rungic-workspace-stream stream.cpp)
target_link_libraries(rungic-workspace-stream PRIVATE rungic-workspace-protocols Qt6::DBus)
qt_add_executable(rungic-workspace-desktop desktop.cpp)
target_link_libraries(rungic-workspace-desktop PRIVATE Qt6::Gui LayerShellQt::Interface)
# The picture on the Android host (present.cpp): KPipeWire for the frames, EGL/GLES for the copy into
# leased buffers, a plain Wayland client for the host.
find_package(KPipeWire REQUIRED)
pkg_check_modules(EGL REQUIRED IMPORTED_TARGET egl glesv2 libdrm)
find_program(WAYLAND_SCANNER wayland-scanner REQUIRED)
set(PRESENT_PROTOCOLS
    stable/xdg-shell/xdg-shell
    unstable/linux-dmabuf/linux-dmabuf-unstable-v1
    unstable/linux-explicit-synchronization/linux-explicit-synchronization-unstable-v1)
set(PRESENT_PROTOCOL_SOURCES)
foreach(protocol ${PRESENT_PROTOCOLS})
    get_filename_component(name ${protocol} NAME)
    add_custom_command(OUTPUT ${name}-client-protocol.h ${name}-protocol.c
        COMMAND ${WAYLAND_SCANNER} client-header ${WAYLAND_PROTOCOLS}/${protocol}.xml ${name}-client-protocol.h
        COMMAND ${WAYLAND_SCANNER} private-code ${WAYLAND_PROTOCOLS}/${protocol}.xml ${name}-protocol.c
        DEPENDS ${WAYLAND_PROTOCOLS}/${protocol}.xml)
    list(APPEND PRESENT_PROTOCOL_SOURCES ${CMAKE_CURRENT_BINARY_DIR}/${name}-client-protocol.h ${CMAKE_CURRENT_BINARY_DIR}/${name}-protocol.c)
endforeach()
qt_add_executable(rungic-workspace-present present.cpp ${PRESENT_PROTOCOL_SOURCES})
target_include_directories(rungic-workspace-present PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(rungic-workspace-present PRIVATE Qt6::Gui K::KPipeWire PkgConfig::EGL PkgConfig::WAYLAND_CLIENT)
qt_add_executable(rungic-workspace-keeper keeper.cpp)
target_link_libraries(rungic-workspace-keeper PRIVATE rungic-workspace-protocols Qt6::DBus Qt6::Network PkgConfig::WAYLAND_CLIENT)
install(TARGETS rungic-workspace-input rungic-workspace-stream rungic-workspace-desktop rungic-workspace-keeper rungic-workspace-present DESTINATION libexec)
install(FILES com.rungic.WorkspaceInput.desktop com.rungic.WorkspaceStream.desktop DESTINATION share/applications)
install(PROGRAMS rungic-workspace rungic-workspace-env rungic-workspace-sound rungic-user rungic-remote
    rungic-bus-forward rungic-desktop-dirs DESTINATION bin)
install(FILES rungic-workspace@.service rungic-remote.service DESTINATION lib/systemd/user)
install(FILES defaults/kwinrc DESTINATION share/rungic-workspace/defaults)
install(PROGRAMS rungic-workspace-a11y rungic-agent-wakelock DESTINATION libexec)
install(FILES rungic-agent-wakelock.service DESTINATION lib/systemd/system)
install(FILES dbus/session.conf dbus/desktop.conf DESTINATION share/rungic-workspace/dbus-1)
install(FILES dbus/org.a11y.Bus.service DESTINATION share/rungic-workspace/dbus-1/services)
file(GLOB DESKTOP_BUS_SERVICES dbus/desktop-services/*.service)
install(FILES ${DESKTOP_BUS_SERVICES} DESTINATION share/rungic-workspace/dbus-1/desktop-services)
