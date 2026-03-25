cmake_minimum_required(VERSION 3.16)
project(p4_core_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(p4_core_cpp STATIC
  src/p4_core_cpp.cpp
)

target_include_directories(p4_core_cpp PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_definitions(p4_core_cpp PRIVATE
  P4_NATIVE_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/../../native/p4_core"
  P4_ONIONRELAY_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/../../onionrelay"
)

if(UNIX AND NOT APPLE)
  target_link_libraries(p4_core_cpp PRIVATE dl)
endif()

add_executable(p4_core_cpp_example example.cpp)
target_link_libraries(p4_core_cpp_example PRIVATE p4_core_cpp)

add_custom_command(TARGET p4_core_cpp_example POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:p4_core_cpp_example>/native/p4_core
  COMMAND ${CMAKE_COMMAND} -E copy_directory
          ${CMAKE_CURRENT_SOURCE_DIR}/../../native/p4_core
          $<TARGET_FILE_DIR:p4_core_cpp_example>/native/p4_core
)

