"""Components to help manage image input sources."""

# Python imports
import sys
from time import sleep
import logging
import types

# NumPy, OpenCV imports
import numpy as np
import cv2

# Custom imports
from .util import KeyCode
from .context import Context
from .base import FrameProcessor


class InputDevice(object):
  """Abstracts away the handling of static image, recorded video files and live camera as input."""
  
  def __init__(self):
    # * Grab application context, logger and check if we have a valid input source
    self.context = Context.getInstance()
    self.logger = logging.getLogger(self.__class__.__name__)
    self.isOkay = False  # conservative assumption: not okay till we're ready
    if self.context.options.input_source is None:
      raise Exception("No valid input source, nothing to do!")
    
    # * Open input source
    if self.context.isImage:
      self.camera = cv2.imread(self.context.options.input_source)
      if self.camera is None:
        raise Exception("Error opening input image file")
    elif self.context.isRemote:
      from net import ImageClient  # to prevent circular dependency
      self.camera = ImageClient(protocol=self.context.remoteEndpoint['protocol'], host=self.context.remoteEndpoint['host'], port=self.context.remoteEndpoint['port'])
      # TODO Allow custom read_call param via command-line arg --rpc_read_call (or remoteEndpoint['path']?)
      # TODO Add ability to read remote URLs by (use a common isStatic flag for local and remote images)
    else:
      self.camera = cv2.VideoCapture(self.context.options.input_source)
      if self.camera is None or not self.camera.isOpened():
        raise Exception("Error opening camera / input video file")
    
    # * Acquire logger and initialize other members
    self.logger = logging.getLogger(self.__class__.__name__)
    self.frameCount = 0
    self.frameTimeStart = self.context.timeNow  # synced with context
    self.timeDelta = 0.0
    
    # * Set camera frame size (if this is a live camera; TODO enable frame resizing for videos and static images as well?)
    if not (self.context.isImage or self.context.isVideo or self.context.isRemote):
      #_, self.image = self.camera.read()  # pre-grab
      # NOTE: If camera frame size is not one supported by the hardware, grabbed images are scaled to desired size, discarding aspect-ratio
      try:
        if self.context.options.camera_width != 'auto':
          self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.context.options.camera_width))
        if self.context.options.camera_height != 'auto':
          self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.context.options.camera_height))
      except ValueError:
        self.logger.warning("Ignoring invalid camera frame size: {}x{}".format(self.context.options.camera_width, self.context.options.camera_height))
    
    # * Check if this is a static image or camera/video/remote endpoint
    if self.context.isImage:
      # ** Supplied camera object should be an image, copy it
      self.image = self.camera
    else:
      if self.context.isVideo:
        # ** Read video properties, set video-specific variables
        self.videoNumFrames = int(self.camera.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.context.options.video_fps == 'auto':
          self.videoFPS = self.camera.get(cv2.CAP_PROP_FPS)
        else:
          try:
            self.videoFPS = float(self.context.options.video_fps)
          except ValueError:
            self.logger.warning("Invalid video FPS \"{}\"; switching to auto".format(self.self.context.options.video_fps))
            self.videoFPS = self.camera.get(cv2.CAP_PROP_FPS)
        self.videoDuration = self.videoNumFrames / self.videoFPS
        self.logger.info("Video [init]: {:.3f} secs., {} frames at {:.2f} fps{}".format(self.videoDuration, self.videoNumFrames, self.videoFPS, (" (sync target)" if self.context.options.sync_video else "")))
        if self.context.options.sync_video:
          self.videoFramesRepeated = 0
          self.videoFramesSkipped = 0
      
      # ** Grab test image and read common camera/video properties
      self.readFrame()  # post-grab (to apply any camera prop changes made)
      if not self.context.isRemote:
        self.logger.info("Frame size: {}x{}".format(int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))))
      if self.context.isVideo:
        self.resetVideo()
    
    # * Read image properties (common to static image/camera/video)
    if self.image is not None:
      self.imageSize = (self.image.shape[1], self.image.shape[0])
      self.logger.info("Image size: {}x{}".format(self.imageSize[0], self.imageSize[1]))
      self.isOkay = True  # all good, so far
    else:
      self.logger.error("Empty image!")
  
  def readFrame(self):
    """Read a frame from camera/video. Not meant to be called directly."""
    if self.context.isVideo and self.context.options.loop_video and self.frameCount >= self.videoNumFrames:
      framesDelivered = self.frameCount + self.videoFramesRepeated - self.videoFramesSkipped if self.context.options.sync_video else self.frameCount
      self.logger.info("Video [loop]: {:.3f} secs., {} frames at {:.2f} fps{}".format(
        self.timeDelta,
        framesDelivered,
        (framesDelivered / self.timeDelta) if self.timeDelta > 0.0 else 0.0,
        (" ({} repeated, {} skipped)".format(self.videoFramesRepeated, self.videoFramesSkipped) if self.context.options.sync_video else "")))
      self.resetVideo()
      if self.context.options.sync_video:
        self.videoFramesRepeated = 0
        self.videoFramesSkipped = 0
    
    self.isOkay, self.image = self.camera.read()
    self.frameCount += 1
  
  def read(self):
    """Read a frame from image/camera/video, handling video sync and loop."""
    self.timeDelta = self.context.timeNow - self.frameTimeStart  # synced with context
    
    if not self.context.isImage:
      if self.context.isVideo and self.context.options.sync_video:
        targetFrameCount = self.videoFPS * self.timeDelta
        diffFrameCount = targetFrameCount - self.frameCount
        #self.logger.debug("[syncVideo] timeDelta: {:06.3f}, frame: {:03d}, target: {:06.2f}, diff: {:+04.2f}".format(self.timeDelta, self.frameCount, targetFrameCount, diffFrameCount))
        if diffFrameCount <= 0:
          self.videoFramesRepeated += 1
        else:
          self.videoFramesSkipped += min(int(diffFrameCount), self.videoNumFrames - self.frameCount)
          while self.isOkay and self.frameCount < targetFrameCount:
            self.readFrame()
            if self.frameCount == 1:  # a video reset occurred
              break
      else:
        self.readFrame()
    
    return self.isOkay
  
  def resetVideo(self):
    self.camera.set(cv2.CAP_PROP_POS_FRAMES, 0)
    self.frameCount = 0
    self.frameTimeStart = self.context.timeNow  # synced with context
    self.timeDelta = 0.0
    # NOTE Depending on the actual keyframes in the video, a reset may not work correctly (some frames towards the end may be skipped everytime after the first reset)
  
  def close(self):
    if not self.context.isImage:  # not valid for static images
      self.camera.release()


class Projector(FrameProcessor):
  """An input manager that can select a window within a given image stream, with a movable point of focus."""
  
  key_focus_jump = 10  # no. of pixels to shift focus under (manual) keyboard control
  default_screen_background = np.uint8([128, 128, 128])  # what should the area outside the source image stream be treated as
  
  def __init__(self, target=None, screen_background=default_screen_background):
    FrameProcessor.__init__(self)
    self.target = target if target is not None else FrameProcessor()
    self.screen_background = screen_background
  
  def initialize(self, imageIn, timeNow):
    FrameProcessor.initialize(self, imageIn, timeNow)
    self.target.initialize(imageIn, timeNow)  # call through
    self.screenSize = (self.imageSize[0] + 2 * self.target.imageSize[0], self.imageSize[1] + 2 * self.target.imageSize[1])  # create a screen which is big enough to accomodate input image and allow panning focus to the edges
    self.logger.debug("Screen size: {}".format(self.screenSize))
    self.screen = np.zeros((self.screenSize[1], self.screenSize[0], 3), dtype=np.uint8)
    self.screen[:, :] = self.screen_background
    self.updateImageRect()
    self.lastFocusPoint = (-1, -1)
    self.centerFocus()  # calls updateFocusRect(), sets lastFocusPoint
  
  def process(self, imageIn, timeNow):
    self.image = imageIn
    self.timeNow = timeNow
    # Copy image to screen, and send part of screen to target (TODO optimize this to a single step?)
    self.screen[self.imageRect[2]:self.imageRect[3], self.imageRect[0]:self.imageRect[1]] = self.image
    #if self.context.options.gui: cv2.imshow("Screen", self.screen)  # [debug]
    self.targetImage = self.screen[self.focusRect[2]:self.focusRect[3], self.focusRect[0]:self.focusRect[1]]
    #if self.context.options.gui: cv2.imshow("Target", self.targetImage)  # [debug]
    return self.target.process(self.targetImage, timeNow)
  
  def onKeyPress(self, key, keyChar=None):
    if keyChar == 'w':
      self.shiftFocus(deltaY=-self.key_focus_jump)
    elif keyChar == 's':
      self.shiftFocus(deltaY=self.key_focus_jump)
    elif keyChar == 'a':
      self.shiftFocus(deltaX=-self.key_focus_jump)
    elif keyChar == 'd':
      self.shiftFocus(deltaX=self.key_focus_jump)
    elif keyChar == 'c':
      self.centerFocus()
    return True
  
  def updateImageRect(self):
    # Compute image rect bounds - constant screen area where image is copied: (left, right, top, bottom)
    # TODO Ensure rect format (left, right, top, bottom) doesn't clash with OpenCV convention (left, top, width, height)
    #      Or, create a versatile utility class Rect with appropriate properties and conversions
    left = self.screenSize[0] / 2 - self.imageSize[0] / 2
    top = self.screenSize[1] / 2 - self.imageSize[1] / 2
    self.imageRect = np.int_([left, left + self.imageSize[0], top, top + self.imageSize[1]])
    #self.logger.debug("Image rect: {}".format(self.imageRect))  # [verbose]
  
  def shiftFocus(self, deltaX=0, deltaY=0):
    return self.setFocus(self.focusPoint[0] + deltaX, self.focusPoint[1] + deltaY)
  
  def centerFocus(self):
    return self.setFocus(self.screenSize[0] / 2, self.screenSize[1] / 2)
  
  def setFocus(self, x, y):
    self.focusPoint = (np.clip(x, self.imageRect[0], self.imageRect[1] - 1), np.clip(y, self.imageRect[2], self.imageRect[3] - 1))
    self.updateFocusRect()
    if self.focusPoint[0] == self.lastFocusPoint[0] and self.focusPoint[1] == self.lastFocusPoint[1]:
      return False  # no actual shift occurred
    else:
      #self.logger.debug("Focus shifted from {} to {}".format(self.lastFocusPoint, self.focusPoint))  # [verbose]
      self.lastFocusPoint = self.focusPoint
      return True
  
  def updateFocusRect(self):
    # Compute focus rect bounds - varying screen area that is copied to target: (left, right, top, bottom)
    left = self.focusPoint[0] - self.target.imageSize[0] / 2
    top = self.focusPoint[1] - self.target.imageSize[1] / 2
    self.focusRect = np.int_([left, left + self.target.imageSize[0], top, top + self.target.imageSize[1]])
    self.logger.debug("Focus rect: {}".format(self.focusRect))


class InputRunner(object):
  """Runs a FrameProcessor instance on a static image (repeatedly) or on frames from a camera/video."""
  
  def __init__(self, processor=None):
    self.processor = processor  # NOTE either a type or an instance can be supplied
    
    # * Get context, logger
    self.context = Context.getInstance()
    self.logger = logging.getLogger(self.__class__.__name__)
    
    # * Initialize parameters and flags
    self.delayS = self.context.options.delay / 1000.0 if self.context.options.delay is not None else None  # sec; only used in non-GUI mode, so this can be set to 0
    self.showInput = self.context.options.gui and True
    self.showOutput = self.context.options.gui and True
    self.showFPS = False
    self.showKeys = False
    self.isFrozen = False
    self.fresh = True
    self.timeLast = self.context.timeNow
    
    # * Initialize input device
    try:
      self.inputDevice = InputDevice()  # grabs options from context
      if not self.inputDevice.isOkay:
        raise Exception("No camera / incorrect filename / missing video codec?")
    except Exception as e:
      self.logger.error("Unable to open input source: {}; aborting... [Error: {}]".format(self.context.options.input_source, e))
      return
    else:
      self.logger.info("Opened input source: {}".format(self.context.options.input_source))
    
    # * Instantiate processor if necessary, using basic FrameProcessor class if None was supplied
    if self.processor is None:
      self.processor = FrameProcessor
    if isinstance(self.processor, type) or isinstance(self.processor, types.ClassType):
      self.processor = self.processor()
  
  def update(self):
    """Perform a single update iteration, return True/False to indicate continuation/exit."""
    
    try:
      # ** [timing] Obtain relative timestamp for this loop iteration
      self.context.update()  # NOTE this will be a duplicate update for applications that manage context externally
      if self.showFPS:
        timeDiff = (self.context.timeNow - self.timeLast)
        fps = (1.0 / timeDiff) if (timeDiff > 0.0) else 0.0
        self.logger.info("{0:5.2f} fps".format(fps))
      
      # ** Read frame from input device
      if not self.isFrozen:
        if not self.inputDevice.isOkay or not self.inputDevice.read():
          return False  # camera disconnected or reached end of video
        
        if self.showInput:
          cv2.imshow("Input", self.inputDevice.image)
      
      # ** Initialize FrameProcessor, if required
      if(self.fresh):
        self.processor.initialize(self.inputDevice.image, self.context.timeNow) # timeNow should be ~zero on initialize
        self.fresh = False
      
      # ** Process frame
      keepRunning, imageOut = self.processor.process(self.inputDevice.image, self.context.timeNow)
      
      # ** Show output image
      if self.showOutput and imageOut is not None:
        cv2.imshow("Output", imageOut)
      if not keepRunning:
        return False  # if a FrameProcessor signals us to stop, we stop (break out of main processing loop)
      
      # ** Check if GUI is available
      if self.context.options.gui:
        # *** If so, wait for inter-frame delay and process keyboard events using OpenCV
        key = cv2.waitKey(self.context.options.delay)
        if key != -1:
          keyCode = key & 0x00007f  # key code is in the last 8 bits, pick 7 bits for correct ASCII interpretation (8th bit indicates ?)
          keyChar = chr(keyCode) if not (key & KeyCode.SPECIAL) else None  # if keyCode is normal, convert to char (str)
          
          if self.showKeys:
            self.logger.info("Key: " + KeyCode.describeKey(key))
            #self.logger.info("key = {key:#06x}, keyCode = {keyCode}, keyChar = {keyChar}".format(key=key, keyCode=keyCode, keyChar=keyChar))
          
          if keyCode == 0x1b or keyChar == 'q':
            return False
          elif keyChar == ' ':
            self.logger.info("[PAUSED] Press any key to continue...")
            self.context.pause()  # [timing] saves timestamp when paused
            cv2.waitKey()  # wait indefinitely for a key press
            self.context.resume()  # [timing] compensates for duration paused
            self.logger.info("[RESUMED]")
          elif keyCode == 0x0d or keyCode == 0x0a:
            self.isFrozen = not self.isFrozen  # freeze frame, but keep processors running
            self.logger.info("Input {} at {:.2f}".format("frozen" if self.isFrozen else "thawed", self.context.timeNow))
          elif keyChar == 'f':
            self.showFPS = not self.showFPS
          elif keyChar == 'k':
            self.showKeys = not self.showKeys
          elif keyChar == 'i':
            self.showInput = not self.showInput
            if not self.showInput:
              cv2.destroyWindow("Input")
          elif keyChar == 'o':
            self.showOutput = not self.showOutput
            if not self.showOutput:
              cv2.destroyWindow("Output")
          elif not self.processor.onKeyPress(key, keyChar):
            return False
      elif self.delayS is not None:
        # *** Else, wait for inter-frame delay using system method
        sleep(self.delayS)
      
      # ** [timing] Save timestamp for fps calculation
      self.timeLast = self.context.timeNow
    except KeyboardInterrupt:
      self.logger.info("Interrupted!")
      return False
    
    return True  # keep looping
  
  def cleanUp(self):
    self.logger.debug("Cleaning up...")
    #if self.context.options.gui:
    #  cv2.destroyAllWindows()  # fails if no windows have been created
    self.inputDevice.close()


def run(processor=Projector, description="A demo computer vision application", parent_argparsers=[], resetContextTime=True):
  # * Create application context and input runner
  context = Context.createInstance(description=description, parent_argparsers=parent_argparsers)
  runner = InputRunner(processor)
  
  # * Start processing loop
  if resetContextTime:
    context.resetTime()  # start afresh
  else:
    context.update()  # start with existing value (useful when running through multiple inputs in the same context)
  
  while runner.update():
    pass  # nothing else to do; stop when runner.update() returns False
  
  # * Clean-up
  runner.cleanUp()


if __name__ == "__main__":
  run()
