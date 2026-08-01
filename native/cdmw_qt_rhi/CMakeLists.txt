cmake_minimum_required(VERSION 3.21)
project(CdmwQtRhi LANGUAGES CXX)

# The Mesh Editor viewport renders as a node inside Qt Quick's scene graph
# rather than as an embedded child window. That needs QRhi, which lives in Qt's
# GuiPrivate module, and private modules carry no binary-compatibility promise:
# this plugin is only valid against the exact Qt build that loads it, which is
# the Qt inside the installed PySide6 wheel.
#
# scripts/vendor_qt_sdk.py fetches that exact version into third_party/qt, so
# configure with:
#   -DCMAKE_PREFIX_PATH=<repo>/third_party/qt/<version>/<arch>
# and the two can never drift apart silently.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# Qt warns that private-module headers tie a build to one Qt version. That is
# precisely why this plugin is version-pinned, and the guard below enforces the
# pin, so the warning has nothing left to tell us. Set before find_package or
# it is read too late to take effect.
set(QT_NO_PRIVATE_MODULE_WARNING ON)

find_package(Qt6 6.7 REQUIRED COMPONENTS Core Gui GuiPrivate Quick Qml ShaderTools)

if(NOT DEFINED CDMW_EXPECTED_QT_VERSION)
    set(CDMW_EXPECTED_QT_VERSION "" CACHE STRING
        "Qt version PySide6 ships; the build fails if the SDK does not match.")
endif()
if(CDMW_EXPECTED_QT_VERSION AND NOT Qt6_VERSION VERSION_EQUAL CDMW_EXPECTED_QT_VERSION)
    message(FATAL_ERROR
        "Qt ${Qt6_VERSION} was found but PySide6 ships ${CDMW_EXPECTED_QT_VERSION}. "
        "A QRhi plugin built against a different Qt may crash at any arbitrary "
        "point. Run scripts/vendor_qt_sdk.py and point CMAKE_PREFIX_PATH at it.")
endif()

qt_standard_project_setup(REQUIRES 6.7)

qt_add_qml_module(cdmwqtrhi
    URI CdmwQtRhi
    VERSION 1.0
    PLUGIN_TARGET cdmwqtrhi
    OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/qml/CdmwQtRhi
    SOURCES
        rhitriangle.h
        rhitriangle.cpp
)

qt6_add_shaders(cdmwqtrhi "cdmwqtrhi_shaders"
    BATCHABLE
    PRECOMPILE
    PREFIX "/shaders"
    FILES
        tri.vert
        tri.frag
    OUTPUTS
        tri.vert.qsb
        tri.frag.qsb
)

target_link_libraries(cdmwqtrhi PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::GuiPrivate
    Qt6::Quick
    Qt6::Qml
)
