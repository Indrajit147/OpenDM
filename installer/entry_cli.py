"""PyInstaller entry point for opendm-cli.exe."""

import sys

from opendm.cli.__main__ import main

sys.exit(main())
