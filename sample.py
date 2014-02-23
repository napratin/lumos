"""A sample lumos application."""

import cv2  # OpenCV functions
import cv2.cv as cv  # OpenCV constants

from lumos.base import FrameProcessor  # base processor class
from lumos.input import run  # driver function

class MyAwesomeProcessor(FrameProcessor):
  """Custom processor that selects hues based on current time."""
  
  def process(self, imageIn, timeNow):
    # Convert input Red-Green-Blue image to Hue-Saturation-Value
    hsv = cv2.cvtColor(imageIn, cv.CV_BGR2HSV)
    h, s, v = cv2.split(hsv)  # split into 3 channels
    
    # Pick desired hue range based on current time
    hue = ((timeNow % 10) / 10) * 180
    min_hue = max(0, hue - 10) 
    max_hue = min(180, hue + 10)
    
    # Apply mask to select pixels in hue range and return
    mask = cv2.inRange(h, min_hue, max_hue)
    imageOut = cv2.bitwise_and(imageIn, imageIn, mask=mask)
    return True, imageOut


if __name__ == "__main__":
  # Run a custom processor instance (NOTE pass in class name)
  run(MyAwesomeProcessor, description="A sample lumos application")
