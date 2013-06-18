#!/usr/bin/env python

import sys
import os
from time import sleep
from datetime import datetime

import numpy as np
import cv2
import cv2.cv as cv

from camview import ensure_dir

class OutMode:
  VIDEO = 0
  IMAGE_SEQ = 1


class VideoCodec:
  AUTO = -1
  MPEG = cv.CV_FOURCC('M', 'P', 'E', 'G')
  AVC1 = cv.CV_FOURCC('A','V','C','1')
  YUV1 = cv.CV_FOURCC('Y','U','V','1')
  PIM1 = cv.CV_FOURCC('P','I','M','1')
  MJPG = cv.CV_FOURCC('M','J','P','G')
  MP42 = cv.CV_FOURCC('M','P','4','2')
  DIV3 = cv.CV_FOURCC('D','I','V','3')
  DIVX = cv.CV_FOURCC('D','I','V','X')
  U263 = cv.CV_FOURCC('U','2','6','3')
  I263 = cv.CV_FOURCC('I','2','6','3')
  FLV1 = cv.CV_FOURCC('F','L','V','1')
  H264 = cv.CV_FOURCC('H','2','6','4')
  AYUV = cv.CV_FOURCC('A','Y','U','V')
  IUYV = cv.CV_FOURCC('I','U','Y','V')
  WMV1 = cv.CV_FOURCC('W','M','V','1')


class ImageSeqWriter:
  """Saves an image sequence to timestamped directory; emulates OpenCV VideoWriter's interface (once created)."""
  def __init__(self, seqDirPath, imagePrefix="img-", imageNumDigits=4, imageSuffix=".png"):
    """Setup to write images as: <seqDirPath>/<imagePrefix>NNNN<imageSuffix>"""
    self.seqDirPath = seqDirPath
    self.imagePrefix = imagePrefix
    self.imageNumDigits = imageNumDigits
    self.imageSuffix = imageSuffix
    
    self.isOpen = False
    if ensure_dir(self.seqDirPath):
      self.isOpen = True
      print "ImageSeqWriter.__init__(): Output directory ready: \"{}\"".format(self.seqDirPath)
    else:
      print "ImageSeqWriter.__init__(): Unable to access directory: \"{}\"".format(self.seqDirPath)
    
    self.frameCount = 0
  
  def write(self, image):
    imageFilename = os.path.join(self.seqDirPath, "{prefix}{num}{suffix}".format(prefix=self.imagePrefix, num=str(self.frameCount).zfill(self.imageNumDigits), suffix=self.imageSuffix))
    try:
      cv2.imwrite(imageFilename, image)
      print "ImageSeqWriter.write(): Image saved to \"{}\"".format(imageFilename)
      self.frameCount += 1
    except:
      print "ImageSeqWriter.write(): Unable to save image to \"{}\"".format(imageFilename)
      raise
  
  def isOpened(self):
    return self.isOpen
  
  def release(self):
    print "ImageSeqWriter.release(): {} images saved to \"{}\"".format(self.frameCount, self.seqDirPath)


def cammon():
  """Monitor and store image stream from camera/video file."""
  cameraWidth, cameraHeight = (640, 480)
  targetRateFrames, targetRateSecs = (1, 3)
  targetFPS = targetRateFrames / float(targetRateSecs)
  targetDeltaTime = 1 / targetFPS
  
  maxFrames = 100
  totalDuration = 120  # secs.
  if totalDuration * targetFPS > maxFrames:
    totalDuration = maxFrames / targetFPS
  
  debug = True
  gui = True
  delay = 10  # ms
  delayS = delay / 1000.0  # sec
  
  outDir = "out"
  outMode = OutMode.IMAGE_SEQ
  outVideoPrefix = "vid_"
  outVideoSuffix = ".mpeg"
  outVideoCodec = VideoCodec.MPEG
  outVideoFPS = 30
  outSeqPrefix = "seq_"
  outSnapPrefix = "snap_"
  outSnapSuffix = ".png"
  
  print "CAMera MONitor (OpenCV " + cv2.__version__ + ")"
  device = 0
  isVideo = False
  if len(sys.argv) <= 1:
    print "Usage: " + sys.argv[0] + " [<device_number> | <video_filename>]"
  else:
    try:
      device = int(sys.argv[1])  # works if sys.argv[1] is an int (device no.)
    except ValueError:
      device = sys.argv[1]  # fallback: treat sys.argv[1] as string (filename)
      isVideo = True
  
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
  
  if debug:
    print "Target FPS: {}/{} = {}".format(targetRateFrames, targetRateSecs, targetFPS)
    print "Total duration: {} secs.".format(totalDuration)
  
  if gui:
    print "Press ESC or Q to quit, SPACE to pause, S to take snapshot..."
  
  isOkay = True
  isFresh = True
  videoOut = None
  frameCount = 0
  avgFPS = 0.0
  timeNow = 0.0
  timeLast = -targetDeltaTime  # to force first frame to be saved
  timeStart = cv2.getTickCount() / cv2.getTickFrequency()
  
  while isOkay:
    timeNow = (cv2.getTickCount() / cv2.getTickFrequency()) - timeStart
    if timeNow > totalDuration:
      break
    timeDiff = (timeNow - timeLast)
    
    _, image = camera.read()
    if image is None:
      break
    
    if isFresh:
      isFresh = False
      imageSize = (image.shape[1], image.shape[0])
      print "Image size: {}x{}".format(imageSize[0], imageSize[1])
      
      if not ensure_dir(outDir):
        print "Unable to access output directory \"{}\"; video will not be recorded".format(outDir)
      else:
        if outMode == OutMode.VIDEO:
          timestamp = datetime.now()
          outVideoFilename = os.path.join(outDir, outVideoPrefix + "{:%Y-%m-%d_%H-%M-%S}".format(timestamp) + outVideoSuffix)
          videoOut = cv2.VideoWriter(outVideoFilename, outVideoCodec, outVideoFPS, imageSize)
          if videoOut is not None and videoOut.isOpened():
            print "Initialized output video file \"{}\"".format(outVideoFilename)
          else:
            print "Unable to initialize video file \"{}\"; video will not be recorded".format(outVideoFilename)
            videoOut = None
        elif outMode == OutMode.IMAGE_SEQ:
          timestamp = datetime.now()
          outSeqDirPath = os.path.join(outDir, "{prefix}{tstamp:%Y-%m-%d_%H-%M-%S}".format(prefix=outSeqPrefix, tstamp=timestamp))  # write images to: <outDir>/<seqPrefix>yyyy-mm-dd_HH-MM-SS/
          videoOut = ImageSeqWriter(outSeqDirPath)
          if videoOut is not None and videoOut.isOpened():
            print "Initialized output image sequence directory \"{}\"".format(outSeqDirPath)
          else:
            print "Unable to initialize image sequence directory \"{}\"; images will not be recorded".format(outSeqDirPath)
            videoOut = None
    
    if timeDiff >= targetDeltaTime:
      if debug:
        currentFPS = (1.0 / timeDiff) if (timeDiff > 0.0) else 0.0
        avgFPS = frameCount / timeNow
        print "[{:6.2f}] Frame {}: {:5.2f} fps ({:5.2f} avg.)".format(timeNow, frameCount, currentFPS, avgFPS)
    
      if videoOut is not None:
        try:
          videoOut.write(image)
        except:
          print "Error storing image; aborting..."
          break
      
      frameCount += 1
      #timeLast = timeNow  # NOTE: This method is error prone, as time delay will accumulate
      timeLast += targetDeltaTime
    
    if gui:
      cv2.imshow("Camera", image)
      key = cv2.waitKey(delay)
      if key != -1:
        keyCode = key & 0xff
        keyChar = chr(keyCode)
        print "Key: {} ({})".format(keyChar, keyCode)
        if keyCode == 0x1b or keyChar == 'q' or keyChar == 'S':  # quit
          isOkay = False
        elif keyChar == ' ':  # pause
          print "Paused; press any key to continue..."
          cv2.waitKey()
          durationPaused = (cv2.getTickCount() / cv2.getTickFrequency()) - timeNow
          timeStart += durationPaused
          print "Resumed after {} secs.".format(durationPaused)
        elif keyChar == 's' or keyChar == 'S':  # take snapshot
          if not ensure_dir(outDir):
            print "Unable to access snapshot directory \"{}\"".format(outDir)
          else:
            timestamp = datetime.now()
            outSnapFilename = os.path.join(outDir, outSnapPrefix + "{:%Y-%m-%d_%H-%M-%S}".format(timestamp) + outSnapSuffix)
            try:
              cv2.imwrite(outSnapFilename, image)
              print "Snapshot saved to \"{}\"".format(outSnapFilename)
            except Exception:
              print "Unable to save snapshot to \"{}\"".format(outSnapFilename)
    else:
      sleep(delayS)
  
  avgFPS = frameCount / timeNow
  print "Done; %d frames, %.2f secs, %.2f fps (avg.)" % (frameCount, timeNow, avgFPS)
  
  if videoOut is not None:
    videoOut.release()
  camera.release()


if __name__ == "__main__":
  cammon()
