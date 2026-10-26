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

"""Compare fresh imports with and without the optional wheel initialization."""

import importlib.util
from pathlib import Path
import subprocess
import sys

spec = importlib.util.find_spec("tvm_tirx")
base = Path(spec.origin).parent / "base.py"
original = base.read_text()
hook = '            importlib.import_module("tvm_tirx_llvm_targets")'
assert original.count(hook) == 1
command = [sys.executable, "-I", "-B", "-c", "import tvm_tirx; print('CORE_FIRST_IMPORT_OK')"]
try:
    base.write_text(original.replace(hook, "            pass  # negative control"))
    result = subprocess.run(command, text=True, capture_output=True)
    print("Without optional-package initialization:", result.returncode)
    print(result.stdout)
    print(result.stderr)
    assert result.returncode != 0 and "FileNotFoundError" in result.stderr, result
finally:
    base.write_text(original)
subprocess.run(command, check=True)
print("Restoring only optional-package initialization fixes the fresh Windows import")
