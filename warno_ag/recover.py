"""Decompile WITHOUT importing or executing any game module."""
import contextlib
import io
import json
from pathlib import Path
from collections import Counter
from xdis.bytecode import Bytecode
from xdis.op_imports import get_opcode_module
from uncompyle6.main import decompile
from .archives import read_entry
from .storage import safe_child, sha256, write_json
from .xyz import XYZ

OPCODES = get_opcode_module((2, 6))


def code_report(code):
    rows = list(Bytecode(code, OPCODES))
    if any(row.opname.startswith("<") for row in rows):
        raise ValueError("Unknown opcode")
    return {"filename": str(code.co_filename), "name": str(code.co_name),
            "instruction_count": len(rows), "bytecode_size": len(code.co_code),
            "opcodes": dict(Counter(row.opname for row in rows)),
            "nested": [code_report(v) for v in code.co_consts if hasattr(v, "co_code")]}


def recover(index_path, output_root, variant="F0", campaign=None):
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    if index["errors"] or index["conflicts"]:
        raise ValueError("Resolve index errors/conflicts before recovery")
    output_root = Path(output_root).resolve()
    successes, failures = [], []
    for name, layers in index["resources"].items():
        if f"/{variant}/" not in name:
            continue
        # Shared script libraries plus campaign scripts. Exclude effects/sound/etc.
        shared = "/Python/Eugen" in name or "/Python/Defines/" in name or "/Python/defines/" in name
        scenario = "/Map/Scenario/CampagneStrat_" in name
        if not shared and not scenario:
            continue
        if scenario and campaign and f"/{campaign}/" not in name:
            continue
        record = layers[-1]
        try:
            raw = read_entry(record)
            xyz = XYZ.read(raw)
            code = xyz.code()
            metadata = code_report(code)
            destination = safe_child(output_root / "xyz", name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            out, diagnostic = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(diagnostic), contextlib.redirect_stderr(diagnostic):
                decompile(code, bytecode_version=(2, 6), out=out)
            text = out.getvalue()
            empty = metadata["instruction_count"] == 2 and set(metadata["opcodes"]) == {"LOAD_CONST","RETURN_VALUE"}
            if len(text.splitlines()) < 7 and not empty:
                raise ValueError("Decompiler produced only a header")
            if empty:
                text += "\n# Empty module verified from bytecode (LOAD_CONST None; RETURN_VALUE).\n"
            source = safe_child(output_root / "source", name).with_suffix(".py")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(text, encoding="utf-8", newline="\n")
            successes.append({"resource": name, "source": str(source), "origin": record,
                              "xyz_sha256": sha256(raw), "payload_sha256": sha256(xyz.payload),
                              "source_sha256": sha256(text.encode()), "opaque_header": xyz.opaque_header.hex(),
                              "compression": xyz.compression,
                              "code": metadata, "diagnostic": diagnostic.getvalue()[-2000:]})
        except Exception as exc:
            failures.append({"resource": name, "origin": record, "error": f"{type(exc).__name__}: {exc}"})
        if (len(successes) + len(failures)) % 50 == 0:
            print(f"Recovered {len(successes)}; failed {len(failures)}", flush=True)
    result = {"schema": 1, "mode": "offline; decompiler output not presumed source-equivalent",
              "variant": variant, "successes": successes, "failures": failures}
    write_json(output_root / "recovery.json", result)
    print(f"Recovery: {len(successes)} sources, {len(failures)} failures")
    return result
