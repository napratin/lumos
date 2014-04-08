"""Convenient RPC module based on ZMQ and JSON.

Usage:

from lumos import rpc

# Export a function (callable), using default name (same as function name)
@rpc.export
def foo():
  ...

# Export a function (callable), using an explicit name
@rpc.export('bar')
def bar_impl():
  ...

# Export a class (only enabled class methods are exposed)
@rpc.export
class QueueService(object):
  @rpc.enable
  @classmethod
  def count(cls):
    ...
  
  @rpc.enable
  def push(self, item):
    ...
  
  @rpc.disable
  def pop(self):
    ...

# Export an instance (only enabled instance methods are exposed)
rpc.export(QueueService())  # export an instance, use class name by default
rpc.export('q', QueueService())  # export an instance, explicitly specify name

# Start RPC server
rpc.start_server()  # blocking
rpc.start_server_thread(daemon=True)  # hassle-free asynchronous thread, stop with: rpc.stop()
"""

from inspect import isclass, ismethod, getmembers
from types import ClassType, InstanceType
from collections import OrderedDict
from threading import Thread
import simplejson as json
from simplejson.decoder import JSONDecodeError  # TODO fallback to json? (what is the equiv. of JSONDecodeError?)
import time
import logging
import numpy as np
import zmq

from util import is_bound, is_classmethod


# Module-level constants and variables
default_protocol = "tcp"
default_bind_host = "*"  # to listen on all interfaces
default_connect_host = "127.0.0.1"
default_port = "60606"

_rpc_enabled_attr = '_rpc_enabled'  # attribute used to mark enabled methods
_rpc_raw_payload_attr = '_rpc_raw_payload'  # attribute used to mark methods that return raw payload that should not be serialized
_rpc_image_payload_attr = '_rpc_image_payload'  # attribute used to mark methods that return an image, treated as a special raw payload
_exported_objects = OrderedDict()  # maintaining order generates more predictable docs
_exported_callables = OrderedDict()
_helpers = OrderedDict()

logger = logging.getLogger(__name__)  # module-level logger for functions and decorators
call_request_template = dict(type='call', call=None)
call_reply_template = dict(status='ok', type='value', value=None)  # reply message used to wrap any serializable return value
call_reply_raw_template = dict(status='ok', type='raw')  # special reply message used as header for raw data
call_reply_image_template = dict(status='ok', type='image', shape=None, dtype=None)  # special reply message used as image header
reply_error_template = dict(status='error', type='msg', msg=None)


# Utility functions
def is_rpc_enabled(method):
  """Check if argument is an RPC-enabled bound method."""
  return ismethod(method) and is_bound(method) and getattr(method, _rpc_enabled_attr, False)


# TODO Generalize make_*() functions so that fields can be set in a single call (using dict.extend?)
def make_call_request(call, params={}):
  request = call_request_template.copy()
  request['call'] = call
  request['params'] = params
  return request


def make_call_reply(value):
  reply = call_reply_template.copy()
  reply['value'] = value
  return reply


def make_call_reply_raw():
  reply = call_reply_raw_template.copy()  # do we need to copy since no fields are editable?
  return reply


def make_call_reply_image(image):
  reply = call_reply_image_template.copy()
  reply['shape'] = image.shape
  reply['dtype'] = str(image.dtype)
  return reply


def make_error_reply(msg):
  reply = reply_error_template.copy()
  reply['msg'] = msg
  return reply


# Handy reply objects
reply_bad_json = make_error_reply('JSON error')
reply_bad_request = make_error_reply('Bad request')
reply_bad_call = make_error_reply('Unknown call')
reply_bad_params = make_error_reply('Bad params')


# Decorators/functions to specify RPC calls
def enable(method, payload_attr=None):
  """Decorator/function to enable RPC on a method."""
  #logger.debug("method: {}, type: {}, callable? {}, isfunction? {}, ismethod? {}, is_bound? {}, is_classmethod? {}".format(method, type(method), callable(method), isfunction(method), ismethod(method), is_bound(method), is_classmethod(method)))  # [verbose]
  if is_classmethod(method) or is_bound(method):
    setattr(method.__func__, _rpc_enabled_attr, True)  # for bound methods, we can only set attributes on the underlying function object
    if payload_attr is not None:
      setattr(method.__func__, payload_attr, True)
  else:
    setattr(method, _rpc_enabled_attr, True)  # NOTE this will fail if applied on an instancemethod
    if payload_attr is not None:
      setattr(method, payload_attr, True)
  return method


def enable_raw(method):
  """Decorator/function to enable raw RPC on a method, i.e. return values are not serialized."""
  return enable(method, payload_attr=_rpc_raw_payload_attr)


def enable_image(method):
  """Decorator/function to enable proper RPC on a method that returns an image, treated as a raw payload."""
  return enable(method, payload_attr=_rpc_image_payload_attr)


def disable(method):
  """Decorator/function to disable RPC on a method."""
  if is_classmethod(method) or is_bound(method):
    setattr(method.__func__, _rpc_enabled_attr, False)  # for bound methods, we can only set attributes on the underlying function object
  else:
    setattr(method, _rpc_enabled_attr, False)  # NOTE this will fail if applied on an instancemethod
  return method


def export(*args, **kwargs):
  """Decorator/function to export methods of an instance or class, or a callable, via RPC."""
  
  def do_export(obj_):
    name_ = name  # TODO perform duplicate key checking before adding to exported_ dicts (?)
    #logger.debug("[Inside] name: {}, obj: {}, type: {}, callable? {}, method? {}, bound? {}".format(name_, obj_, type(obj_), callable(obj_), ismethod(obj_), isbound(obj_)))  # [verbose]
    if isinstance(obj_, (type, ClassType)):  # a type
      if name_ is None:
        name_ = obj_.__name__
      _exported_objects[name_] = obj_
      logger.debug("Exported type: {}".format(name_))  # [debug]
    elif ismethod(obj_):  # a method (doesn't work as methods are special *descriptors* in Python)
      if name_ is None:
        name_ = "{}.{}".format(obj_.__self__.__name__
                               if isinstance(obj_.__self__, (type, ClassType))
                               else obj_.__self__.__class__.__name__, obj_.__name__)  # pick class name, whether classmethod or instancemethod
      logger.warning("Could not export method: {}. Mark methods for export using rpc.enable and then export an instance, or the class.".format(name_))
    elif callable(obj_):  # a function or other callable (only marked for now, will be exported when instance is exported)
      if name_ is None:
        name_ = obj_.__name__
      _exported_callables[name_] = obj_
      logger.debug("Exported callable: {}".format(name_))
    elif isinstance(obj_, (object, InstanceType)):  # an instance that is not callable (only marked methods will be exported) 
      if name_ is None:
        name_ = obj_.__class__.__name__
      _exported_objects[name_] = obj_
      logger.debug("rpc.export(): Exported instance: {} (type: {})".format(name_, obj_.__class__.__name__))
    else:
      logger.warning("Unable to export object; name: {}, type (unsupported): {}".format(name_, type(obj_)))
    return obj_
  
  # Process arguments
  name = None
  obj = None
  args = list(args)  # we need a mutable sequence (deque is more efficient, but not required here)
  #logger.debug("[Outside] args: {}, kwargs: {}".format(args, kwargs))  # [verbose]
  
  if 'name' in kwargs:
    name = kwargs['name']
  elif args and isinstance(args[0], str):  # NOTE enforces name to be a string; if not, must be obj
    name = args.pop(0)
  
  if 'obj' in kwargs:
    obj = kwargs['obj']
  elif args:
    obj = args.pop(0)
  
  #logger.debug("[Outside] name: {}, obj: {}".format(name, obj))  # [verbose]
  
  # Handle different use cases
  if name is None and obj is not None:
    # Use case 1 - decorator, no args: @export <object>
    #logger.debug("[Outside] Use case 1 - decorator, no args: @export")  # [verbose]
    return do_export(obj)  # return wrapped object
  elif name is not None and obj is None:
    # Use case 2 - decorator, with args: @export(<name>) <object>
    #logger.debug("[Outside] Use case 2 - decorator, with args: @export('{}')".format(name))  # [verbose]
    return do_export  # return wrapper with name in closure (NOTE it might be important to keep 'obj' out of closure)
  elif name is not None and obj is not None:
    # Use case 3 - function call: export(<name>, <object>)
    #logger.debug("[Outside] Use case 3 - function call: export('{}', {})".format(name, obj))  # [verbose]
    return do_export(obj)  # return wrapped object
  else:
    # Unknown use case!
    logger.warning("Unknown use case: name: {}, obj: {}".format(name, obj))
    return None


def unexport(name):
  """Remove a function (callable), or an instance/class and all its methods previously exported."""
  
  if name in _exported_objects:
    prefix = "{}.".format(name)
    methods_to_remove = [qualified_name for qualified_name in _exported_callables.iterkeys() if qualified_name.startswith(prefix)]
    for qualified_name in methods_to_remove:
      del _exported_callables[qualified_name]
    del _exported_objects[name]
    logger.debug("Removed object named: {} (and corresponding callables)".format(name))
    return
  
  if name in _exported_callables:
    del _exported_callables[name]
    logger.debug("Removed callable named: {}".format(name))
    return
  
  logger.warning("Couldn't find name in list of exported objects or callables: {}".format(name))


# Helper RPC calls
def list_():
  return _exported_callables.keys()
_helpers['rpc.list'] = list_


# Types
class RPCError(Exception):
  """Exception raised for errors in RPC call processing."""
  
  def __init__(self, message, retval=None):
      self.message = message  # message to log
      self.retval = retval  # dict to return as RPC response (if None, message is sent with status='error')


class Server(object):
  """RPC call server - this is where all the magic happens."""
  
  # TODO A broken down mechanism (like InputRunner) that allows fine-grain control over updates/request-reply iterations (?)
  
  socket_linger = 2500  # max time to wait around to send pending messages before closing, -1 to wait indefinitely
  recv_timeout = 4000
  
  _running_instances = set()  # to ensure we don't try to run multiple servers bound to the same address
  _loop_flag = True  # run() keeps running while this is True, stop() sets it to false
  
  def __init__(self, protocol=default_protocol, host=default_bind_host, port=default_port, timeout=recv_timeout):
    self.logger = logging.getLogger(self.__class__.__name__)
    self.addr = "{}://{}:{}".format(protocol, host, port)
    self.timeout = timeout
    refresh()  # gather/update all callables, for further updates call refresh() externally
  
  def run(self):
    # Check for existing server instance, abort if one is already running
    for instance in self._running_instances:
      if self.addr == instance.addr:
        self.logger.warn("Server instance already running at: %s (aborting to avoid clash)", instance.addr)
        return
    
    # ZMQ setup (NOTE this is almost identical to client setup - can these be combined?)
    self.c = zmq.Context()
    self.s = self.c.socket(zmq.REP)
    self.s.setsockopt(zmq.LINGER, self.socket_linger)  # does this affect how long server listens for?
    if self.timeout is not None:
      self.s.setsockopt(zmq.RCVTIMEO, self.timeout)
    self.s.bind(self.addr)
    self._running_instances.add(self)
    time.sleep(0.1)  # yield to ZMQ backend
    self.logger.info("Bound to: {}".format(self.addr))
    
    # Serve indefinitely, till interrupted/flagged
    self.logger.info("Starting server [Ctrl+C to quit]")
    self._loop_flag = True
    while self._loop_flag:
      try:
        request = self.s.recv()  # use recv_json() or handle() strings requests
        if request is None:
          continue
        self.handle(request)
      except zmq.ZMQError as e:
        if e.errno == zmq.EAGAIN:
          continue  # no message available, probably a timeout
        else:
          raise  # real error
      except KeyboardInterrupt:
        break
    
    # Clean up
    self.s.close()
    #self.c.term()  # don't close context, as it may be shared (will be closed upon release anyway)
    self._running_instances.remove(self)
    self.logger.info("Server stopped.")
  
  def handle(self, request):
    self.logger.debug("REQ: %s", request)  # [verbose]
    
    # Open top-level try block to catch exceptions of type RPCError
    # NOTE Internal try blocks should raise RPCError instances with appropriate messages
    try:
      # If request is a string, construct a proper request object (dict) from it
      if isinstance(request, str):
        try:
          # First try parsing it as JSON
          request = json.loads(request)
        except JSONDecodeError as e:
          # If it isn't valid JSON, try interpreting it as a single token call with no params
          # TODO More strict checking? Or better regexp-based string parsing to get params as well?
          request = request.strip()  # trim whitespace from the ends
          if ' ' not in request and ':' not in request and ',' not in request and '{' not in request and '}' not in request:  # no spaces in between
            request = make_call_request(request)  # request is our call, no params
          else:
            raise RPCError("Unable to parse JSON request: {}".format(e), reply_bad_json)
      
      # Request must be a dict at this point for making a successful call
      if isinstance(request, dict):
        try:
          # Process request based on type
          request_type = request['type']
          if request_type == 'call':
            # RPC call: Get callable name and params, if any
            call = request['call']
            params = request.get('params', {})
            if not isinstance(params, dict):  # params must be a dict (TODO or list - map params to *args)
              raise RPCError("Bad call params: {}".format(params), reply_bad_params)
            
            # Dispatch RPC call
            try:
              # NOTE Calls to both helpers and user-exported callables are treated the same (they're just stored in different dicts, and helpers have precedence)
              if call in _helpers:
                call_target = _helpers[call]
              elif call in _exported_callables:
                call_target = _exported_callables[call]
              else:
                raise RPCError("Unknown call: {}".format(call), reply_bad_call)
              
              # Try to execute the actual call, handle returned value and any exceptions
              try:
                retval = call_target(**params)
                if getattr(call_target, _rpc_image_payload_attr, False) and isinstance(retval, np.ndarray):
                  # Image payload call returned an image; send back header/metadata followed by image bytes
                  self.logger.debug("REP[image]: shape: {}, dtype: {}".format(retval.shape, retval.dtype))  # [verbose]
                  header = make_call_reply_image(retval)
                  self.s.send_json(header, zmq.SNDMORE)
                  return self.s.send(retval)
                elif getattr(call_target, _rpc_raw_payload_attr, False):
                  # Raw payload call
                  header = make_call_reply_raw()
                  self.s.send_json(header, zmq.SNDMORE)
                  if isinstance(retval, (tuple, list)):  # multiple payloads
                    self.logger.debug("REP[raw]: %d payload(s)", len(retval))
                    self.s.send_multipart(retval)
                  else:
                    self.logger.debug("REP[raw]: Payload: %d bytes", len(retval))
                    self.s.send(retval)
                else:
                  # Regular (value) call
                  self.logger.debug("REP: {}".format(retval))  # [verbose]
                  self.s.send_json(make_call_reply(retval))
              except zmq.ZMQError as e:  # catch ZMQ exceptions separately
                self.logger.error("Unable to send reply (ZMQError): {}".format(e))  # don't try to send back an RPCError message
              except Exception as e:  # catch all other exceptions, related to failed RPC call or otherwise
                raise RPCError("{}: {}".format(e.__class__.__name__, e.message))  # message is the return value
            except TypeError as e:
              raise RPCError("Type mismatch (bad params?): {}".format(e), reply_bad_params)
          else:
            raise RPCError("Unknown request type: {}".format(request_type), reply_bad_request)
        except KeyError as e:
          raise RPCError("Missing key: {}".format(e), reply_bad_request)
      else:
        raise RPCError("Invalid request: {}".format(request), reply_bad_request)
    except RPCError as e:
      self.logger.error(e.message)
      retval = e.retval if e.retval is not None else make_error_reply(e.message)
      self.s.send_json(retval)  # NOTE retval is assumed to be a dict
  
  @classmethod
  def stop(cls):
    cls._loop_flag = False


class Client(object):
  """A lightweight client that can be used to make RPC calls on a server."""
  
  socket_linger = 2500  # max time to wait around to send pending messages before closing, -1 to wait indefinitely
  recv_timeout = None  #2000  # it's better to force clients to block and Ctrl+C out of them
  
  def __init__(self, protocol=default_protocol, host=default_connect_host, port=default_port, timeout=recv_timeout):
    self.logger = logging.getLogger(self.__class__.__name__)
    self.addr = "{}://{}:{}".format(protocol, host, port)
    self.c = zmq.Context()
    self.s = self.c.socket(zmq.REQ)
    self.s.setsockopt(zmq.LINGER, self.socket_linger)
    if timeout is not None:
      self.s.setsockopt(zmq.RCVTIMEO, timeout)
    self.s.connect(self.addr)
    time.sleep(0.1)  # yield to ZMQ backend
    self.logger.info("Connected to: {}".format(self.addr))
  
  def call(self, call, params={}):
    return self.request(make_call_request(call, params))
  
  def request(self, req):
    #self.logger.debug("REQ: %s", req)  # [verbose]
    self.s.send_json(req)  # req must be a Python dict/JSON object; caller must handle any exceptions
    
    try:
      rep = self.s.recv_json()  # first reply must be a JSON object
      
      # Handle errors (return an Exception object with the message)
      if rep['status'] == 'error':
        #self.logger.error("REP[error]: {}".format(rep))  # [verbose]
        return Exception(rep.get('msg', 'Unknown error'))
      
      # Handle different reply types
      if rep['type'] == 'value' and 'value' in rep:
        #self.logger.debug("REP: {}".format(rep['value']))  # [verbose]
        return rep['value']
      elif rep['type'] == 'image' and 'shape' in rep and 'dtype' in rep and self.s.getsockopt(zmq.RCVMORE):  # check for image data
        imageBytes = self.s.recv()  # TODO what if there's more data? should we recv till no more?
        imageBuffer = buffer(imageBytes)
        imageArray = np.frombuffer(imageBuffer, dtype=rep['dtype'])
        image = imageArray.reshape(rep['shape'])
        #self.logger.debug("REP[image]: shape: {}, dtype: {}".format(image.shape, image.dtype))  # [verbose]
        return image
      elif rep['type'] == 'raw' and self.s.getsockopt(zmq.RCVMORE):  # check for payload(s)
        payloads = []
        while self.s.getsockopt(zmq.RCVMORE):
          payload = self.s.recv()  # payloads are treated as raw
          payloads.append(payload)
          #self.logger.debug("REP[raw]: Payload: %d bytes", len(payload))  # [verbose]
        #self.logger.debug("REP[raw]: %d payload(s)", len(payloads))  # [verbose]
        # Returned value should be None, a single object or a list: <payload_1>, <payload_2> ...
        if len(payloads) == 1:
          return payloads[0]
        elif len(payloads) > 1:
          return payloads
      else:
        self.logger.debug("REP[unknown]: %s", rep)  # [verbose]
    except JSONDecodeError as e:
      self.logger.error("Unable to parse JSON reply: {}".format(e))  # [verbose]
    except zmq.ZMQError as e:
      if e.errno == zmq.EAGAIN:
        pass  # no message available, probably a timeout
      else:
        raise  # real error
    
    return None  # explicit default reply
  
  def close(self):
    self.s.close()
    #self.c.term()  # don't close context, as it may be shared (will be closed upon release anyway)
    self.logger.info("Client closed.")
  
  def __enter__(self):
    return self

  def __exit__(self, *_):  # unused args: (exc_type, exc_value, exc_trace)
    self.close()


# Primary module-level functions
def clear():
  _exported_callables.clear()
  _exported_objects.clear()


def refresh():
  """Update internal registry of callables to add any exported/unexported/enabled/disabled items."""
  
  # TODO Synchronize on _exported_objects and _exported_callables (along with export and unexport)
  for obj_name, obj in _exported_objects.iteritems():
    logger.debug("Exporting methods from {} ({})".format(obj_name, "type" if isclass(obj) else "instance of type: {}".format(obj.__class__.__name__)))
    for method_name, method in getmembers(obj, is_rpc_enabled):
      if method.__self__ is not obj:  # may happen if obj is an instance of a type with classmethods
        continue
      qualified_name = "{}.{}".format(obj_name, method_name)
      _exported_callables[qualified_name] = method
      #logger.debug("Added {}".format(qualified_name)  # [verbose]
  
  logger.info("Exported RPC calls: {}".format(", ".join(_exported_callables.iterkeys())))


def start_server(*args, **kwargs):
  """Start RPC server for exported callables (blocking)."""
  Server(*args, **kwargs).run()


def start_server_thread(daemon=True, *args, **kwargs):
  """Start RPC server thread (asynchronous), return Thread object immediately."""
  rpcServerThread = Thread(target=start_server, name="RPC-Server", args=args, kwargs=kwargs)
  rpcServerThread.daemon=daemon
  rpcServerThread.start()
  time.sleep(0.01)  # let new thread start
  return rpcServerThread


def stop_server():
  """Stop RPC server, whether started in blocking mode or asynchronously."""
  Server.stop()


# Testing
if __name__ == "__main__":
  log_format = "%(levelname)s | %(name)s | %(funcName)s() | %(message)s"
  logging.basicConfig(format=log_format, level=logging.DEBUG)  # use desired logging format and level when this module is run directly
  
  @export
  def foo():
    return "who?"
  
  @export
  def mul(a, b):
    return a * b
  
  start_server()  # refresh() is called internally by start_server()
