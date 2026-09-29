# Rungic's design system as a QML module (docs/87): `import com.rungic.design`.
# Tokens (Theme), the system's dark or light (SystemTheme), icons (Icon) and the
# shared controls. Installed into Qt's QML directory, so any Rungic app can use it.
cmake_minimum_required(VERSION 3.22)
project(RungicDesign LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick QuickControls2)
find_package(KF6Config REQUIRED)
qt_standard_project_setup(REQUIRES 6.5)
# QML files live in qml/: each such directory gets its own qmldir.
qt_policy(SET QTP0004 NEW)

set(module_dir "${CMAKE_BINARY_DIR}/qml/com/rungic/design")
set_source_files_properties(qml/Theme.qml PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
file(GLOB icons RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}" CONFIGURE_DEPENDS icons/*.svg)
file(GLOB controls RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}" CONFIGURE_DEPENDS qml/*.qml qml/*.js)
# One plugin library holds the C++ types, the compiled QML and the icons.
qt_add_qml_module(rungicdesign
    URI com.rungic.design
    VERSION 1.0
    PLUGIN_TARGET rungicdesign
    OUTPUT_DIRECTORY "${module_dir}"
    SOURCES systemtheme.cpp systemtheme.h
    QML_FILES ${controls}
    RESOURCES ${icons}   # the sources of qml/icons.js (make-icons.py), for other uses
)
target_link_libraries(rungicdesign PRIVATE Qt6::Core Qt6::Gui Qt6::Qml Qt6::Quick KF6::ConfigCore)

set(install_dir "${QT6_INSTALL_QML}/com/rungic/design")
install(TARGETS rungicdesign LIBRARY DESTINATION "${install_dir}")
install(FILES "${module_dir}/qmldir" "${module_dir}/rungicdesign.qmltypes" DESTINATION "${install_dir}")

# The state gallery: every control in every state, light and dark (docs/87).
qt_add_executable(rungic-design-gallery gallery.cpp)
target_link_libraries(rungic-design-gallery PRIVATE Qt6::Gui Qt6::Qml Qt6::Quick Qt6::QuickControls2)
install(TARGETS rungic-design-gallery DESTINATION bin)
