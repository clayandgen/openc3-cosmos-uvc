# OpenC3 COSMOS UVC Plugin

<p align="center">
  <img src="public/store_img.png" alt="UVC Plugin" width="400"/>
</p>

Control USB Video Class (UVC) webcams from COSMOS. Generic V4L2 standard controls (PTZ, brightness, contrast, exposure, white balance, focus, etc.) work with any compliant camera. Optional Insta360 Link / Link 2 vendor-specific controls (AI tracking, scene modes, framing, target) gated by a plugin variable.

Single-repo, modeled after `openc3-cosmos-elegoo-tumbller`: the plugin and the host-side bridge script (`lib/uvc_bridge.py`) ship in one gem.

## Architecture

```
[ COSMOS plugin (Docker) ] --TCP/8080--> [ python lib/uvc_bridge.py (host) ] --V4L2/USB--> [ Camera ]
```

The bridge script uses OpenC3's `TcpipServerInterface` directly so framing is symmetric on both ends. **Bridge synthesizes nothing.** Telemetry is live `v4l2-ctl --get-ctrl` queries against the actual device; the only writes back to COSMOS are STATUS replies driven by `GET_STATUS` commands.

## Plugin Variables

| Variable                 | Default                  | Purpose                                                          |
|--------------------------|--------------------------|------------------------------------------------------------------|
| `uvc_target_name`        | `UVC`                    | Target name                                                      |
| `uvc_bridge_host`        | `host.docker.internal`   | Host where `uvc_bridge.py` runs                                  |
| `uvc_bridge_port`        | `8080`                   | TCP port the bridge listens on                                   |
| `uvc_insta360_enabled`   | `true`                   | Include Insta360 XU commands + screen section. Set `false` for generic UVC cameras. |

## Wire Format

```
[ SYNC u16 = 0xAABB ][ LEN u16 = total bytes ][ PKT_ID u8 ][ PAYLOAD... ]
```

Big-endian. COSMOS auto-fills `SYNC` and `LEN` (LengthProtocol `fill_fields=True`).

### Command IDs

All V4L2 standard controls share one PKT_ID — each `COMMAND` in `cmd.txt`
embeds its V4L2 control name as a fixed payload string. Bridge is a thin
proxy: `v4l2-ctl --set-ctrl <NAME>=<VALUE>`. No V4L2 mapping table in the
bridge.

| ID    | Name              | Payload                                              | COSMOS COMMANDs                                                                 |
|-------|-------------------|------------------------------------------------------|---------------------------------------------------------------------------------|
| 0x01  | SET_V4L2_CTRL     | `i32 VALUE` + utf-8 `NAME` to end of packet         | `ZOOM`, `PAN`, `TILT`, `BRIGHTNESS`, `CONTRAST`, `SATURATION`, `SHARPNESS`, `GAIN`, `BACKLIGHT_COMPENSATION`, `AUTO_WHITE_BALANCE`, `WHITE_BALANCE_TEMP`, `EXPOSURE_AUTO`, `EXPOSURE_ABSOLUTE`, `AUTO_FOCUS`, `FOCUS_ABSOLUTE`, `V4L2_SET` |
| 0x04  | PAN_TILT_RELATIVE | `i32 pan, i32 tilt`                                  | `PAN_TILT_RELATIVE`                                                             |
| 0x05  | GIMBAL_RESET      | (none)                                               | `GIMBAL_RESET`                                                                  |
| 0x10  | AI_TRACKING       | `u8` 0/1                                             | `AI_TRACKING` *(Insta360)*                                                      |
| 0x11  | TRACKING_FRAME    | `u8` 0=Head, 1=Half, 2=Full                          | `TRACKING_FRAME` *(Insta360)*                                                   |
| 0x12  | TRACKING_TARGET   | `u8` 0=Single, 1=Group                               | `TRACKING_TARGET` *(Insta360)*                                                  |
| 0x13  | SCENE_MODE        | `u8` 0=Normal, 1=Whiteboard, 2=Overhead, 3=DeskView  | `SCENE_MODE` *(Insta360)*                                                       |
| 0x40  | PRESET_SAVE       | `u8` slot 0-5                                        | `PRESET_SAVE`                                                                   |
| 0x41  | PRESET_RECALL     | `u8` slot 0-5                                        | `PRESET_RECALL`                                                                 |
| 0x7F  | GET_STATUS        | utf-8 comma-separated V4L2 control names             | `GET_STATUS` (default NAMES list in `cmd.txt`)                                  |

`EXPOSURE_AUTO` uses raw V4L2 enum values (1=manual, 3=aperture-priority/auto)
via COSMOS STATEs, so the bridge does no translation.

Adding a new V4L2 control = one new `COMMAND` in `cmd.txt` (PKT_ID 0x01 + fixed
`NAME` default) and optionally extend `GET_STATUS NAMES` + matching item in
`tlm.txt`. No bridge change needed.

### Telemetry

| ID    | Packet  | Source                                                                                |
|-------|---------|---------------------------------------------------------------------------------------|
| 0x80  | STATUS  | Live `v4l2-ctl --get-ctrl` query for the names in `GET_STATUS`'s NAMES payload. Fields in `targets/UVC/cmd_tlm/tlm.txt` must appear in the same order. |

XU vendor state (AI tracking, scene mode, framing, target) is write-only over
the wire — there is no STATUS field for it until a libusb `UVC_GET_CUR` path
is wired up.

### STATUS field source-of-truth

The `NAMES` parameter on the `GET_STATUS` command (defined in `cmd.txt`)
dictates which V4L2 controls the bridge reads. The bridge has no hardcoded
list. To add or remove a STATUS field, edit `cmd.txt`'s `GET_STATUS NAMES`
default **and** the matching `APPEND_ITEM` in `tlm.txt` (same order).

## Quick Start

On the host with USB access to the camera:

```
pip install openc3 pyusb
sudo apt install v4l-utils    # Linux only
OPENC3_NO_STORE=1 python lib/uvc_bridge.py --device /dev/video0 --port 8080
```

Grant USB access for Insta360 vendor controls (Linux):

```
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2e1a", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-insta360.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Build and install the plugin:

```
<COSMOS>/openc3.sh cli rake build VERSION=1.0.0
```

Upload the `.gem` in Admin Tool > Plugins. Adjust variables (host, port, Insta360 toggle) at install time.

## Script API

```python
load_utility('UVC/lib/uvc.py')
cam = Uvc()
cam.zoom(250)
cam.pan_tilt(1500, -300)
cam.brightness(50)
cam.ai_tracking(True)            # Insta360 only
cam.tracking_frame("HALF_BODY")  # Insta360 only
cam.scene_mode("WHITEBOARD")     # Insta360 only
cam.preset_save(0)
```

Arbitrary V4L2 control via the escape hatch:

```python
cmd("UVC V4L2_SET with VALUE 100, NAME 'zoom_absolute'")
```

## License

MIT - see [LICENSE.txt](LICENSE.txt).
