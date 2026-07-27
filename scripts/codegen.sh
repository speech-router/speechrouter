#!/usr/bin/env bash
# Regenerate gateway protocol models from packages/spec. CI fails if output differs.
set -euo pipefail
cd "$(dirname "$0")/../gateway"
uv run datamodel-codegen \
  --input ../packages/spec/events.schema.json \
  --input-file-type jsonschema \
  --output speechrouter_gateway/protocol/events.py \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.13 \
  --use-schema-description --collapse-root-models --disable-timestamp \
  --formatters black isort
