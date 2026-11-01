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


"""Tests for diagnostics whose correctness affects the timing conclusions."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "build_speed", Path(__file__).with_name("build_speed.py")
)
measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure)


def test_ninja_multi_output_and_overlap(tmp_path):
    log = tmp_path / "ninja.log"
    log.write_text(
        "# ninja log v5\n"
        "0\t1000\t0\ta.obj\taa\n"
        "0\t1000\t0\ta.dep\taa\n"
        "500\t1500\t0\tb.obj\tbb\n"
        "1500\t2000\t0\tlib.dll\tcc\n"
    )
    result = measure.ninja_summary(log)
    assert result["commands"] == 3
    assert result["peak_concurrent_commands"] == 2
    assert result["summed_task_seconds"] == {"compile": 2, "link_or_custom": 0.5}


def test_real_child_sampling_and_exit_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("diagnostics").mkdir()
    command = [
        sys.executable,
        "-c",
        (
            "import time, sys; print('*** Configuring CMake...', flush=True); "
            "time.sleep(.3); print('*** Building project with Ninja...', flush=True); "
            "deadline=time.monotonic()+.5; "
            "exec('while time.monotonic() < deadline: pass'); "
            "print('*** Installing project into wheel...', flush=True); sys.exit(7)"
        ),
    ]
    result = measure.measured_build(command, os.environ.copy(), interval=0.05)
    assert result["returncode"] == 7
    assert result["phase_seconds"]["native_build"] == pytest.approx(0.5, abs=0.15)
    assert result["sampler_cpu_seconds"] < result["wall_seconds"]
    samples = [
        json.loads(line) for line in Path("diagnostics/samples.jsonl").read_text().splitlines()
    ]
    # The root launcher is intentionally excluded; only descendant tools count.
    assert all(not s["tools"] for s in samples)


def test_descendant_cpu_and_flags_without_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("diagnostics").mkdir()
    child = "import time; end=time.monotonic()+.5; exec('while time.monotonic()<end: pass')"
    parent = f"import subprocess,sys; subprocess.run([sys.executable,'-c',{child!r}])"
    measure.measured_build([sys.executable, "-c", parent], os.environ.copy(), interval=0.05)
    samples = [
        json.loads(line) for line in Path("diagnostics/samples.jsonl").read_text().splitlines()
    ]
    assert any(sum(g["active"] for g in s["tools"].values()) for s in samples)
    assert sum(g["cpu_seconds"] for s in samples for g in s["tools"].values()) > 0.1
    assert all(
        set(g) == {"count", "active", "cpu_seconds", "rss"}
        for s in samples
        for g in s["tools"].values()
    )
