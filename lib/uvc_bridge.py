#!/usr/bin/env python3
"""
UVC bridge for OpenC3 COSMOS. Talks to UVC cameras via raw libusb control
transfers (PyUSB) — same code path on Linux and macOS. Linux: udev rule
grants user access. macOS: must run with `sudo`.

Wire format:
    [ SYNC u16 = 0xAABB ][ LEN u16 ][ PKT_ID u8 ][ PAYLOAD... ]

Run:
    OPENC3_NO_STORE=1 OPENC3_API_HOSTNAME=localhost OPENC3_API_PORT=2900 \\
        python lib/uvc_bridge.py --port 8080
"""

import argparse
import array
import logging
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
from openc3.interfaces.tcpip_server_interface import TcpipServerInterface
from openc3.packets.packet import Packet
import usb.core

log = logging.getLogger("uvc_bridge")

SYNC = 0xAABB
HEADER_FMT = ">HHB"
HEADER_SIZE = 5

# Insta360 Link is the default auto-detect target.
INSTA360 = [(0x2E1A, 0x4C01, "Insta360 Link"),
            (0x2E1A, 0x4C04, "Insta360 Link 2")]

# Camera Terminal unit + PANTILT_ABSOLUTE selector — used by PAN_TILT command
# and (indirectly) PRESET_SAVE/RECALL.
CT_UNIT, CT_PANTILT, CT_ZOOM = 1, 0x0D, 0x0B


def _raw_ctrl(dev, bm_req_type, b_req, w_value, w_index, data_or_len):
    """Bypass PyUSB's managed_claim_interface so we don't kick the system
    camera service (Photo Booth, Zoom, etc.) off the VideoControl interface
    on macOS. Calls libusb's control transfer directly."""
    ret = dev._ctx.backend.ctrl_transfer(
        dev._ctx.handle, bm_req_type, b_req, w_value, w_index,
        data_or_len, 1000,
    )
    if log.isEnabledFor(logging.DEBUG):
        log.debug("ctrl_transfer bm=0x%02x req=0x%02x val=0x%04x idx=0x%04x ret=%r",
                  bm_req_type, b_req, w_value, w_index, ret)
    return ret


def uvc_set(dev, unit, sel, data):
    # Backend ctrl_transfer expects array.array for the OUT buffer.
    buf = array.array("B", data)
    try:
        _raw_ctrl(dev, 0x21, 0x01, sel << 8, unit << 8, buf)
    except usb.core.USBError as e:
        log.error("SET_CUR fail: unit=%d sel=0x%02x len=%d data=%s errno=%s msg=%s",
                  unit, sel, len(data), data.hex(), e.errno, e.strerror)
        raise


def uvc_get(dev, unit, sel, length):
    return bytes(_raw_ctrl(dev, 0xA1, 0x81, sel << 8, unit << 8, length))


def frame(pkt_id, payload):
    p = Packet()
    p.buffer = struct.pack(HEADER_FMT, SYNC, HEADER_SIZE + len(payload), pkt_id) + payload
    return p


def status_packet(dev, query_str, model, model_id):
    """Run live UVC GET_CUR for each `unit,sel,len,signed[,count];` query and
    frame the i32 results into a STATUS packet."""
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
    payload += struct.pack(">H", model_id) + model.encode("utf-8")
    return frame(0x80, payload)


def handle(pkt_id, payload, dev, presets):
    """Dispatch one inbound command packet. Returns a reply Packet or None."""
    if dev is None:
        return None
    try:
        if pkt_id == 0x01:  # SET_CTRL  [unit, sel, len, signed, value i64]
            unit, sel, length, signed, value = struct.unpack(">BBBBq", payload)
            mask = (1 << (8 * length)) - 1
            uvc_set(dev, unit, sel, (value & mask).to_bytes(length, "little"))
        elif pkt_id == 0x02:  # SET_PANTILT  [pan i32, tilt i32]
            uvc_set(dev, CT_UNIT, CT_PANTILT, struct.pack("<ii", *struct.unpack(">ii", payload)))
        elif pkt_id == 0x03:  # GIMBAL_RESET (no payload) — convenience alias for (0, 0)
            uvc_set(dev, CT_UNIT, CT_PANTILT, struct.pack("<ii", 0, 0))
        elif pkt_id == 0x40:  # PRESET_SAVE  [index u8]
            presets[payload[0]] = uvc_get(dev, CT_UNIT, CT_PANTILT, 8) + uvc_get(dev, CT_UNIT, CT_ZOOM, 2)
        elif pkt_id == 0x41:  # PRESET_RECALL  [index u8]
            blob = presets.get(payload[0])
            if blob:
                uvc_set(dev, CT_UNIT, CT_PANTILT, blob[:8])
                uvc_set(dev, CT_UNIT, CT_ZOOM, blob[8:10])
        else:
            log.warning("Unknown pkt_id 0x%02x", pkt_id)
    except Exception:
        log.exception("Failed handling 0x%02x", pkt_id)
    return None


def find_camera(vid, pid):
    """Return (usb_device, model_name, model_id) or (None, 'UVC', 0)."""
    if vid is not None and pid is not None:
        d = usb.core.find(idVendor=vid, idProduct=pid)
        result = (d, f"USB {vid:04x}:{pid:04x}", pid) if d else (None, "UVC", 0)
    else:
        result = (None, "UVC", 0)
        for v, p, name in INSTA360:
            d = usb.core.find(idVendor=v, idProduct=p)
            if d:
                log.info("Detected %s (%04x:%04x)", name, v, p)
                result = (d, name, p)
                break
        else:
            log.warning("No supported camera found")
    dev = result[0]
    if dev is not None:
        # Open the libusb device handle WITHOUT claiming any interface — this
        # lets the macOS AppleCameraInterface kext keep serving Photo Booth /
        # Zoom while we send control transfers via _raw_ctrl.
        try:
            dev._ctx.managed_open()
        except Exception as e:
            log.warning("Could not open device handle: %s", e)
        # set_configuration is required by libusb before transfers; without
        # claim it doesn't disturb the kext on macOS.
        try:
            dev.set_configuration()
        except Exception as e:
            log.warning("set_configuration: %s", e)
    return result


def main():
    ap = argparse.ArgumentParser(description="UVC bridge for OpenC3 COSMOS")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--vid", type=lambda s: int(s, 0))
    ap.add_argument("--pid", type=lambda s: int(s, 0))
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format="%(asctime)s [%(levelname)s] %(message)s")

    dev, model, model_id = find_camera(args.vid, args.pid)
    presets = {}

    intf = TcpipServerInterface(args.port, args.port, 10.0, None,
                                "LENGTH", 16, 16, 0, 1, "BIG_ENDIAN",
                                0, "0xAABB", None, True)
    intf.connect()
    log.info("UVC bridge listening on %d, model=%s", args.port, model)

    try:
        while True:
            pkt = intf.read()
            if pkt is None:
                break
            data = pkt.buffer
            if len(data) < HEADER_SIZE:
                continue
            _, length, pkt_id = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
            payload = data[HEADER_SIZE:length]
            if pkt_id == 0x7F:  # GET_STATUS
                q = payload.decode("utf-8", "replace").strip("\x00").strip()
                try:
                    intf.write(status_packet(dev, q, model, model_id))
                except Exception:
                    log.exception("STATUS write failed")
            else:
                handle(pkt_id, payload, dev, presets)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        try:
            intf.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main() or 0)
