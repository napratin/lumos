"""A sample lumos application."""

import cv2  # OpenCV functions

from lumos.base import FrameProcessor  # base processor class
from lumos.input import run  # driver function

class MyAwesomeProcessor(FrameProcessor):
  """Custom processor that selects hues based on current time."""
  
  def process(self, imageIn, timeNow):
    # Convert input Red-Green-Blue image to Hue-Saturation-Value
    hsv = cv2.cvtColor(imageIn, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)  # split into 3 channels
    h = h.reshape(h.shape + (1,))
    s = h.reshape(s.shape + (1,))
    
    # Pick desired hue range based on current time
    hue = int(((timeNow % 10) / 10) * 180)
    min_hue = max(0, hue - 10)
    max_hue = min(180, hue + 10)

    # Pick desired saturation range
    min_sat = 100
    max_sat = 255
    
    # Apply mask to select pixels in hue range and return
    mask = cv2.inRange(h, min_hue, max_hue)
    mask &= cv2.inRange(s, min_sat, max_sat)
    imageOut = cv2.bitwise_and(imageIn, imageIn, mask=mask)
    return True, imageOut


if __name__ == "__main__":
  # Run a custom processor instance (NOTE pass in class name)
  run(MyAwesomeProcessor, description="A sample lumos application")
