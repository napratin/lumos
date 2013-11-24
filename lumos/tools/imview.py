#!/usr/bin/env python

import sys

import numpy as np
import cv2

def imview():
  """View a single image."""
  print "IMage VIEWer (OpenCV " + cv2.__version__ + ")"
  if len(sys.argv) <= 1:
    print "Usage: " + sys.argv[0] + " <filename>"
    return
  
  inFilename = sys.argv[1]
  print "Filename: " + inFilename
  image = cv2.imread(inFilename)
  if image is None:
    print "Unable to read image!"
    return
  
  print "Image size: {}x{}".format(image.shape[1], image.shape[0])
  cv2.imshow("Image", image)
  print "Press any key to continue..."
  cv2.waitKey()


if __name__ == "__main__":
  imview()
