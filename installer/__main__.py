"""Entry point: python3 -m installer [subcommand] [options]."""

from __future__ import annotations

import sys

from installer.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
