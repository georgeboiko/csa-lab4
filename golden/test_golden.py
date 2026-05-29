import contextlib
import io
import json
import logging
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from machine import main as machine_main
from translator import main as translator_main


@pytest.mark.golden_test("*.yml")
def test_golden(golden, caplog):
    caplog.set_level(logging.DEBUG)

    with tempfile.TemporaryDirectory() as tmpdir:
        source_file = os.path.join(tmpdir, "source.fth")
        input_file = os.path.join(tmpdir, "input.json")
        target_file = os.path.join(tmpdir, "target.bin")
        memory_file = os.path.join(tmpdir, "memory.bin")

        with open(source_file, "w", encoding="utf-8") as f:
            f.write(golden["source"])

        with open(input_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(golden.get("input", [])))

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            translator_main(source_file, target_file, memory_file)

        translator_output = stdout.getvalue()

        with (
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            machine_main(target_file, memory_file, input_file)

        machine_output = stdout.getvalue()
        machine_err = stderr.getvalue()

        # Filter log to avoid huge files, maybe just keep the first 100 and last 100 lines
        log_lines = caplog.text.splitlines()
        if len(log_lines) > 200:
            log_text = "\n".join([*log_lines[:100], "...", *log_lines[-100:]])

        else:
            log_text = "\n".join(log_lines)

        assert golden.out["translator_output"] == translator_output
        assert golden.out["machine_output"] == machine_output
        assert golden.out["machine_err"] == machine_err
        assert golden.out["log"] == log_text
