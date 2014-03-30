#!/usr/bin/env python

import sys
import os
import time
from ctypes import c_bool, c_ubyte, c_int
from multiprocessing import Process, Value, Array

import numpy as np
import cv2
import cv2.cv as cv

import zmq

camera_frame_width = 640
camera_frame_height = 480
camera_frame_depth = 3
capture_delay = 0.01  # secs; duration to wait between frame captures
wait_delay = 20  # ms; duration to wait for events on each display loop iteration

server_protocol = "tcp"
server_bind_host = "*"
server_host = "127.0.0.1"
server_port = 60006


# Utilitiy functions (should be in util, but duplicated here to keep tools standalone)
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


class CameraStreamPublisher(Process):
  def __init__(self):
    Process.__init__(self)
    print "CameraStreamPublisher.__init__(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
  
  def run(self):
    print "CameraStreamPublisher.run(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
    
    # * Open camera and set desired capture properties
    self.camera = cv2.VideoCapture(0)
    if self.camera.isOpened():
      result_width = self.camera.set(cv.CV_CAP_PROP_FRAME_WIDTH, camera_frame_width)
      result_height = self.camera.set(cv.CV_CAP_PROP_FRAME_HEIGHT, camera_frame_height)
      print "CameraStreamPublisher.run(): Camera frame size set to {width}x{height} (result: {result_width}, {result_height})".format(width=camera_frame_width, height=camera_frame_height, result_width=result_width, result_height=result_height)
    else:
      print "CameraStreamPublisher.run(): Unable to open camera; aborting..."
      return
    
    # * Build ZMQ publisher socket
    self.context = zmq.Context()
    self.socket = self.context.socket(zmq.PUB)
    self.server_bind_addr = "{protocol}://{host}:{port}".format(
      protocol=server_protocol,
      host=server_bind_host,
      port=server_port)
    self.socket.bind(self.server_bind_addr)
    print "CameraStreamPublisher.run(): Publishing at {}".format(self.server_bind_addr)
    
    # * Keep reading frames and publishing until stopped or read error occurs
    print "CameraStreamPublisher.run(): Sending frames [Ctrl+C to quit]..."
    self.isOkay = True
    self.frame = None
    self.frameCount = 0
    while self.isOkay:
      try:
        #print "CameraStreamPublisher.run(): Frame # {}".format(self.frameCount)  # [debug]
        self.isOkay, self.frame = self.camera.read()
        if self.isOkay:
          send_array(self.socket, self.frame, meta=dict(id=self.frameCount))
          self.frameCount += 1
        time.sleep(capture_delay)
      except KeyboardInterrupt:
        break
    
    # * Clean-up
    self.camera.release()
    print "CameraStreamPublisher.run(): Done."


class StreamSubscriber(Process):
  def __init__(self):  #, stayAliveObj, frameCountObj, imageObj, imageShapeObj):
    Process.__init__(self)
    print "StreamSubscriber.__init__(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
  
  def run(self):
    print "StreamSubscriber.run(): [pid: {}, OS pid: {}]".format(self.pid, os.getpid())
    
    # * Build ZMQ socket and connect to publisher
    self.context = zmq.Context()
    self.socket = self.context.socket(zmq.SUB)
    self.server_connect_addr = "{protocol}://{host}:{port}".format(
        protocol=server_protocol,
        host=server_host,
        port=server_port)
    self.socket.connect(self.server_connect_addr)
    self.socket.setsockopt(zmq.SUBSCRIBE, "")  # subscribe to all topics
    print "StreamSubscriber.run(): Subscribed to {}".format(self.server_connect_addr)
    
    # * Keep receiving and displaying images until stopped or null image
    print "StreamSubscriber.run(): Starting display loop [Esc or Q on image, or Ctrl+C on terminal to quit]..."
    self.isOkay = True
    self.image = None
    self.meta = None
    self.lastImageId = self.imageId = -1
    while self.isOkay:
      try:
        self.image, self.meta = recv_array(self.socket)
        if self.image is None or self.meta is None:
          self.isOkay = False
          break
        
        self.imageId = self.meta.get('id', None)  # try to grab image id, default: None
        if self.imageId is None or self.imageId != self.lastImageId:
          #print "StreamSubscriber.run(): Image # {}".format(self.imageId)  # [debug]
          cv2.imshow("Image", self.image)
          self.lastImageId = self.imageId
        
        key = cv2.waitKey(wait_delay)
        if key != -1:
          keyCode = key & 0x00007f
          keyChar = chr(keyCode)
          if keyCode == 0x1b or keyChar == 'q':
            break
      except KeyboardInterrupt:
        break
    print "StreamSubscriber.run(): Done."


def campub():
  """Start a CameraStreamPublisher process."""
  print "campub(): Starting CameraStreamPublisher process..."
  cameraStreamPublisherProcess = CameraStreamPublisher()
  cameraStreamPublisherProcess.start()
  time.sleep(0.1)  # give child process a chance to run
  return cameraStreamPublisherProcess


def camsub():
  """Start a StreamSubscriber process."""
  print "camsub(): Starting StreamSubscriber process..."
  streamSubscriberProcess = StreamSubscriber()
  streamSubscriberProcess.start()
  time.sleep(0.1)  # give child process a chance to run
  return streamSubscriberProcess


def campubsub(argv=sys.argv):
  """Run CameraStreamPublisher and/or StreamSubscriber process(es)."""
  print "CAMera PUBlisher-SUBscriber (OpenCV " + cv2.__version__ + ")"
  
  # * Get command-line options
  doRunPub = '-p' in argv
  doRunSub = '-s' in argv
  if not (doRunPub or doRunSub):
    print "Usage: ./campubsub.py [-p | -s]"
    return
  
  # * Start child processes (subscriber first)
  if doRunSub: streamSubscriberProcess = camsub()
  if doRunPub: cameraStreamPublisherProcess = campub()
  print "campubsub(): Child process(es) started [Ctrl+C to quit]..."
  try:
    if doRunPub: cameraStreamPublisherProcess.join()
    if doRunSub: streamSubscriberProcess.join()
  except KeyboardInterrupt:
    # * Wait for child processes to finish
    print "campubsub(): [Interrupted] Waiting for child process(es) to finish..."
    if doRunPub: cameraStreamPublisherProcess.join()
    if doRunSub: streamSubscriberProcess.join()
  print "campubsub(): Done."


if __name__ == '__main__':
  campubsub()
