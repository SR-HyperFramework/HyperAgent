#!/usr/bin/env python3
import json, sys
from pathlib import Path
try:
    import jsonschema
except ImportError:
    raise SystemExit("Install jsonschema: pip install jsonschema")
if len(sys.argv)!=3:
    raise SystemExit("usage: validate_output.py <schema.json> <output.json>")
schema=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
data=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
jsonschema.Draft202012Validator(schema).validate(data)
print("VALID")
