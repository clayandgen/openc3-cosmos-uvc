#!/usr/bin/env python3
"""
Launcher for the UVC bridge.

`openc3pycli bridge` imports the interface module by bare name (e.g.
`uvc_interface`) so the lib/ folder where uvc_interface.py lives must be on
sys.path. This launcher puts it there and forwards all args to
`openc3pycli bridge bridge.txt`.

Run:
    sudo -E .venv/bin/python run_bridge.py vendor_id=0x2E1A product_id=0x4C04 router_port=8080
"""

import os
import sys

# Env vars must land before any openc3 import (openc3.environment freezes
# OPENC3_NO_STORE at import time).
os.environ.setdefault("OPENC3_NO_STORE", "1")
os.environ.setdefault("OPENC3_API_HOSTNAME", "localhost")
os.environ.setdefault("OPENC3_API_PORT", "2900")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

from openc3.cli import main  # noqa: E402

if __name__ == "__main__":
    bridge_file = os.path.join(HERE, "bridge.txt")
    main(["bridge", bridge_file] + sys.argv[1:])
