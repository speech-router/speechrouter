#!/usr/bin/env python3
"""Generate typed provider-params for both SDKs from providers/*/params.json.

One source of truth: the same files that render the docs' provider option
tables. Regenerate with:  python3 scripts/gen_provider_params.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = ROOT / "gateway/speechrouter_gateway/providers"
TS_OUT = ROOT / "packages/sdk-ts/src/providerParams.ts"
PY_OUT = ROOT / "packages/sdk-python/speechrouter/provider_params.py"

TS_TYPES = {"number": "number", "integer": "number", "boolean": "boolean",
            "string": "string", "array": "unknown[]", "object": "Record<string, unknown>"}
PY_TYPES = {"number": "float", "integer": "int", "boolean": "bool",
            "string": "str", "array": "list", "object": "dict"}


def ts_type(p):
    if "enum" in p:
        return " | ".join(f"'{v}'" for v in p["enum"])
    return TS_TYPES[p["type"]]


def py_type(p):
    if "enum" in p:
        return "Literal[" + ", ".join(f'"{v}"' for v in p["enum"]) + "]"
    return PY_TYPES[p["type"]]


specs = {}
for d in sorted(PROVIDERS.iterdir()):
    f = d / "params.json"
    if f.exists():
        specs[d.name] = json.loads(f.read_text())

ts = ["// GENERATED from gateway providers/*/params.json — do not edit.",
      "// Regenerate: python3 scripts/gen_provider_params.py", ""]
py = ['"""GENERATED from gateway providers/*/params.json — do not edit.',
      "Regenerate: python3 scripts/gen_provider_params.py",
      '"""', "from typing import Literal, TypedDict", ""]

iface_names = {}
for name, spec in specs.items():
    params = spec.get("params", [])
    iface = name.capitalize() + "Params"
    iface_names[name] = iface
    ts.append(f"/** Provider-specific options for `{name}/*` models. */")
    ts.append(f"export interface {iface} {{")
    for p in params:
        doc = p["doc"]
        extras = []
        if "default" in p:
            extras.append(f"@default {json.dumps(p['default'])}")
        if "min" in p or "max" in p:
            extras.append(f"range {p.get('min', '…')}–{p.get('max', '…')}")
        if p.get("modes"):
            extras.append("applies to " + " + ".join(p["modes"]))
        ts.append("  /** " + doc + (" — " + "; ".join(extras) if extras else "") + " */")
        key = p["name"]
        key_ts = f"'{key}'" if not key.replace("_", "a").isalnum() else key
        ts.append(f"  {key_ts}?: {ts_type(p)}")
    ts.append("  [key: string]: unknown")
    ts.append("}")
    ts.append("")

    fields = ",\n".join(
        f'        "{p["name"]}": {py_type(p)}' for p in params)
    py.append(f"{iface} = TypedDict(")
    py.append(f'    "{iface}",')
    if fields:
        py.append("    {\n" + fields + ",\n    },")
    else:
        py.append("    {},")
    py.append("    total=False,")
    py.append(")")
    py.append(f'"""Provider-specific options for {name}/* models."""')
    py.append("")

ts.append("/** Map from provider name to its typed params. */")
ts.append("export interface ProviderParamsMap {")
for name, iface in iface_names.items():
    ts.append(f"  {name}: {iface}")
ts.append("}")
ts.append("")

py.append("PROVIDER_PARAMS = {")
for name, iface in iface_names.items():
    py.append(f'    "{name}": {iface},')
py.append("}")
py.append("")

TS_OUT.write_text("\n".join(ts))
PY_OUT.write_text("\n".join(py))
print(f"wrote {TS_OUT.name} ({len(iface_names)} interfaces) + {PY_OUT.name}")
