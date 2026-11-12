"""
z407d: keeps the BLE link to the speaker and serves commands on a Unix socket.

Clients send one command per line and get one JSON status line back. The speaker drops idle
links after about five minutes, so every command reconnects on demand.

The speaker never reports its volume or bass and confirms steps even at the limits, so levels
are tracked here as raw step counts. The first absolute "set" while a level is unknown steps
down to the minimum, which is a known zero, and then up to the target. Tracked levels are
saved so they survive restarts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from z407_remote.protocol import BASS_LEVELS, BASS_RAW_MAX, VOL_CURVE, VOL_LEVELS, VOL_RAW_MAX, Cmd
from z407_remote.speaker import Speaker

log = logging.getLogger("z407d")

STEP_GAP_S = 0.12  # the speaker drops steps that arrive faster than this
SYNC_EXTRA_STEPS = 8  # margin in case the real range is larger than assumed

LEVELS = {
    "volume": {
        "levels": VOL_LEVELS,
        "raw_max": VOL_RAW_MAX,
        "curve": VOL_CURVE,
        "up": Cmd.VOL_UP,
        "down": Cmd.VOL_DOWN,
    },
    "bass": {
        "levels": BASS_LEVELS,
        "raw_max": BASS_RAW_MAX,
        "curve": 1.0,
        "up": Cmd.BASS_UP,
        "down": Cmd.BASS_DOWN,
    },
}


def socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime_dir) / "z407.sock"


def levels_path() -> Path:
    state_dir = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state_dir) / "z407" / "levels.json"


def level_to_raw(kind: str, level: int) -> int:
    spec = LEVELS[kind]
    return round(spec["raw_max"] * (level / spec["levels"]) ** spec["curve"])


def raw_to_level(kind: str, raw: int) -> int:
    return min(range(LEVELS[kind]["levels"] + 1), key=lambda level: abs(level_to_raw(kind, level) - raw))


class Daemon:
    def __init__(self, address: str | None) -> None:
        self.address = address
        self.speaker = Speaker()
        self.connecting = False
        self.last_error = ""
        self._connect_lock = asyncio.Lock()
        self._level_lock = asyncio.Lock()
        self.raw: dict[str, int | None] = self._load_levels()

        self.actions: dict[str, Callable[[], Awaitable[object]]] = {
            "vol_up": lambda: self.nudge("volume", +1),
            "vol_down": lambda: self.nudge("volume", -1),
            "bass_up": lambda: self.nudge("bass", +1),
            "bass_down": lambda: self.nudge("bass", -1),
            "play_pause": lambda: self.speaker.send(Cmd.PLAY_PAUSE),
            "next": lambda: self.speaker.send(Cmd.NEXT_TRACK),
            "prev": lambda: self.speaker.send(Cmd.PREV_TRACK),
            "src_bt": lambda: self.speaker.select_source("bluetooth"),
            "src_aux": lambda: self.speaker.select_source("aux"),
            "src_usb": lambda: self.speaker.select_source("usb"),
        }

    def level(self, kind: str) -> int | None:
        raw = self.raw[kind]
        return None if raw is None else raw_to_level(kind, raw)

    def status(self) -> dict:
        return {
            "daemon": True,
            "connected": self.speaker.connected,
            "connecting": self.connecting,
            "address": self.speaker.address or self.address,
            "volume": self.level("volume"),
            "bass": self.level("bass"),
            "volume_max": VOL_LEVELS,
            "bass_max": BASS_LEVELS,
            "source": self.speaker.source,
            "error": self.last_error,
        }

    async def ensure_connected(self) -> bool:
        async with self._connect_lock:
            if self.speaker.connected:
                return True
            self.connecting = True
            try:
                ok = await self.speaker.connect(self.address)
            finally:
                self.connecting = False
            if ok:
                self.address = self.speaker.address
            self.last_error = "" if ok else "connect_failed"
            return ok

    def _load_levels(self) -> dict[str, int | None]:
        raw: dict[str, int | None] = dict.fromkeys(LEVELS)
        try:
            saved = json.loads(levels_path().read_text())
        except (OSError, ValueError):
            return raw
        for kind, spec in LEVELS.items():
            value = saved.get(f"{kind}_raw")
            if isinstance(value, int) and 0 <= value <= spec["raw_max"]:
                raw[kind] = value
        return raw

    def _save_levels(self) -> None:
        path = levels_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({f"{kind}_raw": value for kind, value in self.raw.items()}))

    async def _step(self, kind: str, up: bool, count: int) -> bool:
        cmd = LEVELS[kind]["up" if up else "down"]
        for _ in range(count):
            if not await self.speaker.send(cmd):
                return False
            await asyncio.sleep(STEP_GAP_S)
        return True

    async def _move_raw(self, kind: str, target: int) -> None:
        delta = target - self.raw[kind]
        # A partial run leaves the real level somewhere in between, so it becomes unknown.
        self.raw[kind] = target if await self._step(kind, delta > 0, abs(delta)) else None
        self._save_levels()

    async def nudge(self, kind: str, delta: int) -> None:
        async with self._level_lock:
            if self.raw[kind] is None:
                await self._step(kind, delta > 0, abs(delta))
                return
            current = self.level(kind)
            target = max(0, min(LEVELS[kind]["levels"], current + delta))
            if target == current:
                # At the limit the step is still sent: the speaker plays its limit chime and
                # clamps, which also re-aligns a drifted level.
                await self._step(kind, delta > 0, 1)
                return
            await self._move_raw(kind, level_to_raw(kind, target))

    async def set_level(self, kind: str, level: int) -> None:
        spec = LEVELS[kind]
        level = max(0, min(spec["levels"], level))
        async with self._level_lock:
            if self.raw[kind] is None:
                log.info("Syncing %s from the minimum", kind)
                if not await self._step(kind, False, spec["raw_max"] + SYNC_EXTRA_STEPS):
                    return
                self.raw[kind] = 0
            await self._move_raw(kind, level_to_raw(kind, level))

    async def execute(self, line: str) -> dict:
        cmd, *args = line.split() or [""]
        if cmd == "status":
            pass
        elif cmd == "connect":
            await self.ensure_connected()
        elif cmd == "disconnect":
            await self.speaker.disconnect()
        elif cmd == "forget":
            self.raw = dict.fromkeys(LEVELS)
            self._save_levels()
        elif cmd in ("vol_set", "bass_set") and len(args) == 1 and args[0].isdigit():
            if await self.ensure_connected():
                await self.set_level("volume" if cmd == "vol_set" else "bass", int(args[0]))
        elif cmd in self.actions and not args:
            if await self.ensure_connected():
                await self.actions[cmd]()
        else:
            return {**self.status(), "error": f"unknown_command:{line}"}
        return self.status()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await reader.readline()).decode(errors="replace").strip()
            writer.write((json.dumps(await self.execute(line)) + "\n").encode())
            await writer.drain()
        except ConnectionError:
            pass
        except Exception:
            log.exception("Command failed")
        finally:
            writer.close()

    async def serve(self) -> None:
        path = socket_path()
        path.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(self.handle_client, path=str(path))
        path.chmod(0o600)
        log.info("Listening on %s", path)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        async with server:
            await stop.wait()
        # Without a clean disconnect BlueZ keeps the link and the speaker stops advertising.
        await self.speaker.disconnect()
        path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Logitech Z407 BLE service")
    parser.add_argument("--address", "-a", default=os.environ.get("Z407_ADDRESS") or None, help="speaker BLE address")
    parser.add_argument("--debug", "-d", action="store_true", help="log every BLE packet")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(name)s: %(message)s")
    if not args.debug:
        logging.getLogger("bleak").setLevel(logging.WARNING)

    asyncio.run(Daemon(args.address).serve())


if __name__ == "__main__":
    main()
