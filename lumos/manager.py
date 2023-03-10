"""Driver code for running one or more FrameProcessors in a pipeline.

Basic usage: python manager.py [<image/video filename> | <camera_device_num>]
More options: python manager.py --help

"""

import sys
from time import sleep
import logging
import argparse
import signal

import numpy as np
import cv2

from .util import KeyCode, isImageFile, log_str, rotateImage
from .context import Context
from .input import InputDevice
from .base import FrameProcessor, FrameProcessorPipeline
from .filter.colorfilter import ColorFilterProcessor
from .track.blobtracking import BlobTracker


class PipelineManager:
  def __init__(self, processorTypes=None, description="A demo computer vision application", parent_argparsers=[]):
    # * Create application context, passing in custom arguments, and get a logger
    argParser = argparse.ArgumentParser(add_help=False)
    argParser.add_argument('--filter-bank', type=str, default=ColorFilterProcessor.defaultFilterBankFilename, help="color filter bank to use")
    parent_argparsers.append(argParser)  # TODO collect all argParsers from supplied processorTypes?
    self.context = Context.createInstance(description=description, parent_argparsers=parent_argparsers)
    self.logger = logging.getLogger(__name__)
    
    # * Initialize input device
    self.inputDevice = None
    try:
      self.inputDevice = InputDevice()  # grabs options from context
      if not self.inputDevice.isOkay:
        raise Exception("No camera / incorrect filename / missing video codec?")
    except Exception:
      self.logger.error("Unable to open input source: {}; aborting...".format(self.context.options.input_source))
      raise
    else:
      self.logger.info("Opened input source: {}".format(self.context.options.input_source))
    
    # * Create pipeline(s) of FrameProcessor objects, initialize supporting variables
    if processorTypes is None:
      processorTypes = [ColorFilterProcessor, BlobTracker]  # blob tracking pipeline
    self.pipeline = FrameProcessorPipeline(processorTypes)
    
    # * Example: Get references to specific processors for fast access
    #colorFilter = self.pipeline.getProcessorByType(ColorFilterProcessor)
    #blobTracker = self.pipeline.getProcessorByType(BlobTracker)
  
  def start(self):
    """Create FrameProcessor objects and start vision loop (works on a static image, video or camera input)."""
    # * Initialize parameters and flags
    delay = 10  # ms; only used in GUI mode, needed to process window events
    delayS = delay / 1000.0  # sec; only used in non-GUI mode, so this can be set to 0
    showInput = self.context.options.gui and True
    showOutput = self.context.options.gui and True
    showFPS = False
    showKeys = False
    isFrozen = False
    
    # * Set signal handler before starting vision loop (NOTE must be done in the main thread of this process)
    signal.signal(signal.SIGTERM, self.handleSignal)
    signal.signal(signal.SIGINT, self.handleSignal)
    
    # * Vision loop
    self.logger.info("Starting vision loop...")
    self.isOkay = True
    frameCount = 0  # TODO get frameCount directly from inputDevice
    fresh = True
    self.context.resetTime()  # start afresh
    timeLast = self.context.timeNow
    while self.isOkay:
      # ** [timing] Obtain relative timestamp for this loop iteration
      self.context.update()
      
      # ** Print any pre-frame messages
      if not self.context.options.gui:
        self.logger.info("[LOOP] Frame: {0:05d}, time: {1:07.3f}".format(frameCount, self.context.timeNow))  # if no GUI, print something to show we are running
      if showFPS:
        timeDiff = (self.context.timeNow - timeLast)
        fps = (1.0 / timeDiff) if (timeDiff > 0.0) else 0.0
        self.logger.info("[LOOP] {0:5.2f} fps".format(fps))
      #self.logger.debug("Pipeline: " + str(self.pipeline))  # current state of pipeline (preceding ~ means processor is inactive)
      
      # ** Read frame from input device
      if not isFrozen:
        if not self.inputDevice.read():
          break  # camera disconnected or reached end of video
        
        if showInput:
          cv2.imshow("Input", self.inputDevice.image)
      
      # ** Initialize FrameProcessors, if required
      if(fresh):
        self.pipeline.initialize(self.inputDevice.image, self.context.timeNow)
        fresh = False
      
      # ** TODO Activate/deactivate processors as desired
        
      # ** Process frame
      keepRunning, imageOut = self.pipeline.process(self.inputDevice.image, self.context.timeNow)
      
      # ** TODO Perform post-process functions
      
      # ** Show output image
      if showOutput and imageOut is not None:
        cv2.imshow("Output", imageOut)  # output image from last processor
      if not keepRunning:
        self.stop()
      
      # ** Check if GUI is available
      if self.context.options.gui:
        # *** If so, wait for inter-frame delay and process keyboard events using OpenCV
        key = cv2.waitKey(delay)
        if key != -1:
          keyCode = key & 0x00007f
          keyChar = chr(keyCode) if not (key & KeyCode.SPECIAL) else None
          
          if showKeys:
            self.logger.info("Key: " + KeyCode.describeKey(key))
          
          if keyCode == 0x1b or keyChar == 'q':
            break
          elif keyChar == ' ':
            self.logger.info("[PAUSED] Press any key to continue...")
            self.context.pause()  # [timing] saves timestamp when paused
            cv2.waitKey()  # wait indefinitely for a key press
            self.context.resume()  # [timing] compensates for duration paused
            self.logger.info("[RESUMED]")
          elif keyCode == 0x0d or keyCode == 0x0a:
            isFrozen = not isFrozen  # freeze frame, but keep processors running
            self.logger.info("Input {} at {:.2f}".format("frozen" if isFrozen else "thawed", self.context.timeNow))
          elif keyChar == 'x':
            self.pipeline.deactivateProcessors()
            self.logger.info("Pipeline processors deactivated.")
          elif keyChar == 'y':
            self.pipeline.activateProcessors()
            self.logger.info("Pipeline processors activated.")
          elif keyChar == 'f':
            showFPS = not showFPS
          elif keyChar == 'k':
            showKeys = not showKeys
          else:
            keepRunning = self.pipeline.onKeyPress(key, keyChar)  # pass along key-press to processors in pipeline
            if not keepRunning:
              self.stop()
      else:
        # *** Else, wait for inter-frame delay using system method
        sleep(delayS)
      
      # ** [timing] Save timestamp for fps calculation
      timeLast = self.context.timeNow
    
    # * Reset signal handlers to default behavior
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    # * Clean-up
    self.logger.info("Cleaning up...")
    if self.context.options.gui:
      cv2.destroyAllWindows()
    self.inputDevice.close()
  
  def stop(self):
    self.isOkay = False  # request vision loop to stop (will be checked at the beginning of the next loop iteration)
  
  def handleSignal(self, signum, frame):
    if signum == signal.SIGTERM or signum == signal.SIGINT:
      self.logger.debug("Termination signal ({0}); stopping vision loop...".format(signum))
    else:
      self.logger.warning("Unknown signal ({0}); stopping vision loop anyways...".format(signum))
    self.stop()


def run():
  """Entry point: Create PipelineManager and start vision loop."""
  manager = PipelineManager()
  manager.start()  # start vision loop


if __name__ == "__main__":
  run()
