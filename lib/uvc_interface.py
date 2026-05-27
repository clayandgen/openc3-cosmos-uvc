"""
COSMOS Interface for UVC cameras. Drives the camera via raw libusb control
transfers (PyUSB) so the same code runs on Linux and macOS.

Bridge usage:
    openc3cli bridgegem openc3-cosmos-uvc vendor_id=0x2E1A product_id=0x4C04 router_port=8080

The interface receives framed packets (LengthProtocol on the bridge ROUTER)
and dispatches one UVC control transfer per command.
"""

import array
import logging
import queue
import struct
import threading
from typing import Optional, Tuple

import usb.core
from openc3.interfaces.interface import Interface

log = logging.getLogger("uvc_interface")


# --- Wire protocol -----------------------------------------------------------

SYNC = 0xAABB
HEADER_FMT = ">HHB"
HEADER_SIZE = 5

CMD_SET_CTRL     = 0x01
CMD_SET_PANTILT  = 0x02
CMD_GIMBAL_RESET = 0x03
CMD_PRESET_SAVE  = 0x40
CMD_PRESET_RECALL= 0x41
CMD_GET_STATUS   = 0x7F
TLM_STATUS       = 0x80

CT_UNIT, CT_PANTILT, CT_ZOOM = 1, 0x0D, 0x0B


def _raw_ctrl(dev, bm_req_type, b_req, w_value, w_index, data_or_len):
    """libusb control transfer without managed_claim_interface — keeps the
    macOS AppleCameraInterface kext attached so Photo Booth / Zoom etc. can
    still stream while the bridge sends UVC SET_CUR / GET_CUR."""
    return dev._ctx.backend.ctrl_transfer(
        dev._ctx.handle, bm_req_type, b_req, w_value, w_index,
        data_or_len, 1000,
    )


def uvc_set(dev, unit, sel, data):
    buf = array.array("B", data)
    _raw_ctrl(dev, 0x21, 0x01, sel << 8, unit << 8, buf)


def uvc_get(dev, unit, sel, length):
    return bytes(_raw_ctrl(dev, 0xA1, 0x81, sel << 8, unit << 8, length))


def _frame(pkt_id: int, payload: bytes) -> bytes:
    return struct.pack(HEADER_FMT, SYNC, HEADER_SIZE + len(payload), pkt_id) + payload


def _status_payload(dev, query_str: str) -> bytes:
    payload = b""
    for chunk in query_str.split(";"):
        parts = [p.strip() for p in chunk.strip().split(",") if p.strip()]
        if len(parts) < 4:
            continue
        unit, sel, length, signed = (int(parts[i], 0) for i in range(4))
        count = int(parts[4], 0) if len(parts) > 4 else 1
        try:
            data = uvc_get(dev, unit, sel, length)
        except Exception:
            data = b"\x00" * length
        n = length // count
        for i in range(count):
            v = int.from_bytes(data[i*n:(i+1)*n], "little", signed=bool(signed))
            payload += struct.pack(">i", max(-0x80000000, min(0x7FFFFFFF, v)))
    return payload


# --- Interface ---------------------------------------------------------------

INSTA360_VID = 0x2E1A
INSTA360_LINK_PIDS = {0x4C01: "Insta360 Link", 0x4C04: "Insta360 Link 2"}


class UvcInterface(Interface):
    """
    USB Video Class camera interface. Args from bridge.txt:
        uvc_interface.py <vendor_id> <product_id>
    Pass `nil` for either to auto-detect the first Insta360 Link.
    """

    def __init__(self, vendor_id="nil", product_id="nil"):
        super().__init__()
        self.vid = self._parse_id(vendor_id)
        self.pid = self._parse_id(product_id)
        self.dev = None
        self.model = "UVC"
        self.model_id = 0
        self.presets = {}
        self._connected = False
        self._read_queue: "queue.Queue[bytes]" = queue.Queue()
        self._lock = threading.Lock()

    @staticmethod
    def _parse_id(value):
        if value is None or str(value).lower() in ("nil", "none", ""):
            return None
        return int(value, 0) if isinstance(value, str) else int(value)

    def connection_string(self) -> str:
        return f"UVC {self.vid:04x}:{self.pid:04x}" if self.vid and self.pid else "UVC (auto)"

    # --- lifecycle ---

    def connect(self):
        super().connect()
        if self.vid is not None and self.pid is not None:
            d = usb.core.find(idVendor=self.vid, idProduct=self.pid)
            if d is not None:
                self.dev = d
                self.model = f"USB {self.vid:04x}:{self.pid:04x}"
                self.model_id = self.pid
        else:
            for pid, name in INSTA360_LINK_PIDS.items():
                d = usb.core.find(idVendor=INSTA360_VID, idProduct=pid)
                if d is not None:
                    self.dev = d
                    self.model = name
                    self.model_id = pid
                    log.info("Detected %s (%04x:%04x)", name, INSTA360_VID, pid)
                    break
        if self.dev is None:
            raise IOError(f"No UVC camera found ({self.connection_string()})")
        # Open device handle + set configuration WITHOUT claiming any interface
        # so the macOS camera kext stays attached.
        self.dev._ctx.managed_open()
        try:
            self.dev.set_configuration()
        except Exception as e:
            log.warning("set_configuration: %s", e)
        self._connected = True

    def connected(self) -> bool:
        return self._connected

    def disconnect(self):
        self._connected = False
        try:
            self._read_queue.put_nowait(b"")
        except queue.Full:
            pass
        if self.dev is not None:
            try:
                usb.util.dispose_resources(self.dev)
            except Exception:
                pass
            self.dev = None
        super().disconnect()

    # --- I/O ---

    def read_interface(self) -> Tuple[Optional[bytes], None]:
        while self._connected:
            try:
                data = self._read_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if not data:
                return None, None
            self.read_interface_base(data, None)
            return data, None
        return None, None

    def write_interface(self, data, extra=None):
        self.write_interface_base(data, extra)
        if len(data) < HEADER_SIZE:
            return data, extra
        _, length, pkt_id = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        payload = bytes(data[HEADER_SIZE:length])
        with self._lock:
            self._dispatch(pkt_id, payload)
        return data, extra

    # --- dispatch ---

    def _dispatch(self, pkt_id: int, payload: bytes):
        if self.dev is None:
            return
        try:
            if pkt_id == CMD_SET_CTRL:
                unit, sel, length, signed, value = struct.unpack(">BBBBq", payload)
                mask = (1 << (8 * length)) - 1
                uvc_set(self.dev, unit, sel, (value & mask).to_bytes(length, "little"))
            elif pkt_id == CMD_SET_PANTILT:
                pan, tilt = struct.unpack(">ii", payload)
                uvc_set(self.dev, CT_UNIT, CT_PANTILT, struct.pack("<ii", pan, tilt))
            elif pkt_id == CMD_GIMBAL_RESET:
                uvc_set(self.dev, CT_UNIT, CT_PANTILT, struct.pack("<ii", 0, 0))
            elif pkt_id == CMD_PRESET_SAVE:
                self.presets[payload[0]] = (
                    uvc_get(self.dev, CT_UNIT, CT_PANTILT, 8) +
                    uvc_get(self.dev, CT_UNIT, CT_ZOOM, 2)
                )
            elif pkt_id == CMD_PRESET_RECALL:
                blob = self.presets.get(payload[0])
                if blob:
                    uvc_set(self.dev, CT_UNIT, CT_PANTILT, blob[:8])
                    uvc_set(self.dev, CT_UNIT, CT_ZOOM, blob[8:10])
            elif pkt_id == CMD_GET_STATUS:
                q = payload.decode("utf-8", "replace").strip("\x00").strip()
                body = _status_payload(self.dev, q)
                body += struct.pack(">H", self.model_id) + self.model.encode("utf-8")
                self._read_queue.put(_frame(TLM_STATUS, body))
            else:
                log.warning("Unknown pkt_id 0x%02x", pkt_id)
        except Exception:
            log.exception("Failed handling 0x%02x", pkt_id)
