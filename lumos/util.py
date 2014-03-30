"""
Utility classes and functions.
"""

import os
from inspect import ismethod, isclass
import numpy as np
import cv2
import zmq


# Globals
image_file_exts = ("png", "jpg", "jpeg", "jpe", "jp2", "tiff", "tif", "pbm", "pgm", "ppm", "bmp", "dib", "gif")  # file extensions that indicate image files
video_file_exts = ("mp4", "mpg", "mpeg", "m4v", "avi", "ogg", "ogv")  # file extensions that indicate video files


# Types
class Enum(tuple):
  """Simple enumeration type based on tuple with indices as integer values.
  
  E.g.:
    Size = Enum(('S', 'M', 'L', 'XL'))
    mySize = Size.M
  
  """
  
  __getattr__ = tuple.index  # e.g. Size.M => getattr(Size, 'M') => tuple.index(('S', 'M', 'L', 'XL'), 'M') => 1
  
  fromString = tuple.index
  
  def toString(self, value):
    return self[value]
  

class KeyCode:
  """Utility class to manage special keys and other keyboard input."""
  
  NUM_LOCK  = 0x100000  # status
  SHIFT     = 0x010000  # combo
  CAPS_LOCK = 0x020000  # status
  CTRL      = 0x040000  # combo
  ALT       = 0x080000  # combo
  SPECIAL   = 0x00ff00  # key down: CTRL, SHIFT, ALT, SUPER, NUM_LOCK, CAPS_LOCK, Fn etc.
  
  @classmethod
  def describeKey(cls, key, showStatus=False):
    """Describe key with modifiers (SHIFT, CTRL, ALT), and optionally status (NUM_LOCK, CAPS_LOCK)."""
    desc  = ""
    
    # * Status
    if showStatus:
      desc += "[" + \
          "NUM_LOCK "  + ("ON" if key & KeyCode.NUM_LOCK  else "OFF") + ", " + \
          "CAPS_LOCK " + ("ON" if key & KeyCode.CAPS_LOCK else "OFF") + \
          "] "
    
    # * Modifiers
    desc += "" + \
        ("Shift + " if key & KeyCode.SHIFT else "") + \
        ("Ctrl + "  if key & KeyCode.CTRL  else "") + \
        ("Alt + "   if key & KeyCode.ALT   else "")
    
    # * Key
    keyByte = key & 0xff # last 8 bits
    keyCode = key & 0x7f  # last 7 bits (ASCII)
    keyChar = chr(keyCode)
    desc += (hex(keyByte) + " (" + str(keyByte) + ")" if key & KeyCode.SPECIAL or keyCode < 32 else keyChar + " (" + str(keyCode) + ")")
    
    return desc


# Decorators
def deprecated(func):
  """Decorator to mark deprecated functions."""
  func._deprecated_warned = False
  def deprecated_func(*args, **kwargs):
    if not func._deprecated_warned:
      print "[WARNING] Deprecated function \"{}\" called".format(func.__name__)
    func._deprecated_warned = True
    return func(*args, **kwargs)
  return deprecated_func


# Logging [deprecated: use Python's logging facility, configured by context]
@deprecated
def log_str(obj, func, msg):
  """Compose a log message with an object's class name and (optional) function name."""
  if func is None:
    return "{0}: {1}".format(obj.__class__.__name__, msg)
  else:
    return "{0}.{1}(): {2}".format(obj.__class__.__name__, func, msg)


@deprecated
def log(obj, func, msg):
  """Log a message composed using log_str() to stdout."""
  print log_str(obj, func, msg)


# File-related
def getFileExtension(filename):
  """Return the extension part of a filename, sans period, in lowercase."""
  return os.path.splitext(filename)[1][1:].strip().lower()


def isImageFile(filename):
  """Decides whether given filename represents an image file type (solely based on extension)."""
  return getFileExtension(filename) in image_file_exts


def isVideoFile(filename):
  """Decides whether given filename represents a video file type (solely based on extension)."""
  return getFileExtension(filename) in video_file_exts


# Inspection
def is_bound(method):
  """Check if argument is a bound (method), i.e. its __self__ attr is not None."""
  return getattr(method, '__self__', None) is not None


def is_classmethod(method):
  """Check if argument is a classmethod object (only useful when being defined inside a class)."""
  return isinstance(method, classmethod)


def is_bound_classmethod(method):
  """Check if argument is a classmethod bound to a class (useful after the class has been defined)."""
  return ismethod(method) and is_bound(method) and isclass(method.__self__)


def is_bound_instancemethod(method):
  """Check if argument is an instancemethod bound to an instance (useful after instance has been created)."""
  return ismethod(method) and is_bound(method) and not isclass(method.__self__)


# ZMQ-related
def send_array(socket, arr, meta=dict(), flags=0, copy=True, track=False):
  """Send a numpy array with metadata."""
  meta['dtype'] = str(arr.dtype)
  meta['shape'] = arr.shape
  socket.send_json(meta, flags | zmq.SNDMORE)
  return socket.send(arr, flags, copy=copy, track=track)


def recv_array(socket, flags=0, copy=True, track=False):
  """Receive a numpy array with metadata."""
  meta = socket.recv_json(flags=flags)
  msg = socket.recv(flags=flags, copy=copy, track=track)
  buf = buffer(msg)
  arr = np.frombuffer(buf, dtype=meta['dtype'])
  return arr.reshape(meta['shape']), meta


# OpenCV-specific, usually operating on an image
def cvtColorBGR2CMYK_(imageBGR):
  """
  Convert a BGR image to CMYK and return separate color channels as 4-tuple.
  Usage: C, M, Y, K = cvtColorBGR2CMYK_(imageBGR)
  """
  imageBGRScaled = imageBGR / 255.0  # scale to [0,1] range
  B, G, R = cv2.split(imageBGRScaled)  # split channels
  I = np.ones((imageBGRScaled.shape[0], imageBGRScaled.shape[1]))  # identity matrix
  K = I - imageBGRScaled.max(axis=2) - 0.001  # -0.001 is to prevent divide by zero in later steps
  C = (I - R - K) / (I - K)
  M = (I - G - K) / (I - K)
  Y = (I - B - K) / (I - K)
  return C, M, Y, K  # return 4 separate arrays


def cvtColorBGR2CMYK(imageBGR):
  """
  Convert a BGR image to CMYK and return a 4-channel image.
  Usage: imageCMYK = cvtColorBGR2CMYK(imageBGR)
  """
  return cv2.merge(cvtColorBGR2CMYK_(imageBGR))  # return a combined 4-channel image


def rotateImage(image, angle):
  """Rotate an image by the specified angle."""
  imageSize = (image.shape[1], image.shape[0])  # (width, height)
  imageCenter = (imageSize[0] / 2, imageSize[1] / 2)
  rotMat = cv2.getRotationMatrix2D(imageCenter, angle, 1.0)
  result = cv2.warpAffine(image, rotMat, imageSize, flags=cv2.INTER_LINEAR)
  return result


def showImage(image, duration=3000, windowTitle="Image", closeWindow=True):
  cv2.imshow(windowTitle, image)
  key = cv2.waitKey(duration)
  if closeWindow:
    cv2.destroyWindow(windowTitle)
  return key
