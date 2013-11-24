"""Base classes for OpenCV-based computer vision."""

import logging
import numpy as np
import cv2
from context import Context

class FrameProcessor:
  """Processes a sequence of images (frames)."""
  
  def __init__(self):
    self.context = Context.getInstance()  # NOTE Context must be created before this
    self.logger = logging.getLogger(__name__)
    self.active = False  # set to True once initialized
    # NOTE Subclasses should call FrameProcessor.__init__(self) and use self.context.options, self.logger
  
  def initialize(self, imageIn, timeNow):
    self.image = imageIn
    self.imageSize = (self.image.shape[1], self.image.shape[0])
    self.imageOut = self.image.copy() if self.context.options.gui else None
    self.logger.debug("Image size: {}".format(self.imageSize))
    self.active = True
  
  def process(self, imageIn, timeNow):
    self.image = imageIn
    if self.context.options.gui: self.imageOut = self.image
    return True, self.imageOut
  
  def onKeyPress(self, key, keyChar=None):
    return True  # indicates stop vision loop if False
    # TODO Change return behavior to indicate if event is consumed, and not to signal stop (or better, return both!)


class FrameProcessorPool:
  """Abstract base class for all collections of FrameProcessors."""
  
  def __init__(self):
    self.context = Context.getInstance()
    self.logger = logging.getLogger(__name__)
  
  def getProcessorByType(self, processorType):
    raise NotImplementedError("FrameProcessorPool.getProcessorByType() is abstract; must be implmented by subclasses.")


class DependentFrameProcessor(FrameProcessor):
  """A FrameProcessor that depends on the output of one or more other processors."""
  
  def __init__(self, processorPool):
    FrameProcessor.__init__(self)
    # NOTE Sublasses should call through to DependentFrameProcessor.__init__(self, processorPool) and find desired processor(s) in processorPool


class FrameProcessorPipeline(FrameProcessorPool):
  """An ordered pipeline of FrameProcessor instances."""
  
  def __init__(self, processorTypes):
    """Create a list of FrameProcessors given appropriate types."""
    FrameProcessorPool.__init__(self)
    self.processors = []
    for processorType in processorTypes:
      if issubclass(processorType, FrameProcessor):
        processor = processorType(self) if issubclass(processorType, DependentFrameProcessor) else processorType()
        self.processors.append(processor)
        self.logger.debug("Added {0} instance.".format(processor.__class__.__name__))
      else:
        self.logger.warning("Warning: {0} is not a FrameProcessor; will not instantiate.".format(processorType.__name__))
  
  def initialize(self, imageIn, timeNow):
    for processor in self.processors:
      processor.initialize(imageIn, timeNow)
  
  def process(self, imageIn, timeNow):
    keepRunning = True
    imageOut = None
    for processor in self.processors:
      if processor.active:
        keepRunning, imageOut = processor.process(imageIn, timeNow)
        if not keepRunning:
          break  # break out of this for loop (no further processors get to process this image)
    return keepRunning, imageOut
  
  def onKeyPress(self, key, keyChar=None):
    keepRunning = True
    for processor in self.processors:
      if processor.active:
        keepRunning = processor.onKeyPress(key, keyChar)  # pass along key-press to processor
        if not keepRunning:
          break  # break out of this for loop (no further processors get the key event)
    return keepRunning
  
  def activateProcessors(self, processorTypes=None, active=True):  # if None, activate all
    for processor in self.processors:
      if processorTypes is None or processor.__class__ in processorTypes:
        processor.active = active
  
  def deactivateProcessors(self, processorTypes=None):  # if None, deactivate all
    self.activateProcessors(processorTypes, False)
  
  def getProcessorByType(self, processorType):
    """Returns the first processor found that is an instance of processorType."""
    for processor in self.processors:
      if isinstance(processor, processorType):
        return processor
    return None
  
  def __str__(self):
    desc = "[" + ", ".join(("" if processor.active else "~") + processor.__class__.__name__ for processor in self.processors) + "]"
    return desc
