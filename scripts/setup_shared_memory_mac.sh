#!/bin/sh
set -eu

# Install Vera from this checkout, initialize a store on an already-mounted
# external drive, and register that store with the local Codex installation.

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /Volumes/VeraMemory" >&2
  exit 2
fi

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
MOUNT_DIR=$(CDPATH= cd -- "$1" 2>/dev/null && pwd -P) || {
  echo "mount point does not exist: $1" >&2
  exit 1
}
STORE_PATH="$MOUNT_DIR/.vera_store.db"
ENV_DIR="$REPO_DIR/.venv312"

if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.12 "$ENV_DIR"
  uv pip install --python "$ENV_DIR/bin/python" "$REPO_DIR[mcp]"
else
  PYTHON_BIN=${VERA_PYTHON_BIN:-python3.12}
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "uv or Python 3.12+ is required" >&2
    exit 1
  }
  "$PYTHON_BIN" -m venv "$ENV_DIR"
  "$ENV_DIR/bin/python" -m pip install "$REPO_DIR[mcp]"
fi

"$ENV_DIR/bin/python" -m vera.cli portable-init "$MOUNT_DIR"

if command -v codex >/dev/null 2>&1; then
  codex mcp remove vera >/dev/null 2>&1 || true
  codex mcp add vera -- "$ENV_DIR/bin/python" -m vera.cli mcp --store "$STORE_PATH"
  echo "Registered Vera with Codex."
else
  echo "Codex CLI was not found. Register manually with:"
  echo "codex mcp add vera -- $ENV_DIR/bin/python -m vera.cli mcp --store $STORE_PATH"
fi

# Claude Desktop uses a JSON file rather than the Codex CLI. Preserve all
# existing servers and replace only Vera's entry. Also write the same
# standard stdio definition beside the portable bundle for other MCP hosts.
CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
"$ENV_DIR/bin/python" - "$MOUNT_DIR" "$STORE_PATH" "$ENV_DIR/bin/python" "$CLAUDE_CONFIG" <<'PY'
import json
import os
import sys
from pathlib import Path

root, store, python_bin, claude_config = map(Path, sys.argv[1:])
entry = {"command": str(python_bin), "args": ["-m", "vera.cli", "mcp", "--store", str(store)]}

standard = root / "mcp-config.json"
standard.write_text(json.dumps({"mcpServers": {"vera": entry}}, indent=2) + "\n", encoding="utf-8")

config_path = Path(claude_config)
if (Path("/Applications/Claude.app").exists()
        or Path.home().joinpath("Applications/Claude.app").exists()
        or config_path.exists()):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = {}
    else:
        config = {}
    config.setdefault("mcpServers", {})["vera"] = entry
    temp = config_path.with_suffix(config_path.suffix + ".tmp")
    temp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, config_path)
    print("Registered Vera with Claude Desktop.")
else:
    print("Claude Desktop was not detected; wrote the generic mcp-config.json.")
PY

echo "Generic MCP configuration: $MOUNT_DIR/mcp-config.json"
echo "Restart MCP clients after setup."
