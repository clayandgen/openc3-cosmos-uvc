#!/usr/bin/env python3
"""
UVC bridge for OpenC3 COSMOS.

Listens on TCP for framed binary command packets from the openc3-cosmos-uvc
plugin, drives the camera via V4L2 + UVC Extension Unit (XU) controls, and
replies to GET_STATUS with live values read from the device. Synthesizes
nothing — every byte sent back originates from a real device query or USB
enumeration.

Wire format:
    [ SYNC u16 = 0xAABB ][ LEN u16 = total bytes ][ PKT_ID u8 ][ PAYLOAD... ]

Run:
    OPENC3_NO_STORE=1 python lib/uvc_bridge.py --device /dev/video0 --port 8080
"""

import argparse
import logging
import re
import shutil
import struct
import subprocess
import sys
from typing import Dict, Optional

from openc3.interfaces.tcpip_server_interface import TcpipServerInterface
from openc3.packets.packet import Packet

try:
    import usb.core
    HAVE_USB = True
except ImportError:
    HAVE_USB = False


log = logging.getLogger("uvc_bridge")


# --- Wire protocol -----------------------------------------------------------

SYNC = 0xAABB
HEADER_FMT = ">HHB"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

CMD_SET_V4L2_CTRL = 0x01
CMD_PAN_TILT_REL = 0x04
CMD_GIMBAL_RESET = 0x05
CMD_AI_TRACKING = 0x10
CMD_TRACKING_FRAME = 0x11
CMD_TRACKING_TARGET = 0x12
CMD_SCENE_MODE = 0x13
CMD_PRESET_SAVE = 0x40
CMD_PRESET_RECALL = 0x41
CMD_GET_STATUS = 0x7F
TLM_STATUS = 0x80


# --- Insta360 USB + XU -------------------------------------------------------

INSTA360_VID = 0x2E1A
INSTA360_LINK_PIDS = {0x4C01: "Insta360 Link", 0x4C04: "Insta360 Link 2"}

XU_UNIT_PRIMARY = 9
XU_UNIT_TARGET = 10
XU_SEL_MODE = 2
XU_SEL_FRAME = 5
XU_SEL_TARGET = 1
XU_SEL_RESET = 3

SCENE_MODE_BYTES = {
    0: b"\x00\x00",  # NORMAL
    1: b"\x04\x01",  # WHITEBOARD
    2: b"\x05\x03",  # OVERHEAD
    3: b"\x06\x10",  # DESKVIEW
}
AI_TRACKING_BYTES = b"\x01\x00"

UVC_SET_CUR = 0x01
UVC_GET_LEN = 0x85
BMREQ_SET = 0x21
BMREQ_GET = 0xA1


# --- V4L2 ---------------------------------------------------------------------

def v4l2_set(device: str, name: str, value: int):
    subprocess.run(
        ["v4l2-ctl", "-d", device, "--set-ctrl", f"{name}={value}"],
        capture_output=True, text=True, timeout=5, check=True,
    )


def v4l2_get(device: str, names) -> Dict[str, int]:
    if not names:
        return {}
    out = subprocess.run(
        ["v4l2-ctl", "-d", device, "--get-ctrl", ",".join(names)],
        capture_output=True, text=True, timeout=5,
    ).stdout
    values: Dict[str, int] = {}
    for line in out.splitlines():
        m = re.match(r"\s*([a-zA-Z0-9_]+)\s*:\s*(-?\d+)", line)
        if m:
            values[m.group(1)] = int(m.group(2))
    return values


# --- XU ----------------------------------------------------------------------

def find_insta360():
    """Return (usb_device, model_name, model_id). dev is None if not found."""
    if not HAVE_USB:
        log.info("pyusb not installed; XU controls disabled")
        return None, "UVC", 0
    for pid, name in INSTA360_LINK_PIDS.items():
        d = usb.core.find(idVendor=INSTA360_VID, idProduct=pid)
        if d is not None:
            log.info("Detected %s (VID=0x%04x PID=0x%04x)",
                     name, INSTA360_VID, pid)
            return d, name, pid
    log.info("No Insta360 Link detected; XU controls unavailable")
    return None, "UVC", 0


def xu_set(dev, unit: int, selector: int, data: bytes):
    raw = dev.ctrl_transfer(
        BMREQ_GET, UVC_GET_LEN, selector << 8, unit << 8, 2, timeout=1000,
    )
    length = raw[0] | (raw[1] << 8)
    data = (data + bytes(length))[:length]
    dev.ctrl_transfer(
        BMREQ_SET, UVC_SET_CUR, selector << 8, unit << 8, data, timeout=1000,
    )


# --- Packets -----------------------------------------------------------------

def build_packet(pkt_id: int, payload: bytes) -> bytes:
    return struct.pack(HEADER_FMT, SYNC, HEADER_SIZE + len(payload), pkt_id) + payload


def status_packet(device: str, names, model: str, model_id: int) -> Packet:
    """Query the V4L2 controls listed in `names` (in order) and frame STATUS."""
    values = v4l2_get(device, names)
    payload = b"".join(struct.pack(">i", values.get(n, 0)) for n in names)
    payload += struct.pack(">H", model_id) + model.encode("utf-8")
    p = Packet()
    p.buffer = build_packet(TLM_STATUS, payload)
    return p


# --- Command dispatch --------------------------------------------------------

def dispatch(pkt_id: int, payload: bytes, device: str, xu_dev, presets: dict):
    try:
        if pkt_id == CMD_SET_V4L2_CTRL:
            value = struct.unpack(">i", payload[:4])[0]
            name = payload[4:].decode("utf-8", "replace").strip("\x00").strip()
            if name:
                v4l2_set(device, name, value)

        elif pkt_id == CMD_PAN_TILT_REL:
            dpan, dtilt = struct.unpack(">ii", payload)
            cur = v4l2_get(device, ["pan_absolute", "tilt_absolute"])
            v4l2_set(device, "pan_absolute",  cur.get("pan_absolute", 0)  + dpan)
            v4l2_set(device, "tilt_absolute", cur.get("tilt_absolute", 0) + dtilt)

        elif pkt_id == CMD_GIMBAL_RESET:
            v4l2_set(device, "pan_absolute", 0)
            v4l2_set(device, "tilt_absolute", 0)
            if xu_dev:
                try:
                    xu_set(xu_dev, XU_UNIT_PRIMARY, XU_SEL_RESET, b"\x01")
                except Exception:
                    pass  # Not all Insta360 firmwares accept this selector.

        elif pkt_id == CMD_AI_TRACKING and xu_dev:
            xu_set(xu_dev, XU_UNIT_PRIMARY, XU_SEL_MODE,
                   AI_TRACKING_BYTES if payload[0] else SCENE_MODE_BYTES[0])
        elif pkt_id == CMD_TRACKING_FRAME and xu_dev:
            xu_set(xu_dev, XU_UNIT_PRIMARY, XU_SEL_FRAME, bytes([payload[0]]))
        elif pkt_id == CMD_TRACKING_TARGET and xu_dev:
            buf = bytearray(8); buf[4] = payload[0]
            xu_set(xu_dev, XU_UNIT_TARGET, XU_SEL_TARGET, bytes(buf))
        elif pkt_id == CMD_SCENE_MODE and xu_dev:
            xu_set(xu_dev, XU_UNIT_PRIMARY, XU_SEL_MODE, SCENE_MODE_BYTES[payload[0]])

        elif pkt_id == CMD_PRESET_SAVE:
            presets[payload[0]] = v4l2_get(
                device, ["pan_absolute", "tilt_absolute", "zoom_absolute"]
            )
        elif pkt_id == CMD_PRESET_RECALL:
            for name, value in presets.get(payload[0], {}).items():
                v4l2_set(device, name, value)

    except Exception:
        log.exception("Failed handling 0x%02x", pkt_id)


# --- Main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="UVC bridge for OpenC3 COSMOS")
    ap.add_argument("--port", type=int, default=8080, help="TCP listen port")
    ap.add_argument("--device", default="/dev/video0", help="V4L2 device")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not shutil.which("v4l2-ctl"):
        log.warning("v4l2-ctl not on PATH; V4L2 commands will fail")

    xu_dev, model, model_id = find_insta360()
    presets: Dict[int, Dict[str, int]] = {}

    intf = TcpipServerInterface(
        args.port, args.port, 10.0, None,
        "LENGTH", 16, 16, 0, 1, "BIG_ENDIAN", 0, 0xAABB, None, True,
    )
    intf.connect()
    log.info("UVC bridge listening on %d, V4L2=%s, model=%s",
             args.port, args.device, model)

    try:
        while True:
            packet = intf.read()
            if packet is None:
                log.info("Interface closed; exiting")
                break
            data = packet.buffer
            if len(data) < HEADER_SIZE:
                continue
            _, length, pkt_id = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
            payload = data[HEADER_SIZE:length]
            if pkt_id == CMD_GET_STATUS:
                names = [
                    n.strip() for n in payload.decode("utf-8", "replace").split(",")
                    if n.strip()
                ]
                try:
                    intf.write(status_packet(args.device, names, model, model_id))
                except Exception:
                    log.exception("STATUS write failed")
            else:
                dispatch(pkt_id, payload, args.device, xu_dev, presets)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        try:
            intf.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main() or 0)
