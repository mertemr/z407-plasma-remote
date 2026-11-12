"""GATT layout and command bytes of the Logitech Z407 BLE remote protocol."""

SERVICE_UUID = "0000fdc2-0000-1000-8000-00805f9b34fb"
CMD_CHAR_UUID = "c2e758b9-0e78-41e0-b0cb-98a593193fc5"
RESP_CHAR_UUID = "b84ac9c6-29c5-46d4-bba1-9d534784330f"

# Bass has 20 real steps. Volume has about 32, and the lower half is barely audible,
# so clients get VOL_LEVELS levels mapped as raw = VOL_RAW_MAX * (level / VOL_LEVELS) ** VOL_CURVE.
BASS_LEVELS = 20
BASS_RAW_MAX = 20
VOL_LEVELS = 20
VOL_RAW_MAX = 32
VOL_CURVE = 0.6


class Cmd:
    HANDSHAKE_INIT = bytes.fromhex("8405")
    HANDSHAKE_ACK = bytes.fromhex("8400")
    BASS_UP = bytes.fromhex("8000")
    BASS_DOWN = bytes.fromhex("8001")
    VOL_UP = bytes.fromhex("8002")
    VOL_DOWN = bytes.fromhex("8003")
    PLAY_PAUSE = bytes.fromhex("8004")
    NEXT_TRACK = bytes.fromhex("8005")
    PREV_TRACK = bytes.fromhex("8006")
    SRC_BLUETOOTH = bytes.fromhex("8101")
    SRC_AUX = bytes.fromhex("8102")
    SRC_USB = bytes.fromhex("8103")


class Resp:
    HANDSHAKE_INIT = bytes.fromhex("d40501")
    HANDSHAKE_DONE = (bytes.fromhex("d40001"), bytes.fromhex("d40002"), bytes.fromhex("d40003"))
    SOURCE_STATUS = {
        bytes.fromhex("cf04"): "bluetooth",
        bytes.fromhex("cf05"): "aux",
        bytes.fromhex("cf06"): "usb",
    }


SOURCE_COMMANDS = {
    "bluetooth": Cmd.SRC_BLUETOOTH,
    "aux": Cmd.SRC_AUX,
    "usb": Cmd.SRC_USB,
}
