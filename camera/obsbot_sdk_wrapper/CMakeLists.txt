cmake_minimum_required(VERSION 3.16)

project(obsbot_c_api LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_CURRENT_LIST_DIR}/../bin")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_LIST_DIR}/../bin")

set(SDK_ROOT "${CMAKE_CURRENT_LIST_DIR}/../sdk/libdev_v2.1.0_8")
set(SDK_INCLUDE_DIR "${SDK_ROOT}/include")
set(SDK_LIB_DIR "${SDK_ROOT}/windows/win64-release")

add_library(obsbot_c_api SHARED obsbot_c_api.cpp)
target_compile_definitions(obsbot_c_api PRIVATE OBSBOT_C_API_EXPORTS UNICODE _UNICODE)
target_include_directories(obsbot_c_api PRIVATE "${SDK_INCLUDE_DIR}")
target_link_directories(obsbot_c_api PRIVATE "${SDK_LIB_DIR}")
target_link_libraries(obsbot_c_api PRIVATE libdev w32-pthreads)

if (MSVC)
    target_compile_options(obsbot_c_api PRIVATE /utf-8 /wd4996 /wd4251 /wd4275)
endif()

add_custom_command(TARGET obsbot_c_api POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${SDK_LIB_DIR}/libdev.dll"
        "$<TARGET_FILE_DIR:obsbot_c_api>/libdev.dll"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${SDK_LIB_DIR}/w32-pthreads.dll"
        "$<TARGET_FILE_DIR:obsbot_c_api>/w32-pthreads.dll")
