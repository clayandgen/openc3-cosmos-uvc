# Demo script: drives the camera through a quick PTZ + AI sweep.
load_utility('UVC/lib/uvc.py')

cam = Uvc()

cam.gimbal_reset()
cam.zoom(100)
wait(1)

cam.pan(2000)
cam.tilt(500)
wait(2)

cam.zoom(250)
wait(1)

cam.ai_tracking(True)
cam.tracking_frame("HALF_BODY")
cam.tracking_target("SINGLE")
wait(5)

cam.ai_tracking(False)
cam.scene_mode("NORMAL")
cam.gimbal_reset()
