# Helper for Insta360 Link / UVC camera scripts.
#
# Usage:
#   load_utility 'UVC/lib/uvc.py'
#   cam = Uvc()
#   cam.zoom(200)
#   cam.pan_tilt(1000, -500)
#   cam.ai_tracking(True)

from openc3.script import *


class Uvc:
    def __init__(self, target_name="UVC"):
        self.target = target_name

    # PTZ
    def zoom(self, value):
        cmd(f"{self.target} ZOOM with VALUE {int(value)}")

    def pan(self, value):
        cmd(f"{self.target} PAN with VALUE {int(value)}")

    def tilt(self, value):
        cmd(f"{self.target} TILT with VALUE {int(value)}")

    def pan_tilt(self, pan, tilt):
        cmd(f"{self.target} PAN with VALUE {int(pan)}")
        cmd(f"{self.target} TILT with VALUE {int(tilt)}")

    def pan_tilt_relative(self, pan_delta, tilt_delta):
        cmd(f"{self.target} PAN_TILT_RELATIVE with PAN_DELTA {int(pan_delta)}, TILT_DELTA {int(tilt_delta)}")

    def gimbal_reset(self):
        cmd(f"{self.target} GIMBAL_RESET")

    # AI tracking / scene
    def ai_tracking(self, on):
        cmd(f"{self.target} AI_TRACKING with STATE {'ON' if on else 'OFF'}")

    def tracking_frame(self, mode):
        cmd(f"{self.target} TRACKING_FRAME with FRAME {mode.upper()}")

    def tracking_target(self, target):
        cmd(f"{self.target} TRACKING_TARGET with TARGET {target.upper()}")

    def scene_mode(self, mode):
        cmd(f"{self.target} SCENE_MODE with MODE {mode.upper()}")

    # Image
    def brightness(self, value):
        cmd(f"{self.target} BRIGHTNESS with VALUE {int(value)}")

    def contrast(self, value):
        cmd(f"{self.target} CONTRAST with VALUE {int(value)}")

    def saturation(self, value):
        cmd(f"{self.target} SATURATION with VALUE {int(value)}")

    def sharpness(self, value):
        cmd(f"{self.target} SHARPNESS with VALUE {int(value)}")

    def gain(self, value):
        cmd(f"{self.target} GAIN with VALUE {int(value)}")

    def backlight(self, on):
        cmd(f"{self.target} BACKLIGHT_COMPENSATION with STATE {'ON' if on else 'OFF'}")

    # WB
    def auto_white_balance(self, on):
        cmd(f"{self.target} AUTO_WHITE_BALANCE with STATE {'ON' if on else 'OFF'}")

    def white_balance_temp(self, kelvin):
        cmd(f"{self.target} WHITE_BALANCE_TEMP with VALUE {int(kelvin)}")

    # Exposure
    def exposure_auto(self, mode):
        cmd(f"{self.target} EXPOSURE_AUTO with MODE {mode.upper()}")

    def exposure_absolute(self, value):
        cmd(f"{self.target} EXPOSURE_ABSOLUTE with VALUE {int(value)}")

    # Focus
    def auto_focus(self, on):
        cmd(f"{self.target} AUTO_FOCUS with STATE {'ON' if on else 'OFF'}")

    def focus_absolute(self, value):
        cmd(f"{self.target} FOCUS_ABSOLUTE with VALUE {int(value)}")

    # Presets
    def preset_save(self, index):
        cmd(f"{self.target} PRESET_SAVE with INDEX {int(index)}")

    def preset_recall(self, index):
        cmd(f"{self.target} PRESET_RECALL with INDEX {int(index)}")
