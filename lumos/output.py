"""Components to help manage image output destinations."""

import logging
import numpy as np
import cv2
import cv2.cv as cv
import pyglet
from psychopy.visual import Window

import rpc


class OutputDevice(object):
  """Base class for all image output devices, defining the basic interface."""
  
  def __init__(self):
    self.image = None
  
  def write(self, image):
    self.image = image


class ImageServer(OutputDevice):
  """An image output device that posts the latest written image over RPC."""
  
  default_port = 61616
  
  def __init__(self, port=default_port):
    OutputDevice.__init__(self)
    rpc.export(self)  # uses class name by default
    rpc.start_server_thread(port=port)
  
  @rpc.enable_image
  def get_image(self):
    return self.image
  
  def stop(self):
    rpc.stop_server()
  
  def __enter__(self):
    return self
  
  def __exit__(self):
    self.stop()


class ImageServerWindow(Window):
  """A variant of psychopy.visual.Window (running on pyglet) that automatically posts screen images over RPC.
  
  Usage:
  
  # Create an ImageServerWindow (drop-in replacement for psychopy.visual.Window)
  from lumos.output import ImageServerWindow
  win = ImageServerWindow(size=(800, 600), fullscr=True, screen=0, allowGUI=False, allowStencil=False,
    monitor=u'testMonitor', color=u'black', colorSpace=u'rgb')
  ...
  win.flip()  # must call this when each frame is complete - augments original flip(), copies rendered frame for serving
  ...
  
  # You can also specify a rectangular region to serve
  win.setRect((int(win.size[0] / 4), int(win.size[1] / 4), int(win.size[0] / 2), int(win.size[1] / 2)))  # (x, y, w, h)
  
  # It's a good idea to close the window when done; this cleanly releases backend server thread
  win.close()
  """
  
  gui = False  # image window may steal focus; enable for debugging only
  imageWinName = "Image Server Window"
  
  def __init__(self, *args, **kwargs):
    #print "ImageServerWindow.__init__()"  # [debug]
    self.logger = logging.getLogger(self.__class__.__name__)
    self.rect = None  # selected rectangular region to serve (default: entire image)
    self.server = ImageServer()
    if self.gui and not kwargs.get('fullscr', True):  # NOTE can't rely on self.is_Fullscr Window.__init__() hasn't been called yet
      cv2.namedWindow(self.imageWinName)  # try to open this before the pyglet window so that it doesn't steal focus
      cv2.waitKey(1)
    Window.__init__(self, *args, **kwargs)  # NOTE this likely calls flip a few times to calibrate, so we need everything to be initialized beforehand
  
  def flip(self, clearBuffer=True):
    Window.flip(self, clearBuffer=False)  # draw everything, but don't clear buffer yet so that we can capture it
    self.updatePygletImage()  # TODO use Window._getFrame() instead? or _getRegionOfFrame?
    if clearBuffer:
      Window.clearBuffer(self)  # now that we have captured the image, clear the buffer
  
  # TODO rpc.enable this and then rpc.export(self, name='window') to allow remote calls like 'window.setRect' (similarly, window.moveRect?)
  def setRect(self, rect):
    """Set rectangular region to serve with a list/tuple/array: win.setRect((x, y, w, h))"""
    if rect is not None and len(rect) == 4:
      self.rect = rect  # TODO perform bounds checking
    else:
      self.logger.error("Invalid selection rect: {}".format(rect))
  
  def updatePygletImage(self):
    # * Grab raw image from current color buffer
    # TODO Handle FBO mode (currently assumes back color buffer is directly written to)
    rawImage = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
    if self.rect is not None:
      rawImage = rawImage.get_region(*self.rect)  # select rectangular region
    #self.logger.debug("rawImage: width: {}, height: {}, format: {}, pitch {}".format(rawImage.width, rawImage.height, rawImage.format, rawImage.pitch))
    
    # * Get image bytes, convert to numpy array
    imageBytes = rawImage.get_data(rawImage.format, rawImage.pitch)  # returns a bytes array
    imageRGBA = np.ndarray(shape=(rawImage.height, rawImage.width, len(rawImage.format)), buffer=imageBytes, dtype=np.uint8, strides=(rawImage.pitch, len(rawImage.format), 1))
    
    # * Convert array to desired format (assuming raw image is RGBA and we want BGR)
    # ** Method 1: Slice out the first 3 color channels (RGB), convert RGB to BGR
    # NOTE: OpenCV chokes on the result when trying to display (or do anything else), if source image was actually 4-channel (strides issue?)
    #imageRGB = imageRGBA[:, :, 0:3]
    #self.logger.debug("imageRGB: shape: {}, dtype: {}, min: {}, max: {}".format(imageRGB.shape, imageRGB.dtype, np.min(imageRGB), np.max(imageRGB)))
    #imageBGR = cv2.cvtColor(imageRGB, cv.CV_RGB2BGR)
    # ** Method 2: Split color channels, dropping alpha, and recombine in desired order
    imageR, imageG, imageB, _ = cv2.split(imageRGBA)
    imageBGR = cv2.merge((imageB, imageG, imageR))
    
    # Cache latest image for serving; optionally, display it
    self.server.write(imageBGR)
    if self.gui and not self._isFullScr:
        cv2.imshow(self.imageWinName, imageBGR)
        cv2.waitKey(1)  # NOTE: OpenCV window doesn't show up without this, even though pyglet is running (why?)
  
  def close(self):
    #print "ImageServerWindow.close()"  # [debug]
    self.server.stop()
    Window.close(self)
