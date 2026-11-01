<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# Windows and macOS build-speed investigation

Measured on November 1, 2026. **Parallel compilation is enabled, but the
MSBuild build has a substantial interval of serial compilation. Most of the
remaining Windows/macOS gap is native C++ compilation throughput; these data
cannot attribute that remaining gap to MSVC alone.**

## Evidence and comparison

The unmodified upstream run at source
[`e45a49da0`](https://github.com/apache/tvm-tirx/commit/e45a49da0bd7141f4c7ba6c6a827ab56f641b022)
reproduces the original observation: [Windows took 31m31s](https://github.com/apache/tvm-tirx/actions/runs/41347179295/job/124969404272)
and [macOS took 14m43s](https://github.com/apache/tvm-tirx/actions/runs/41347179295/job/124969404510).
Their wheel build/install steps took 25m48s and 9m25s, respectively.

The [diagnostic run](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593)
uses [`304241cb4`](https://github.com/tqchen/tvm-tirx/commit/304241cb4bcf98eeb1156e4eb841c51ef35e6ed9),
which adds only diagnostic files to that same source revision. It compares the
existing Windows Visual Studio generator, Ninja with the same MSVC version,
and the existing macOS Ninja/Apple Clang setup. Each job starts without a build
or wheel directory. Dependency-cache restoration is disabled; no compiler cache
is configured. Setup remains separate from native build measurements.

| Measurement | [Windows/MSBuild](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593/job/124972415918) | [Windows/Ninja](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593/job/124972415963) | [macOS/Ninja](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593/job/124972416000) |
|---|---:|---:|---:|
| Dependency preparation | 231 s | 227 s | 89 s |
| CMake configure/generate | 17.1 s | 13.1 s | 7.6 s |
| **Native build** | **1995.8 s / 33m16s** | **1754.6 s / 29m15s** | **468.4 s / 7m48s** |
| Wheel staging and packaging | 9.8 s | 10.5 s | 7.5 s |
| Whole wheel command, including startup/finalization | 2029.4 s | 1785.0 s | 486.8 s |
| Mean sampled system CPU during native build | 82.5% | 99.7% | 99.5% |
| Minimum available RAM during native build | 10.22 GiB | 11.19 GiB | 2.69 GiB |
| Reported physical cores / logical CPUs | 2 / 4 | 2 / 4 | 3 / 3 |
| CPU | AMD EPYC 7763 | AMD EPYC 7763 | Apple M1 (Virtual) |
| RAM | approximately 16 GiB | approximately 16 GiB | 7 GiB |

Both Windows jobs use MSVC 19.51.36260.0 and Release `/O2 /Ob2 /DNDEBUG`.
macOS uses Apple Clang 21.0.0, arm64, Release `-O3 -DNDEBUG`, and enables Metal.
All three use CMake 4.4.4 and the same pinned FFI submodule and SDK requirements.
The Windows runner images differ: MSBuild `20261021.278.1`, Ninja
`20261030.294.1`. The physical-core counts are the topology reported by the VMs.

## Parallelism is enabled, but MSBuild does not keep it effective throughout

- The Windows workflow requests `CMAKE_BUILD_PARALLEL_LEVEL=4`. The process
  samples directly observed MSBuild `/m:4`, and generated project metadata has
  `MultiProcessorCompilation=true` for the TIRx compiler/runtime object targets.
- MSBuild had a median of four CPU-active `cl` processes, with a peak of nine;
  raw `cl` process count peaked at eleven, including compiler coordinators.
  Thus the two levels of parallelism can also exceed the four logical CPUs.
  Microsoft documents that [project parallelism and `/MP` multiply](https://learn.microsoft.com/en-us/cpp/build/reference/mp-build-with-multiple-processes).
- **From approximately 1203 to 1832 seconds into the wheel command, 97.7% of
  samples showed only one `cl` process.** Mean system CPU in this 10m29s interval
  was 56.0%. The log shows 49 source files compiling in succession before the
  compiler-object target finishes.
- Those 49 files match **exactly** the 49 sources with duplicate basenames in
  the 183-source `tvm_tirx_compiler_objs` target: for example `expr.cc`, `ir.cc`,
  `stmt.cc`, and eleven `target_kind.cc` files. This is a specific scheduling
  problem despite the global parallel settings.

The likely mechanism is per-file object-name batching. CMake 4.4.4
[marks basename collisions for explicit object names](https://github.com/Kitware/CMake/blob/v4.4.4/Source/cmLocalVisualStudioGenerator.cxx#L40)
and [emits per-source `ObjectFileName` metadata](https://github.com/Kitware/CMake/blob/v4.4.4/Source/cmVisualStudio10TargetGenerator.cxx#L2756).
MSBuild [batches items by distinct metadata values](https://learn.microsoft.com/en-us/visualstudio/msbuild/walkthrough-using-msbuild?view=vs-2019).
The exact filename match and observed serial interval strongly support this
explanation. The run saved project-level flags, not each per-source object-name
entry, so the mechanism is an inference rather than a direct capture of the
individual CL task inputs.

The FFI object project also lacks `MultiProcessorCompilation=true`; its own
MSVC helper adds `/Zi` and `/bigobj`, but not `/MP`. Its project duration was
431.7 s, overlapping the much longer 1809.4 s compiler-object project. These
project times overlap and must not be added as wall time.

Ninja avoids the observed long serial tail: its log shows four concurrent
commands on Windows and three on macOS. Both used about 98.7% of their available
command-slot time. Windows `cl` process counts and CPU-active counts both had
median and maximum four. Memory capacity was not close to exhausted.

## The remaining gap is mostly compilation, not linking or packaging

MSBuild's task summary reports 2468.1 aggregate seconds in CL tasks versus
10.4 seconds in link tasks and 35.8 seconds in custom-build tasks. These are
aggregate task durations, not a decomposition of wall time.

Ninja records 6857.7 aggregate compile-task seconds on Windows, versus 67.5
seconds in all link/custom commands. The same 241 source tasks total 1338.9
seconds on macOS; the median Windows/macOS per-task duration ratio is 5.05.
Examples from the same-source Ninja runs:

| Compile task | Windows/MSVC | macOS/Apple Clang |
|---|---:|---:|
| `src/sym/rewrite_simplify.cc` | 110.3 s | 20.5 s |
| `src/ir/prim/expr.cc` | 109.9 s | 16.5 s |
| `src/ir/stmt.cc` | 103.7 s | 12.1 s |

Windows Ninja spent at least 6129.7 sampled CPU-seconds in `cl`, accounting for
at least 87% of its four-logical-CPU native-build budget. This supports a C++
compilation-throughput bottleneck even after the scheduling issue is removed.
However, CPU microarchitecture, physical-core count, SMT, operating system,
compiler and platform code paths all differ from macOS. **This experiment does
not establish that MSVC alone causes the remaining slowdown.**

## What the measurements justify next

Ninja is a plausible way to remove the observed serial batching and enforce
one global compilation limit. It was 12.1% faster than MSBuild in this trial,
but a stable speedup is not established: runner images differ, there is only
one diagnostic trial per configuration, and the unmodified same-source
MSBuild native build took 1513.2 s, faster than either diagnostic Windows build.
A repeat on a fixed Windows runner/image is warranted before a production
configuration change. Increasing the parallel setting alone is not justified:
MSBuild already oversubscribes at times, while Ninja already saturates the CPUs.

To distinguish MSVC cost from the Windows hardware/platform cost, the next
separate experiment would compare MSVC and clang-cl on the same Windows
hardware, with matched Release settings, SDKs, source and clean object caches.
The present branch makes no compiler replacement or production CI change.

## Measurement limits and retained artifacts

Sampling was requested every two seconds; actual mean intervals were about
2.40 s (MSBuild), 2.46 s (Windows Ninja), and 2.09 s (macOS). Short-lived
processes can escape sampling, so per-process CPU totals are lower bounds.
System CPU includes activity outside the build. Windows pagefile usage is not
a measurement of active paging. Counts of compiler drivers are not counts of
busy cores. Phase markers and Ninja intervals provide the separate wall-time
and scheduling evidence.

The sampler consumed 6.83, 5.08, and 1.61 CPU-seconds respectively, each below
0.35% of one CPU averaged over the wheel command. No environment dump or MSBuild
binary log was collected. The three Actions artifacts contain `machine.json`,
`result.json`, timestamped build logs, resource samples, and Ninja logs where
applicable:

- [Windows/MSBuild measurements](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593/artifacts/13101642343)
- [Windows/Ninja measurements](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593/artifacts/13100509267)
- [macOS/Ninja measurements](https://github.com/tqchen/tvm-tirx/actions/runs/41348181593/artifacts/13099974683)

Artifacts have 30-day retention; the measurements and source/run references in
this report remain committed on `windows-build-speed-909`.
