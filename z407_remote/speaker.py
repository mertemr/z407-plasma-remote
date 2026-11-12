"""BLE link to a Logitech Z407: discovery, handshake and raw commands."""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from z407_remote.protocol import CMD_CHAR_UUID, RESP_CHAR_UUID, SERVICE_UUID, SOURCE_COMMANDS, Cmd, Resp

log = logging.getLogger(__name__)

SCAN_TIMEOUT_S = 10.0
HANDSHAKE_TIMEOUT_S = 5.0
HANDSHAKE_ACK_DELAY_S = 0.15


class Speaker:
    def __init__(self) -> None:
        self.connected = False
        self.address: str | None = None
        self.source: str | None = None
        self._client: BleakClient | None = None
        self._write_with_response = True
        self._handshake = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    async def connect(self, address: str | None = None) -> bool:
        target = await self._resolve(address)
        if target is None:
            log.warning("No Z407 found")
            return False

        client = BleakClient(target, disconnected_callback=self._on_disconnect)
        self._client = client
        self._handshake.clear()
        try:
            await client.connect()
            char = client.services.get_characteristic(CMD_CHAR_UUID)
            if char is None:
                raise BleakError("command characteristic not found")
            self._write_with_response = "write-without-response" not in char.properties
            await client.start_notify(RESP_CHAR_UUID, self._on_notify)
            await client.write_gatt_char(CMD_CHAR_UUID, Cmd.HANDSHAKE_INIT, response=True)
            await asyncio.wait_for(self._handshake.wait(), HANDSHAKE_TIMEOUT_S)
        except (BleakError, TimeoutError, OSError) as e:
            log.warning("Connection failed: %s", e or type(e).__name__)
            await self.disconnect()
            return False

        self.address = client.address
        self.connected = True
        log.info("Connected to %s", self.address)
        return True

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        self.connected = False
        if client and client.is_connected:
            await client.disconnect()

    async def send(self, data: bytes) -> bool:
        if not self.connected or self._client is None:
            return False
        try:
            await self._client.write_gatt_char(CMD_CHAR_UUID, data, response=self._write_with_response)
        except BleakError as e:
            log.warning("Write %s failed: %s", data.hex(), e)
            return False
        log.debug("TX %s", data.hex())
        return True

    async def select_source(self, source: str) -> bool:
        if not await self.send(SOURCE_COMMANDS[source]):
            return False
        # The speaker does not always report the new source, so assume the switch worked.
        self.source = source
        return True

    async def _resolve(self, address: str | None) -> BLEDevice | str | None:
        if address:
            # A device still linked to BlueZ does not advertise; connecting by address works then.
            return await BleakScanner.find_device_by_address(address, timeout=SCAN_TIMEOUT_S / 2) or address
        log.info("Scanning for a Z407")
        return await BleakScanner.find_device_by_filter(
            lambda _, adv: SERVICE_UUID in (uuid.lower() for uuid in adv.service_uuids),
            timeout=SCAN_TIMEOUT_S,
        )

    def _on_notify(self, _: object, payload: bytearray) -> None:
        data = bytes(payload)
        log.debug("RX %s", data.hex())
        if data == Resp.HANDSHAKE_INIT:
            self._spawn(self._ack_handshake())
        elif data in Resp.HANDSHAKE_DONE:
            self._handshake.set()
        elif data in Resp.SOURCE_STATUS:
            self.source = Resp.SOURCE_STATUS[data]

    async def _ack_handshake(self) -> None:
        await asyncio.sleep(HANDSHAKE_ACK_DELAY_S)
        if self._client is not None:
            await self._client.write_gatt_char(CMD_CHAR_UUID, Cmd.HANDSHAKE_ACK, response=True)

    def _on_disconnect(self, client: BleakClient) -> None:
        # BlueZ can report a stale disconnect while a new link is being set up; ignore those.
        if client is not self._client or not self.connected:
            return
        log.info("Speaker disconnected")
        self._client = None
        self.connected = False

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
