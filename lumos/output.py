"""Components to help manage image output destinations."""

class OutputDevice(object):
  """Base class for all image output devices, defining the basic interface."""
  
  def __init__(self):
    self.image = None
  
  def write(self, image):
    self.image = image
