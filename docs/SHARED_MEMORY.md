# Shared Vera memory on USB or Thunderbolt

Vera accepts an arbitrary SQLite path with `--store`. The portable helper
initializes that path and registers it with the local Codex installation.

## Create the USB installer

On the Mac where Vera is already installed, mount the USB drive and run:

```bash
vera portable-export /Volumes/VeraMemory
```

This copies the required Vera source to `Vera Shared Memory`, creates the
shared database, and creates `Vera Setup.command`.

## Setup on another Mac

Mount the drive and double-click:

```text
Vera Shared Memory/Vera Setup.command
```

The installer creates a local Python environment, registers Vera with Codex
when available, updates Claude Desktop's MCP configuration when installed,
and writes `mcp-config.json` for other MCP-compatible clients. Each Mac gets
its own client configuration; `.vera_store.db` on the drive is shared.

For a manually maintained checkout, the equivalent command is:

```bash
./scripts/setup_shared_memory_mac.sh /Volumes/VeraMemory
```

The lower-level initialization command is also available:

```bash
vera portable-init /Volumes/VeraMemory
```

## Safety

Mount the drive on one Mac at a time and eject it cleanly before moving it to
the other Mac. Never unplug it while Codex/Vera is running. Do not let two
Macs write the same SQLite database over SMB, NFS, or another filesystem with
unreliable SQLite locking. If simultaneous access is required, use a real
network database/service; for disconnected work, use separate stores and
reconcile with `vera sync`.

If the helper cannot find the Codex CLI, register manually:

```bash
codex mcp add vera -- \
  /absolute/path/to/call-me-vera/.venv312/bin/python \
  -m vera.cli mcp \
  --store /Volumes/VeraMemory/.vera_store.db
```
