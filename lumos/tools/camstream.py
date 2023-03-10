#!/usr/bin/env python

import os
from ctypes import c_bool, c_ubyte, c_int
from multiprocessing import Process, Value, Array

import numpy as np
from numpy import ctypeslib
import cv2

camera_frame_width = 1280
camera_frame_height = 720
camera_frame_depth = 3
frame_delay = 20

class CameraStreamer(Process):
  def __init__(self, stayAliveObj=None, frameCountObj=None, imageObj=None, imageShapeObj=None):
    Process.__init__(self)
    print "CameraStreamer.__init__(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
    # * Store references to and/or create shared objects
    self.stayAliveObj = stayAliveObj if stayAliveObj is not None else Value(c_bool, True)
    self.frameCountObj = frameCountObj if frameCountObj is not None else Value('i', 0)
    self.imageShapeObj = imageShapeObj if imageShapeObj is not None else Array('i', (camera_frame_height, camera_frame_width, camera_frame_depth))
    if imageObj is not None:
      # ** Use supplied shared image object
      self.imageObj = imageObj
    else:
      # ** Create shared image object
      image = np.zeros((camera_frame_height, camera_frame_width, camera_frame_depth), dtype=np.uint8)  # create an image
      imageShape = image.shape  # store original shape
      imageSize = image.size  # store original size (in bytes)
      image.shape = imageSize  # flatten numpy array
      self.imageObj = Array(c_ubyte, image)  # create a synchronized shared array object
  
  def run(self):
    print "CameraStreamer.run(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
    # * Interpret shared objects properly (NOTE this needs to happen in the child process)
    self.image = ctypeslib.as_array(self.imageObj.get_obj())  # get flattened image array
    self.image.shape = ctypeslib.as_array(self.imageShapeObj.get_obj())  # restore original shape
    
    # * Open camera and set desired capture properties
    self.camera = cv2.VideoCapture(0)
    if self.camera.isOpened():
      result_width = self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, camera_frame_width)
      result_height = self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_frame_height)
      print "CameraStreamer.run(): Camera frame size set to {width}x{height} (result: {result_width}, {result_height})".format(width=camera_frame_width, height=camera_frame_height, result_width=result_width, result_height=result_height)
    else:
      print "CameraStreamer.run(): Unable to open camera; aborting..."
      self.stayAliveObj.value = False
      return
    
    # * Keep reading frames into shared image until stopped or read error occurs
    while self.stayAliveObj.value:
      try:
        #print "CameraStreamer.run(): Frame # {}, stay alive? {}".format(self.frameCountObj.value, self.stayAliveObj.value)  # [debug]
        isOkay, frame = self.camera.read()
        if not isOkay or frame is None:
          self.stayAliveObj.value = False
        else:
          self.frameCountObj.value = self.frameCountObj.value + 1
          self.image[:] = frame
      except KeyboardInterrupt:
        self.stayAliveObj.value = False
    
    # * Clean-up
    self.camera.release()


class StreamViewer(Process):
  def __init__(self, stayAliveObj, frameCountObj, imageObj, imageShapeObj):
    Process.__init__(self)
    print "StreamViewer.__init__(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
    self.stayAliveObj = stayAliveObj
    self.frameCountObj = frameCountObj
    self.imageShapeObj = imageShapeObj
    self.imageObj = imageObj
    self.lastFrameCount = -1
  
  def run(self):
    print "StreamViewer.run(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
    # * Interpret shared objects properly (NOTE this needs to happen in the child process)
    self.image = ctypeslib.as_array(self.imageObj.get_obj())  # get flattened image array
    self.image.shape = ctypeslib.as_array(self.imageShapeObj.get_obj())  # restore original shape
    
    print "StreamViewer.run(): Starting display loop [Esc or Q to quit]..."
    while self.stayAliveObj.value:
      try:
        if self.frameCountObj.value != self.lastFrameCount:
          cv2.imshow("Image", self.image)
          self.lastFrameCount = self.frameCountObj.value
        key = cv2.waitKey(frame_delay)
        if key != -1:
          keyCode = key & 0x00007f
          keyChar = chr(keyCode)
          if keyCode == 0x1b or keyChar == 'q':
              self.stayAliveObj.value = False
      except KeyboardInterrupt:
        self.stayAliveObj.value = False


def camstream():
  print "CAMera STREAMer (OpenCV " + cv2.__version__ + ")"
  print "main(): OS: {}".format(os.name)
  
  # * Start CameraStreamer process
  print "main(): Starting CameraStreamer process..."
  if os.name == 'nt':  # [Windows]
    # ** Create shared objects (NOTE only necessary on Windows since it uses a different multiprocessing implementation)
    print "main(): [Windows] Creating shared objects..."
    # *** Stay alive flag
    stayAliveObj = Value(c_bool, True)
    
    # *** Frame counter
    frameCountObj = Value('i', 0)
    
    # *** Image array
    image = np.zeros((camera_frame_height, camera_frame_width, camera_frame_depth), dtype=np.uint8)
    imageShape = image.shape
    imageSize = image.size
    image.shape = imageSize  # flatten numpy array
    imageObj = Array(c_ubyte, image)  # create a synchronized shared array
    
    # *** Image shape
    imageShapeObj = Array('i', imageShape)
    cameraStreamerProcess = CameraStreamer(stayAliveObj, frameCountObj, imageObj, imageShapeObj)
  else:  # [POSIX]
    cameraStreamerProcess = CameraStreamer()
    # ** Grab generated shared objects to share with other child processes
    print "main(): [POSIX] Getting shared objects from CameraStreamer..."
    stayAliveObj = cameraStreamerProcess.stayAliveObj
    frameCountObj = cameraStreamerProcess.frameCountObj
    imageObj = cameraStreamerProcess.imageObj
    imageShapeObj = cameraStreamerProcess.imageShapeObj
  cameraStreamerProcess.start()
  
  # * Start StreamViewer process
  print "main(): Starting StreamViewer process..."
  streamViewerProcess = StreamViewer(stayAliveObj, frameCountObj, imageObj, imageShapeObj)
  streamViewerProcess.start()
  
  # * Wait for child processes to finish
  print "main(): Waiting for child processes to finish..."
  try:
    streamViewerProcess.join()
    cameraStreamerProcess.join()
  except KeyboardInterrupt:
    stayAliveObj.value = False
    streamViewerProcess.join()
    cameraStreamerProcess.join()
  print "main(): Done."


if __name__ == '__main__':
  camstream()
