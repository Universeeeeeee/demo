cmake_minimum_required(VERSION 3.16)

project(dshow_probe LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_LIST_DIR}/../bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_LIST_DIR}/../bin")

add_executable(dshow_probe dshow_probe.cpp)
add_executable(dshow_capture_probe dshow_capture_probe.cpp)
add_library(tinyse_capture SHARED tinyse_capture.cpp tinyse_capture.h)
add_library(tinyse_capture_v2 SHARED tinyse_capture.cpp tinyse_capture.h)

if (MSVC)
    target_compile_options(dshow_probe PRIVATE /utf-8 /W3)
    target_compile_options(dshow_capture_probe PRIVATE /utf-8 /W3)
    target_compile_options(tinyse_capture PRIVATE /utf-8 /W3)
    target_compile_options(tinyse_capture_v2 PRIVATE /utf-8 /W3)
endif()

target_link_libraries(dshow_probe PRIVATE strmiids ole32 oleaut32 uuid)
target_link_libraries(dshow_capture_probe PRIVATE strmiids ole32 oleaut32 uuid)
target_link_libraries(tinyse_capture PRIVATE strmiids ole32 oleaut32 uuid)
target_link_libraries(tinyse_capture_v2 PRIVATE strmiids ole32 oleaut32 uuid)
