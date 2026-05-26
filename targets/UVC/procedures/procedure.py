# Demo: quick PTZ + AI sweep on an Insta360 Link.
load_utility('UVC/lib/uvc.py')

cam = Uvc()

cam.gimbal_reset()
cam.zoom(100)
wait(1)

cam.pan_tilt(2000, 500)
wait(2)

cam.zoom(250)
wait(1)

cam.scene_mode("AI_TRACKING")
cam.tracking_frame("HALF_BODY")
cam.tracking_target("SINGLE")
wait(5)

cam.scene_mode("NORMAL")
cam.gimbal_reset()
