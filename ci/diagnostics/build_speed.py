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

"""Measure a clean wheel build without changing compiler or optimization flags.

System CPU includes all activity. Per-process CPU is a sampled lower bound:
short-lived processes can disappear between samples. Process counts include
compiler drivers, so CPU-active counts are reported separately. No environment
dump, full process command line, or MSBuild binary log is saved.
"""

import collections
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from itertools import pairwise
from pathlib import Path

import psutil

PHASES = {
    "configure": "*** Configuring CMake...",
    "native_build": "*** Building project with ",
    "install": "*** Installing project into wheel...",
    "wheel": "*** Making wheel...",
    "built": "*** Created ",
}
CACHE_KEYS = {
    "CMAKE_GENERATOR",
    "CMAKE_BUILD_TYPE",
    "CMAKE_CONFIGURATION_TYPES",
    "CMAKE_C_COMPILER",
    "CMAKE_CXX_COMPILER",
    "CMAKE_CXX_FLAGS",
    "CMAKE_CXX_FLAGS_RELEASE",
    "CMAKE_CXX_COMPILER_LAUNCHER",
    "CMAKE_C_COMPILER_LAUNCHER",
    "CMAKE_MAKE_PROGRAM",
    "CMAKE_INTERPROCEDURAL_OPTIMIZATION",
    "CMAKE_VS_PLATFORM_TOOLSET",
}


def capture(command):
    return subprocess.check_output(command, text=True, errors="replace").strip()


def machine_info():
    info = {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cores": psutil.cpu_count(logical=False),
        "memory_bytes": psutil.virtual_memory().total,
        "source_commit": capture(["git", "rev-parse", "HEAD"]),
        "submodules": capture(["git", "submodule", "status", "--recursive"]),
        "uv_version": capture(["uv", "--version"]),
        "cmake_version": capture(["cmake", "--version"]).splitlines()[0],
        "ninja_version": capture(["ninja", "--version"]),
        "rust_version": capture(["rustc", "--version"]),
        "runner_image": {k: os.environ.get(k) for k in ("ImageOS", "ImageVersion", "RUNNER_ARCH")},
    }
    if sys.platform == "win32":
        info["cpu_model"] = capture(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor).Name",
            ]
        )
    elif sys.platform == "darwin":
        info["cpu_model"] = capture(["sysctl", "-n", "machdep.cpu.brand_string"])
    return info


def msvc_environment(env):
    """Load the same installed x64 MSVC toolset for Ninja; never log its environment."""
    vswhere = (
        Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    install = capture(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ]
    )
    vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
    # Environment output stays only in memory, never in logs/artifacts.
    raw = capture(f'cmd.exe /d /s /c ""{vcvars}" >nul && set"')
    result = env.copy()
    for line in raw.splitlines():
        if "=" in line and not line.startswith("="):
            key, value = line.split("=", 1)
            # Windows environment names are case-insensitive.
            for old in list(result):
                if old.lower() == key.lower():
                    del result[old]
            result[key] = value
    return result


def ninja_summary(path):
    """Deduplicate multi-output commands; summed task times are not wall time."""
    commands = {}
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) != 5 or line.startswith("#"):
            continue
        start, end, _, output, command_hash = fields
        key = (int(start), int(end), command_hash)
        commands.setdefault(key, []).append(output)
    totals = collections.defaultdict(float)
    events = []
    tasks = []
    for (start, end, _), outputs in commands.items():
        kind = "compile" if any(p.endswith((".o", ".obj")) for p in outputs) else "link_or_custom"
        seconds = (end - start) / 1000
        totals[kind] += seconds
        events.extend(((start, 1), (end, -1)))
        tasks.append({"seconds": seconds, "outputs": outputs})
    active = peak = 0
    for _, delta in sorted(events):
        active += delta
        peak = max(active, peak)
    return {
        "commands": len(commands),
        "peak_concurrent_commands": peak,
        "summed_task_seconds": dict(totals),
        "slowest_commands": sorted(tasks, key=lambda t: t["seconds"], reverse=True)[:20],
    }


def build_configuration():
    result = {"cache": {}, "msvc_projects": {}}
    cache = Path("build/CMakeCache.txt")
    if cache.exists():
        for line in cache.read_text(errors="replace").splitlines():
            match = re.match(r"([^:#]+):[^=]+=(.*)", line)
            if match and (match[1] in CACHE_KEYS or match[1].startswith("TVM_TIRX_")):
                result["cache"][match[1]] = match[2]
    # Only build options, not imported MSBuild properties or environment values.
    for path in Path("build").rglob("*.vcxproj"):
        flags = collections.defaultdict(set)
        for node in ET.parse(path).iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag in {"MultiProcessorCompilation", "Optimization", "AdditionalOptions"}:
                flags[tag].add(node.text or "")
        result["msvc_projects"][str(path)] = {k: sorted(v) for k, v in flags.items()}
    ninja_log = Path("build/.ninja_log")
    if ninja_log.exists():
        result["ninja"] = ninja_summary(ninja_log)
        shutil.copy2(ninja_log, "diagnostics/ninja.log")
    return result


def sample_processes(root, previous, seen_flags, elapsed):
    groups = collections.defaultdict(lambda: {"count": 0, "cpu_seconds": 0, "active": 0, "rss": 0})
    try:
        processes = root.children(recursive=True)
    except psutil.NoSuchProcess:
        processes = []
    current = {}
    for proc in processes:
        try:
            with proc.oneshot():
                name = proc.name().lower().removesuffix(".exe")
                key = (proc.pid, proc.create_time())
                cpu = sum(proc.cpu_times()[:2])
                rss = proc.memory_info().rss
            current[key] = cpu
            # Do not attribute pre-observation CPU to an interval of unknown length.
            delta = max(0, cpu - previous.get(key, cpu))
            group = groups[name]
            group["count"] += 1
            group["active"] += delta >= 0.02
            group["cpu_seconds"] += delta
            group["rss"] += rss
            if name in {"msbuild", "cl"}:
                for arg in proc.cmdline()[1:]:
                    if re.fullmatch(r"(?i)[/-](?:m(?::\d+)?|maxcpucount(?::\d+)?|mp\d*)", arg):
                        seen_flags.add((name, arg))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    previous.clear()
    previous.update(current)
    mem = psutil.virtual_memory()
    return {
        "elapsed": elapsed,
        "system_cpu_percent": psutil.cpu_percent(),
        "available_memory_bytes": mem.available,
        "swap_used_bytes": psutil.swap_memory().used,
        "tools": dict(groups),
    }


def measured_build(command, env, interval=2.0):
    start = time.monotonic()
    phases = {}
    samples = []
    seen_flags = set()
    previous = {}
    sampler_cpu_start = sum(psutil.Process().cpu_times()[:2])
    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    root = psutil.Process(process.pid)

    def output():
        with Path("diagnostics/build.log").open("w", encoding="utf-8") as log:
            for line in process.stdout:
                elapsed = time.monotonic() - start
                log.write(f"{elapsed:.3f}\t{line}")
                print(line, end="", flush=True)
                for phase, marker in PHASES.items():
                    if marker in line:
                        phases.setdefault(phase, elapsed)

    reader = threading.Thread(target=output)
    reader.start()
    psutil.cpu_percent()
    with Path("diagnostics/samples.jsonl").open("w") as out:
        while process.poll() is None:
            time.sleep(interval)
            sample = sample_processes(root, previous, seen_flags, time.monotonic() - start)
            samples.append(sample)
            out.write(json.dumps(sample) + "\n")
            out.flush()
    reader.join()
    elapsed = time.monotonic() - start
    sampler_cpu = sum(psutil.Process().cpu_times()[:2]) - sampler_cpu_start
    ordered = sorted(phases.items(), key=lambda p: p[1])
    durations = {a: phases[b] - t for (a, t), (b, _) in pairwise(ordered)}
    return {
        "returncode": process.returncode,
        "wall_seconds": elapsed,
        "phase_start_seconds": phases,
        "phase_seconds": durations,
        "observed_parallel_flags": sorted(seen_flags),
        "sampler_cpu_seconds": sampler_cpu,
        "sample_interval_seconds": interval,
        "samples": len(samples),
    }


def main():
    if Path("build").exists() or Path("dist").exists():
        raise SystemExit("Expected a fresh checkout without build/ or dist/; refusing a warm build")
    Path("diagnostics").mkdir(exist_ok=True)
    env = os.environ.copy()
    generator = env.get("DIAGNOSTIC_GENERATOR", "default")
    if sys.platform == "win32" and generator == "Ninja":
        env = msvc_environment(env)
    if generator != "default":
        env["CMAKE_GENERATOR"] = generator
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(os.cpu_count())
    env["CMAKE_ARGS"] = "-DTVM_TIRX_BUILD_TESTS=OFF"
    if sys.platform == "darwin":
        env["CMAKE_ARGS"] += " -DTVM_TIRX_USE_METAL=ON"
        env["MACOSX_DEPLOYMENT_TARGET"] = "14.0"
    command = ["uv", "build", "--wheel", "--out-dir", "dist", ".", "-v"]
    if sys.platform == "win32" and generator == "default":
        command.append("-Cbuild.tool-args=/clp:PerformanceSummary")
    info = machine_info()
    info["build_environment"] = {
        k: env.get(k)
        for k in (
            "CMAKE_GENERATOR",
            "CMAKE_BUILD_PARALLEL_LEVEL",
            "CMAKE_ARGS",
            "MACOSX_DEPLOYMENT_TARGET",
        )
    }
    info["label"] = env.get("DIAGNOSTIC_LABEL")
    info["command"] = command
    Path("diagnostics/machine.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2), flush=True)
    result = measured_build(command, env)
    result["configuration"] = build_configuration()
    Path("diagnostics/result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return result["returncode"]


if __name__ == "__main__":
    sys.exit(main())
