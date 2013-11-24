import sys
import os
import time
import yaml
import argparse
import logging.config

from util import isImageFile

class Context:
  """Application context class to store global data, configuration and objects."""
  
  default_description = "An awesome computer vision application"  # applications should override this when calling Context.createInstance()
  default_base_dir = os.path.dirname(__file__)  # NOTE this context module must be in top-level package
  default_config_filename = os.path.join(default_base_dir, "config.yaml")  # primary configuration file
  alt_config_filename = os.path.join(default_base_dir, "res", "config", "config.yaml")  # configuration file in alternate location
  default_res_path = os.path.join(default_base_dir, "res")  # resource path
  
  @classmethod
  def createInstance(cls, *args, **kwargs):
    if not hasattr(cls, 'instance'):
      cls.instance = Context(*args, **kwargs)
    else:
      print "Context.createInstance(): [WARNING] Context already created."
    return cls.instance
  
  @classmethod
  def getInstance(cls):
    try:
      return cls.instance
    except AttributeError:
      raise Exception("Context.getInstance(): Called before context was created.")
  
  def __init__(self, argv=None, description=default_description, parent_argparsers=[]):
    """Create a singleton, global application context, parse command-line args (with possible parent parsers passed in), and try to initialize input source parameters."""
    
    # * Ensure singleton
    if hasattr(self.__class__, 'instance'):
      raise Exception("Context.__init__(): Singleton instance already exists!")
    
    # * Setup and parse common command-line arguments
    self.argParser = argparse.ArgumentParser(description=description, parents=parent_argparsers)
    self.argParser.add_argument('--config', dest='config_file', default=self.default_config_filename, help='configuration filename')
    self.argParser.add_argument('--res', dest='res_path', default=self.default_res_path, help='path to resource directory')
    self.argParser.add_argument('--debug', action="store_true", help="show debug output?")
    #self.argParser.add_argument('--gui', action="store_true", help="display GUI interface/windows?")  # use mutually exclusive [--gui | --no_gui] group instead
    guiGroup = self.argParser.add_mutually_exclusive_group()
    guiGroup.add_argument('--gui', dest='gui', action='store_true', default=True, help="display GUI interface/windows?")
    guiGroup.add_argument('--no_gui', dest='gui', action='store_false', default=False, help="suppress GUI interface/windows?")
    self.argParser.add_argument('--loop_video', action="store_true", help="keep replaying video?")
    self.argParser.add_argument('--sync_video', action="store_true", help="synchronize video playback to real-time?")
    self.argParser.add_argument('--video_fps', default='auto', help="desired video frame rate (for sync)")
    self.argParser.add_argument('--camera_width', default='auto', help="desired camera frame width")
    self.argParser.add_argument('--camera_height', default='auto', help="desired camera frame height")
    self.argParser.add_argument('input_source', nargs='?', default='0', help="input image/video/camera device no.")
    self.options = self.argParser.parse_args(argv)  # parse_known_args()?
    if self.options.debug:
      print "Context.__init__(): Options: {}".format(self.options)
    
    # * Read config file
    self.config = {}
    try:
      with open(self.options.config_file, 'r') as f:
        self.config = yaml.load(f)
    except IOError:
      print "Context.__init__(): Error reading config file: {}".format(self.options.config_file)
      raise
    else:
      pass  #print "Context.__init__(): Loaded configuration: {}".format(self.config)  # [debug]
    
    # * Obtain resource path and other parameters
    # TODO Provide unified configuration capability with config file and command-line overrides
    self.resPath = os.path.abspath(self.options.res_path)  # NOTE only absolute path seems to work properly
    #print "Context.__init__(): Resource path: {}".format(self.resPath)  # [debug]
    
    # * Setup logging (before any other object is initialized that obtains a logger)
    # ** Load configuration from file
    logConfigFile = self.getResourcePath("config", "logging.conf")  # TODO make log config filename an optional argument
    #print "Context.__init__(): Log config file: {}".format(logConfigFile)  # [debug]
    startupDir = os.getcwd()  # save original startup dir
    os.chdir(os.path.dirname(logConfigFile))  # change to log config file's directory (it contains relative paths)
    logging.config.fileConfig(logConfigFile)  # load configuration
    os.chdir(startupDir)  # change back to original startup directory
    # ** Tweak root logger configuration based on command-line arguments
    if self.options.debug and logging.getLogger().getEffectiveLevel() > logging.DEBUG:
      logging.getLogger().setLevel(logging.DEBUG)
    elif not self.options.debug and logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
      logging.getLogger().setLevel(logging.INFO)  # one level above DEBUG
      # NOTE Logging level order: DEBUG < INFO < WARN < ERROR < CRITICAL
    
    # * Get a logger instance
    self.logger = logging.getLogger(__name__)
    # TODO Handle log rolling, log file write permission check?
    
    # * Initialize input source parameters (TODO move this logic into InputDevice?)
    self.isVideo = False
    self.isImage = False
    if self.options.input_source is not None:  # TODO include a way to specify None; currently defaults to device #0
      # ** Obtain camera device no. or input video/image filename
      try:
        self.options.input_source = int(self.options.input_source)  # works if input_source is an int (a device no.)
        self.isVideo = False
        self.isImage = False
      except ValueError:
        self.options.input_source = os.path.abspath(self.options.input_source)  # fallback: treat input_source as string (filename)
        if isImageFile(self.options.input_source):
          self.isVideo = False
          self.isImage = True
        else:
          self.isVideo = True
          self.isImage = False
    
    # * Timing
    self.resetTime()
  
  def resetTime(self):
    self.timeStart = time.time()  # [system time]
    # self.timeStart = cv2.getTickCount() / cv2.getTickFrequency()  # [OpenCV time]
    self.timeNow = 0.0
    self.isPaused = False
    self.timePaused = self.timeStart
  
  def update(self):
    self.timeNow = time.time() - self.timeStart  # [system time]
    # self.timeNow = (cv2.getTickCount() / cv2.getTickFrequency()) - self.timeStart  # [OpenCV time]
  
  def pause(self):
    self.timePaused = time.time()  # [system time]
    # self.ticksPaused = cv2.getTickCount()  # [OpenCV time]
    self.isPaused = True
  
  def resume(self):
    self.timeStart += time.time() - self.timePaused  # [system time]
    # self.timeStart += (cv2.getTickCount() - self.ticksPaused) / cv2.getTickFrequency()  # [OpenCV time]
    self.isPaused = False
  
  def getResourcePath(self, subdir, filename):
    return os.path.abspath(os.path.join(self.resPath, subdir, filename))
