#!/usr/bin/env python

import sys
import os
from datetime import datetime

import numpy as np
import cv2
import cv2.cv as cv

default_frame_delay = 20

def viddiff():
  """Compare two recorded video streams."""
  print "VIDeo DIFFerencer (OpenCV " + cv2.__version__ + ")"
  if len(sys.argv) <= 2:
    print "Usage: " + sys.argv[0] + " <video_filename_a> <video_filename_b> [<frame_delay> [<start_frame_a> [<start_frame_b>]]]"
    return
  
  video_filename_a = sys.argv[1]
  video_filename_b = sys.argv[2]
  frame_delay = default_frame_delay
  start_frame_a = 0
  start_frame_b = 0
  
  try:
    if len(sys.argv) > 3:
      frame_delay = int(sys.argv[3])
      if len(sys.argv) > 4:
        start_frame_a = int(sys.argv[4])
        if len(sys.argv) > 5:
          start_frame_b = int(sys.argv[5])
  except ValueError:
    pass  # argument defaults already assigned
  
  print "Inputs:-\n\ta: {} (frame #{})\n\tb: {} (frame #{})".format(video_filename_a, start_frame_a, video_filename_b, start_frame_b)
  
  video_a = cv2.VideoCapture(video_filename_a)
  if video_a is None or not video_a.isOpened():
    print "Unable to open (a): {}".format(video_filename_a)
    return
  
  video_b = cv2.VideoCapture(video_filename_b)
  if video_b is None or not video_b.isOpened():
    print "Unable to open (b): {}".format(video_filename_b)
    return
  
  def setFramePos(video, frame_pos, relative=False, start_frame=0):
    frame_pos = video.get(cv2.cv.CV_CAP_PROP_POS_FRAMES) + frame_pos if relative else frame_pos
    if frame_pos < start_frame:
      frame_pos = start_frame
    video.set(cv2.cv.CV_CAP_PROP_POS_FRAMES, frame_pos)
    return int(video.get(cv2.cv.CV_CAP_PROP_POS_FRAMES))
  
  if start_frame_a > 0:
    frame_pos_a = setFramePos(video_a, start_frame_a)
  if start_frame_b > 0:
    frame_pos_b = setFramePos(video_b, start_frame_b)
  
  print "[Press ESC or Q to quit, SPACE to pause]"
  if frame_delay == 0:
    print "[Frame-by-frame mode: '<' to go backward, any other key to go forward]"
  isOkay = True
  isFresh = True
  isPaused = False
  isEqualSize = True  # to be determined later; assume equal
  while isOkay:
    frame_pos_a = int(video_a.get(cv2.cv.CV_CAP_PROP_POS_FRAMES))
    frame_pos_b = int(video_b.get(cv2.cv.CV_CAP_PROP_POS_FRAMES))
    _, image_a = video_a.read()
    _, image_b = video_b.read()
    if image_a is None or image_b is None:
      # Loop over
      print "Looping..."
      frame_pos_a = setFramePos(video_a, start_frame_a)
      frame_pos_b = setFramePos(video_b, start_frame_b)
      continue
    
    if isFresh:
      isFresh = False
      image_a_size = (image_a.shape[1], image_a.shape[0])
      image_b_size = (image_b.shape[1], image_b.shape[0])
      print "Image sizes:- a: {}x{}, b: {}x{}".format(image_a_size[0], image_a_size[1], image_b_size[0], image_b_size[1])
      if image_a_size[0] != image_b_size[0] or image_a_size[1] != image_b_size[1]:
        isEqualSize = False
        print "Warning: Unequal image sizes cannot be handled!"
        # TODO Handle unequal frame sizes by resizes smaller up to larger; handle edge case where one is wider, other is taller
        return
    
    image_diff = cv2.absdiff(image_a, image_b)
    print "Frame #: {}, {}".format(frame_pos_a, frame_pos_b)
    cv2.imshow("a", image_a)
    cv2.imshow("b", image_b)
    cv2.imshow("diff", image_diff)
    
    key = cv2.waitKey(0 if isPaused else frame_delay)
    if key != -1:
      keyCode = key & 0xff
      keyChar = chr(keyCode)
      #print "Key: {} ({})".format(keyChar, keyCode)
      if keyCode == 0x1b or keyChar == 'q' or keyChar == 'Q':  # quit
        isOkay = False
      elif keyChar == ' ':  # pause
        isPaused = not isPaused
        if isPaused:
          print "[PAUSED] Use '<' / '>' to go to prev/next frame; SPACE to resume"
        else:
          print "[RESUMED]"
      elif keyChar == ',' or keyChar == '<':
        frame_pos_a = setFramePos(video_a, -2, True, start_frame_a)
        frame_pos_b = setFramePos(video_b, -2, True, start_frame_b)
  
  print "[DONE] Press any key to continue..."
  cv2.waitKey()
  video_a.release()
  video_b.release()


if __name__ == "__main__":
  viddiff()
