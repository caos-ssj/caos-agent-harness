"""Entry point for the standalone Tauri desktop sidecar binary."""
import multiprocessing

from caos_harness.__main__ import cli


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(cli())
