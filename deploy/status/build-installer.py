#!/usr/bin/env python3
"""Writes install-status-pipeline.sh: installer-template.sh with gen-pipeline.js inside it, as base64."""

import base64
import hashlib
import textwrap
from pathlib import Path

HERE = Path(__file__).parent
generator = (HERE / "gen-pipeline.js").read_bytes().replace(b"\r\n", b"\n")
encoded = "\n".join(textwrap.wrap(base64.b64encode(generator).decode("ascii"), 100))
template = (HERE / "installer-template.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
output = template.replace("@@GENERATOR_B64@@", encoded).replace("@@GENERATOR_SHA256@@", hashlib.sha256(generator).hexdigest())
(HERE / "install-status-pipeline.sh").write_text(output, encoding="utf-8", newline="\n")
print(f"install-status-pipeline.sh: {len(output)} bytes, generator sha256 {hashlib.sha256(generator).hexdigest()}")
