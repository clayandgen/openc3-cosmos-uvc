# Sweep the camera in a zig-zag pattern.
#
# Pan left -> right at one tilt row, advance tilt, pan right -> left, repeat.
load_utility('UVC/lib/uvc.py')

cam = Uvc()

PAN_MAX     = 200000   # 1/3600 degree units (UVC PANTILT_ABSOLUTE)
TILT_START  = -100000
TILT_STEP   = 40000
ROWS        = 5
DWELL       = 0.5      # seconds at each waypoint

cam.gimbal_reset()
wait(1)

for row in range(ROWS):
    tilt = TILT_START + row * TILT_STEP
    if row % 2 == 0:
        left, right = -PAN_MAX, PAN_MAX
    else:
        left, right = PAN_MAX, -PAN_MAX
    cam.pan_tilt(left, tilt)
    wait(DWELL)
    cam.pan_tilt(right, tilt)
    wait(DWELL)

cam.gimbal_reset()
