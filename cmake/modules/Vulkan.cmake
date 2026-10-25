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

find_vulkan(${TVM_TIRX_USE_VULKAN})

if(TVM_TIRX_USE_VULKAN)
  if(NOT Vulkan_FOUND)
    message(FATAL_ERROR "Cannot find Vulkan, TVM_TIRX_USE_VULKAN=" ${TVM_TIRX_USE_VULKAN})
  endif()
  message(STATUS "Build vulkan device runtime")

  file(GLOB RUNTIME_VULKAN_SRCS CONFIGURE_DEPENDS src/backend/vulkan/runtime/*.cc)

  add_library(tvm_runtime_vulkan_objs OBJECT ${RUNTIME_VULKAN_SRCS})
  target_link_libraries(tvm_runtime_vulkan_objs PUBLIC tvm_tirx_header)
  target_include_directories(tvm_runtime_vulkan_objs SYSTEM PRIVATE ${Vulkan_INCLUDE_DIRS})
  set_target_properties(tvm_runtime_vulkan_objs PROPERTIES POSITION_INDEPENDENT_CODE ON)
  add_library(tvm_runtime_vulkan SHARED $<TARGET_OBJECTS:tvm_runtime_vulkan_objs>)
  install(TARGETS tvm_runtime_vulkan DESTINATION ${CMAKE_INSTALL_LIBDIR} COMPONENT tvm_tirx)
  list(APPEND TVM_RUNTIME_BACKEND_LIBS tvm_runtime_vulkan)
  target_link_libraries(tvm_runtime_vulkan PUBLIC tvm_runtime PRIVATE ${Vulkan_LIBRARY})
  tvm_tirx_configure_target(tvm_runtime_vulkan_objs)
  tvm_tirx_configure_target(tvm_runtime_vulkan)
endif(TVM_TIRX_USE_VULKAN)
