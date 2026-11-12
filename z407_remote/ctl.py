#!/usr/bin/env python3
"""
z407ctl: send one command to z407d and print its JSON status.

Standard library only, so it starts fast and runs with any system Python.
"""

import json
import os
import socket
import sys

TIMEOUT_S = 30
USAGE = """usage: z407ctl [command]

  status                     print the current status (default)
  connect | disconnect
  vol_up | vol_down | vol_set N       N = 0-20
  bass_up | bass_down | bass_set N    N = 0-20
  forget                     drop tracked levels so the next set re-syncs
  play_pause | next | prev
  src_bt | src_aux | src_usb"""


def main() -> int:
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(USAGE)
        return 0

    cmd = " ".join(sys.argv[1:]) or "status"
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    path = os.path.join(runtime_dir, "z407.sock")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT_S)
            sock.connect(path)
            sock.sendall((cmd + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
    except OSError as e:
        print(json.dumps({"daemon": False, "error": f"daemon_unreachable:{type(e).__name__}"}))
        return 1

    print(data.decode().strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
