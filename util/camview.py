#!/usr/bin/env python

import sys
import os
from datetime import datetime

import numpy as np
import cv2
import cv2.cv as cv

defaultCameraWidth = 320
defaultCameraHeight = 240
defaultDelay = 15

def ensure_dir(path):
  """Ensure a directory exists at given path; if not, try to create it."""
  if os.path.isdir(path):
    return True
  
  try:
    print "Creating directory \"{}\"".format(path)
    os.makedirs(path)
    return True
  except OSError:
    print "Unable to create directory!"
    return False


def camview():
  """View image stream from camera/video file."""
  cameraWidth, cameraHeight = (defaultCameraWidth, defaultCameraHeight)
  delay = defaultDelay
  outDir = "out"
  outFilePrefix = "snap_"
  outFileSuffix = ".png"
  
  print "CAMera VIEWer (OpenCV " + cv2.__version__ + ")"
  device = 0
  isVideo = False
  if len(sys.argv) <= 1:
    print "Usage: " + sys.argv[0] + " [<device_number> | <video_filename> [<frame_delay> [<width> [<height>]]]]"
  else:
    try:
      device = int(sys.argv[1])  # works if sys.argv[1] is an int (device no.)
    except ValueError:
      device = sys.argv[1]  # fallback: treat sys.argv[1] as string (filename)
      isVideo = True
    
    if len(sys.argv) > 2:
      try:
        delay = int(sys.argv[2])
      except ValueError:
        delay = defaultDelay
    
    # If this is a live input device (camera), then look for width and height
    if not isVideo and len(sys.argv) > 3:
      try:
        cameraWidth = int(sys.argv[3])
        if len(sys.argv) > 4:
          cameraHeight = int(sys.argv[4])
        else:
          cameraHeight = int(cameraWidth * defaultCameraHeight / defaultCameraWidth)
      except ValueError:
        cameraWidth, cameraHeight = (defaultCameraWidth, defaultCameraHeight)
  
  print "{}: {}".format("Video file" if isVideo else "Device no.", device)
  camera = cv2.VideoCapture(device)
  if camera is None or not camera.isOpened():
    print "Unable to open {}!".format("video file" if isVideo else "camera")
    return
  
  if not isVideo:
    camera.set(cv.CV_CAP_PROP_FRAME_WIDTH, cameraWidth)
    camera.set(cv.CV_CAP_PROP_FRAME_HEIGHT, cameraHeight)
    _, image = camera.read()  # test read image
    cameraWidth = int(camera.get(cv.CV_CAP_PROP_FRAME_WIDTH))
    cameraHeight = int(camera.get(cv.CV_CAP_PROP_FRAME_HEIGHT))
    print "Camera frame size: {}x{}".format(cameraWidth, cameraHeight)
  
  print "Press ESC or Q to quit, SPACE to pause, S to take snapshot..."
  isOkay = True
  isFresh = True
  while isOkay:
    _, image = camera.read()
    if image is None:
      break
    
    if isFresh:
      isFresh = False
      imageSize = (image.shape[1], image.shape[0])
      print "Image size: {}x{}".format(imageSize[0], imageSize[1])
    
    cv2.imshow("Camera", image)
    key = cv2.waitKey(delay)
    if key != -1:
      keyCode = key & 0xff
      keyChar = chr(keyCode)
      print "Key: {} ({})".format(keyChar, keyCode)
      if keyCode == 0x1b or keyChar == 'q' or keyChar == 'S':  # quit
        isOkay = False
      elif keyChar == ' ':  # pause
        print "[PAUSED] Press any key to continue..."
        cv2.waitKey()
        print "[RESUMED]"
      elif keyChar == 's' or keyChar == 'S':  # take snapshot
        if not ensure_dir(outDir):
          print "Unable to access snapshot directory \"{}\"".format(outDir)
        else:
          timestamp = datetime.now()
          outFilename = os.path.join(outDir, outFilePrefix + "{:%Y-%m-%d_%H-%M-%S}".format(timestamp) + outFileSuffix)
          try:
            cv2.imwrite(outFilename, image)
            print "Snapshot saved to \"{}\"".format(outFilename)
          except Exception:
            print "Unable to save snapshot to \"{}\"".format(outFilename)
  
  print "Done."
  camera.release()


if __name__ == "__main__":
  camview()
