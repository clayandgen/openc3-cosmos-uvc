# OpenC3 COSMOS UVC Plugin

<p align="center">
  <img src="public/store_img.png" alt="UVC Plugin" width="400"/>
</p>

Control USB Video Class (UVC) webcams from COSMOS. Generic UVC standard controls (PTZ, brightness, contrast, exposure, white balance, focus, etc.) work with any compliant camera. Optional Insta360 Link / Link 2 vendor-specific controls (AI tracking, scene modes, framing, target) gated by a plugin variable.

Single-repo: COSMOS plugin + a host-side bridge script (`lib/uvc_bridge.py`) that drives the camera via raw USB control transfers (PyUSB / libusb). One code path, cross-platform.

## Architecture

```
[ COSMOS plugin (Docker) ] --TCP/8080--> [ python lib/uvc_bridge.py (host) ] --libusb--> [ Camera ]
```

The bridge uses OpenC3's `TcpipServerInterface` so framing is symmetric on both ends. **Bridge synthesizes nothing.** Telemetry comes from live UVC `GET_CUR` requests against the actual device; the only writes back to COSMOS are STATUS replies driven by `GET_STATUS`.

The wire protocol is UVC-native: every command carries `(unit_id, selector, length, signed, value)`. No platform-specific naming, no translation table.

## Platform notes

| Platform | Status                                                                                                |
|----------|-------------------------------------------------------------------------------------------------------|
| Linux    | Works without root **if** a udev rule grants USB access to the camera's VID:PID. See Quick Start.     |
| macOS    | Must run the bridge with `sudo` — Apple holds the camera's `VideoControl` interface and libusb needs root to detach. |
| Windows  | Untested. PyUSB + libusb support Windows; should work with a WinUSB driver bound to the camera (Zadig). |

## Plugin Variables

| Variable                 | Default                  | Purpose                                                          |
|--------------------------|--------------------------|------------------------------------------------------------------|
| `uvc_target_name`        | `UVC`                    | Target name                                                      |
| `uvc_bridge_host`        | `host.docker.internal`   | Host running `uvc_bridge.py`                                     |
| `uvc_bridge_port`        | `8080`                   | TCP port the bridge listens on                                   |
| `uvc_insta360_enabled`   | `true`                   | Include Insta360 XU commands + screen section.                   |

## Wire Format

```
[ SYNC u16 = 0xAABB ][ LEN u16 ][ PKT_ID u8 ][ PAYLOAD... ]
```

Big-endian. COSMOS auto-fills `SYNC` and `LEN` (LengthProtocol `fill_fields=True`).

### Command IDs

| ID    | Name          | Payload                                                                                       | COSMOS COMMANDs                                                                 |
|-------|---------------|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| 0x01  | SET_CTRL      | `u8 UNIT_ID, u8 SELECTOR, u8 LENGTH, u8 SIGNED, i64 VALUE`                                    | `ZOOM`, `BRIGHTNESS`, `CONTRAST`, `SATURATION`, `SHARPNESS`, `BACKLIGHT_COMPENSATION`, `SCENE_MODE` *(Insta360)*, `TRACKING_FRAME` *(Insta360)*, `TRACKING_TARGET` *(Insta360)* |
| 0x02  | SET_PANTILT   | `i32 PAN, i32 TILT` (UVC CT_PANTILT_ABSOLUTE; combined 8-byte control)                        | `PAN_TILT`                                                                       |
| 0x03  | GIMBAL_RESET  | (none)                                                                                        | `GIMBAL_RESET`                                                                   |
| 0x40  | PRESET_SAVE   | `u8` slot 0-5 — bridge reads live pan/tilt/zoom and saves                                     | `PRESET_SAVE`                                                                    |
| 0x41  | PRESET_RECALL | `u8` slot 0-5                                                                                 | `PRESET_RECALL`                                                                  |
| 0x7F  | GET_STATUS    | utf-8 `unit,sel,len,signed[,count];...` query list                                            | `GET_STATUS` (default QUERIES in `cmd.txt`)                                      |

`SET_CTRL` does a single UVC `SET_CUR` control transfer: bytes = `value.to_bytes(LENGTH, "little", signed=SIGNED)` sent with `wValue=(SELECTOR<<8)`, `wIndex=(UNIT_ID<<8)`. The same dispatch handles standard UVC controls (CT unit 1, PU unit 5) and Insta360 vendor controls (XU units 9/10) — only the UNIT_ID/SELECTOR/LENGTH defaults in cmd.txt differ.

Insta360 `SCENE_MODE` packs the two-byte XU mode bytes into a single 16-bit LE value via STATEs (e.g. `WHITEBOARD` = `0x0104` = bytes `04 01`). `TRACKING_TARGET` packs byte[4] of an 8-byte buffer via `(target << 32)`.

### Telemetry

| ID    | Packet  | Source                                                                                |
|-------|---------|---------------------------------------------------------------------------------------|
| 0x80  | STATUS  | One UVC `GET_CUR` per query in `GET_STATUS NAMES`'s payload, packed as i32s. PANTILT (`count=2`) yields two fields (pan, tilt). Fields in `tlm.txt` must appear in QUERIES order. |

### STATUS field source-of-truth

The `QUERIES` default on the `GET_STATUS` command (in `cmd.txt`) lists which UVC controls the bridge reads, in the order the bridge packs them. Bridge has no hardcoded list. Add/remove a STATUS field = edit both `cmd.txt`'s `GET_STATUS QUERIES` default and the matching `APPEND_ITEM` in `tlm.txt`.

## Quick Start

Install the camera and tools

```
# macOS
brew install libuvc
python3 -m venv .venv && source .venv/bin/activate
pip install openc3 pyusb
```

Run the bridge:

```
# macOS
OPENC3_NO_STORE=1 OPENC3_API_HOSTNAME=localhost OPENC3_API_PORT=2900 \
    sudo -E python lib/uvc_bridge.py --port 8080
```

By default the bridge auto-detects an Insta360 Link / Link 2. Use `--vid 0xXXXX --pid 0xYYYY` for another camera.

Build and install the plugin:

```
<COSMOS>/openc3.sh cli rake build VERSION=1.0.0
```

Upload the `.gem` in Admin Tool > Plugins. Adjust `uvc_bridge_host`, `uvc_bridge_port`, `uvc_insta360_enabled` at install time.

## Script API

```python
load_utility('UVC/lib/uvc.py')
cam = Uvc()
cam.zoom(250)
cam.pan_tilt(1500, -300)
cam.brightness(50)
cam.scene_mode("AI_TRACKING")   # Insta360 only
cam.tracking_frame("HALF_BODY") # Insta360 only
cam.preset_save(0)
```

## License

MIT - see [LICENSE.txt](LICENSE.txt).
