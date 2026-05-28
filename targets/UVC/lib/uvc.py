# Helper for UVC camera scripts.
#
# Usage:
#   load_utility('UVC/lib/uvc.py')
#   cam = Uvc()
#   cam.zoom(200)
#   cam.pan_tilt(1000, -500)
#   cam.scene_mode("AI_TRACKING")

from openc3.script import *


class Uvc:
    def __init__(self, target_name="UVC"):
        self.target = target_name

    # PTZ
    def zoom(self, value):
        cmd(f"{self.target} ZOOM with VALUE {int(value)}")

    def pan_tilt(self, pan, tilt):
        cmd(f"{self.target} PAN_TILT with PAN {int(pan)}, TILT {int(tilt)}")

    def gimbal_reset(self):
        cmd(f"{self.target} GIMBAL_RESET")

    # Insta360 vendor controls
    def scene_mode(self, mode):
        cmd(f"{self.target} SCENE_MODE with VALUE {mode.upper()}")

    def tracking_frame(self, mode):
        cmd(f"{self.target} TRACKING_FRAME with VALUE {mode.upper()}")

    def tracking_target(self, target):
        cmd(f"{self.target} TRACKING_TARGET with VALUE {target.upper()}")

    # Image
    def brightness(self, value):
        cmd(f"{self.target} BRIGHTNESS with VALUE {int(value)}")

    def contrast(self, value):
        cmd(f"{self.target} CONTRAST with VALUE {int(value)}")

    def saturation(self, value):
        cmd(f"{self.target} SATURATION with VALUE {int(value)}")

    def sharpness(self, value):
        cmd(f"{self.target} SHARPNESS with VALUE {int(value)}")
