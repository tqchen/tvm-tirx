# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# SPIR-V code generation needs headers and SPIRV-Tools, but no Vulkan loader.
include(FetchContent)
FetchContent_Declare(tvm_spirv_headers
  URL https://github.com/KhronosGroup/SPIRV-Headers/archive/09913f088a1197aba4aefd300a876b2ebbaa3391.tar.gz
  URL_HASH SHA256=6d4aad5a86d7d5af144747aee1d616f624897d64d842f282aca7777f84244318
  SOURCE_SUBDIR headers-only)
find_path(TVM_SPIRV_HEADERS_DIR spirv.hpp
  HINTS "${TVM_TIRX_USE_KHRONOS_SPIRV}" ENV VULKAN_SDK
  PATH_SUFFIXES include/spirv/unified1 include/SPIRV)
if(NOT TVM_SPIRV_HEADERS_DIR)
  FetchContent_MakeAvailable(tvm_spirv_headers)
  set(TVM_SPIRV_HEADERS_DIR "${tvm_spirv_headers_SOURCE_DIR}/include/spirv/unified1")
endif()
find_path(TVM_VULKAN_HEADERS_DIR vulkan/vulkan_core.h
  HINTS "${TVM_TIRX_USE_VULKAN}" ENV VULKAN_SDK PATH_SUFFIXES include)
if(NOT TVM_VULKAN_HEADERS_DIR)
  FetchContent_Declare(tvm_vulkan_headers
    URL https://github.com/KhronosGroup/Vulkan-Headers/archive/952f776f6573aafbb62ea717d871cd1d6816c387.tar.gz
    URL_HASH SHA256=4c744e80c908bcc65c2057482f44e57d7e3d748f6eae4cd759fd593018f4ce35
    SOURCE_SUBDIR headers-only)
  FetchContent_MakeAvailable(tvm_vulkan_headers)
  set(TVM_VULKAN_HEADERS_DIR "${tvm_vulkan_headers_SOURCE_DIR}/include")
endif()

find_package(SPIRV-Tools CONFIG QUIET
  HINTS "${TVM_TIRX_USE_KHRONOS_SPIRV}" ENV VULKAN_SDK)
if(NOT TARGET SPIRV-Tools-static AND NOT TARGET SPIRV-Tools)
  # Keep the matching SDK 1.4.309 headers beside the source build. Only the
  # validation/disassembly library is linked; tools and tests are not built.
  if(NOT tvm_spirv_headers_SOURCE_DIR)
    FetchContent_MakeAvailable(tvm_spirv_headers)
  endif()
  set(SPIRV-Headers_SOURCE_DIR "${tvm_spirv_headers_SOURCE_DIR}")
  set(TVM_SPIRV_HEADERS_DIR "${tvm_spirv_headers_SOURCE_DIR}/include/spirv/unified1")
  set(SPIRV_SKIP_EXECUTABLES ON)
  set(SPIRV_SKIP_TESTS ON)
  set(SPIRV_TOOLS_BUILD_STATIC ON)
  set(SKIP_SPIRV_TOOLS_INSTALL ON)
  FetchContent_Declare(tvm_spirv_tools
    URL https://github.com/KhronosGroup/SPIRV-Tools/archive/f289d047f49fb60488301ec62bafab85573668cc.tar.gz
    URL_HASH SHA256=5fbd56baf226a04435656bae408287365102b69a24fa73bab8353c5f44b55615
    SOURCE_SUBDIR library-only)
  FetchContent_MakeAvailable(tvm_spirv_tools)
  add_subdirectory("${tvm_spirv_tools_SOURCE_DIR}" "${tvm_spirv_tools_BINARY_DIR}" EXCLUDE_FROM_ALL)
  install(FILES "${tvm_spirv_tools_SOURCE_DIR}/LICENSE" DESTINATION licenses
    RENAME LICENSE-SPIRV-Tools.txt COMPONENT tvm_tirx)
endif()
if(TARGET SPIRV-Tools-static)
  set(TVM_SPIRV_TOOLS_LIBRARY SPIRV-Tools-static)
else()
  set(TVM_SPIRV_TOOLS_LIBRARY SPIRV-Tools)
endif()

add_library(tvm_spirv_header INTERFACE)
target_include_directories(tvm_spirv_header SYSTEM INTERFACE
  "${TVM_SPIRV_HEADERS_DIR}" "${TVM_VULKAN_HEADERS_DIR}")
target_link_libraries(tvm_spirv_header INTERFACE ${TVM_SPIRV_TOOLS_LIBRARY})
target_compile_definitions(tvm_spirv_header INTERFACE TVM_ENABLE_SPIRV=1)
if(TVM_TIRX_USE_SPIRV_KHR_INTEGER_DOT_PRODUCT)
  target_compile_definitions(tvm_spirv_header INTERFACE TVM_SPIRV_KHR_INTEGER_DOT_PRODUCT=1)
endif()
file(GLOB COMPILER_SPIRV_SRCS CONFIGURE_DEPENDS
  src/backend/vulkan/codegen/build_vulkan.cc
  src/backend/vulkan/codegen/codegen_spirv.cc
  src/backend/vulkan/codegen/intrin_rule_spirv.cc
  src/backend/vulkan/codegen/ir_builder.cc
  src/backend/vulkan/codegen/spirv_support.cc
  src/backend/vulkan/codegen/spirv_utils.cc)
list(APPEND COMPILER_SRCS ${COMPILER_SPIRV_SRCS})
list(APPEND TVM_LINKER_LIBS ${TVM_SPIRV_TOOLS_LIBRARY})
