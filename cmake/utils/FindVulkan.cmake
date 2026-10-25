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

#######################################################
# Enhanced version of find Vulkan.
#
# Usage:
#   find_vulkan(${USE_VULKAN})
#
# - When USE_VULKAN=ON, use auto search
# - When USE_VULKAN=/path/to/vulkan-sdk-path, use the sdk
#
# Provide variables:
#
# - Vulkan_FOUND
# - Vulkan_INCLUDE_DIRS
# - Vulkan_LIBRARY
#

macro(find_vulkan use_vulkan)
  set(__use_vulkan ${use_vulkan})
  if(IS_DIRECTORY ${__use_vulkan})
    set(__vulkan_sdk ${__use_vulkan})
    message(STATUS "Custom Vulkan SDK PATH=" ${__use_vulkan})
  elseif(IS_DIRECTORY $ENV{VULKAN_SDK})
    set(__vulkan_sdk $ENV{VULKAN_SDK})
  else()
    set(__vulkan_sdk "")
  endif()


  if(CMAKE_SYSTEM_NAME STREQUAL "Android")
    set(VULKAN_NDK_SRC ${CMAKE_ANDROID_NDK}/sources/third_party/vulkan/src)
    set(Vulkan_INCLUDE_DIRS ${VULKAN_NDK_SRC}/include)
    set(Vulkan_FOUND TRUE)
    message(STATUS "Android Vulkan_INCLUDE_DIRS=" ${Vulkan_INCLUDE_DIRS})
    message(STATUS "Skip finding SPIRV in Android, make sure you only build tvm runtime.")
    return()
  endif()

  if(__vulkan_sdk)
    set(Vulkan_INCLUDE_DIRS ${__vulkan_sdk}/include)
    find_library(Vulkan_LIBRARY NAMES vulkan vulkan-1 PATHS ${__vulkan_sdk}/lib)
    if(Vulkan_LIBRARY)
      set(Vulkan_FOUND TRUE)
    endif()
  endif(__vulkan_sdk)

  # resort to find vulkan of option is on
  if(NOT Vulkan_FOUND)
    if(${__use_vulkan} MATCHES ${IS_TRUE_PATTERN})
      find_package(Vulkan QUIET)
    endif()
  endif()

  if(Vulkan_FOUND)
    message(STATUS "Vulkan_INCLUDE_DIRS=" ${Vulkan_INCLUDE_DIRS})
    message(STATUS "Vulkan_LIBRARY=" ${Vulkan_LIBRARY})
  endif()
endmacro(find_vulkan)
