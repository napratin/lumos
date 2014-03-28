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

"""

from inspect import isclass, ismethod, isfunction, getmembers
from types import MethodType, ClassType, InstanceType
from collections import OrderedDict
from simplejson.decoder import JSONDecodeError  # TODO fallback to json? (what is the equiv. of JSONDecodeError?)
import time
import logging
import zmq

from context import Context


# Module-level constants and variables
default_protocol = "tcp"
default_host = "*"
default_port = "60606"
recv_timeout = 4000

_rpc_enabled_attr = '_rpc_enabled'  # attribute used to mark enabled methods
_exported_objects = OrderedDict()  # maintaining order generates more predictable docs
_exported_callables = OrderedDict()
_helpers = OrderedDict()

logger = logging.getLogger(__name__)
reply_error = dict(status='error', type='msg', msg='Error')
reply_bad_json = dict(status='error', type='msg', msg='JSON error')
reply_bad_request = dict(status='error', type='msg', msg='Bad request')
reply_bad_call = dict(status='error', type='msg', msg='Unknown call')
reply_bad_params = dict(status='error', type='msg', msg='Bad params')
call_request_template = dict(type='call', call=None)
call_reply_template = dict(status='ok', type='value', value=None)

_loop_flag = True  # start() keeps looping while this is True


# Utility functions
def is_bound(method):
  """Check if argument is a bound method, i.e. its __self__ attr is not None."""
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


def is_rpc_enabled(method):
  """Check if argument is an RPC-enabled bound method."""
  return ismethod(method) and is_bound(method) and getattr(method, _rpc_enabled_attr, False)


def make_call_request(call, params={}):
  request = call_request_template.copy()
  request['call'] = call
  request['params'] = params
  return request


def make_call_reply(retval):
  reply = call_reply_template.copy()
  reply['value'] = retval
  return reply


# Decorators/functions to specify RPC calls
def enable(method):
  """Decorator/function to enable RPC on a method."""
  #logger.debug("method: {}, type: {}, callable? {}, isfunction? {}, ismethod? {}, is_bound? {}, is_classmethod? {}".format(method, type(method), callable(method), isfunction(method), ismethod(method), is_bound(method), is_classmethod(method)))  # [verbose]
  if is_classmethod(method) or is_bound(method):
    setattr(method.__func__, _rpc_enabled_attr, True)  # for bound methods, we can only set attributes on the underlying function object
  else:
    setattr(method, _rpc_enabled_attr, True)  # NOTE this will fail if applied on an instancemethod
  return method


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


# Functions
def clear():
  _exported_callables.clear()
  _exported_objects.clear()


def refresh():
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


def start(protocol=default_protocol, host=default_host, port=default_port):
  """Start RPC server for exported callables."""
  # TODO Write async wrapper to run start() on separate thread/process with daemon=True, and be interruptible
  #      And a broken down mechanism (like InputRunner) that allows fine-grain control over updates/request-reply iterations
  # TODO Keep checking for new exports/unexports (use a flag with refresh?)
  bind_addr = "{}://{}:{}".format(protocol, host, port)
  c = zmq.Context()
  s = c.socket(zmq.REP)
  s.setsockopt(zmq.RCVTIMEO, recv_timeout)
  s.bind(bind_addr)
  time.sleep(0.01)  # yield to let ZMQ backend code run for a little bit
  logger.info("Bound to: {}".format(bind_addr))
  
  # Serve indefinitely, till interrupted
  logger.info("Starting server [Ctrl+C to quit]")
  _loop_flag = True
  while _loop_flag:
    try:
      request = s.recv()  #recv_json()
      if request is None:
        continue
      logger.debug("REQ: {}".format(request))
      reply = handle(request)
      logger.debug("REP: {}".format(reply))
      s.send_json(reply)
    except JSONDecodeError as e:
      logger.error("Unable to parse JSON request: {}".format(e))
      logger.debug("REP: {}".format(reply_bad_json))  # error reply
      s.send_json(reply_bad_json)
    except KeyboardInterrupt:
      break
  
  s.close()
  c.term()
  logger.info("Done.")


def stop():
  _loop_flag = False


def handle(request):
  if isinstance(request, str):
    try:
      request = json.loads(request)
    except JSONDecodeError as e:
      request = request.strip()  # trim whitespace from the ends
      if ' ' not in request and ':' not in request and ',' not in request and '{' not in request and '}' not in request:  # no spaces in between (TODO more strict checking? or better string parsing?)
        request = make_call_request(request)  # request is our call, no params
      else:
        raise e  # should be caught outside
  
  if isinstance(request, dict):
    try:
      request_type = request['type']
      if request_type == 'call':
        call = request['call']
        params = request.get('params', {})
        if not isinstance(params, dict):  # params must be a dict (TODO or list - map params to *args)
          logger.error("[type=call] Bad params: {}".format(params))
          return reply_bad_params
        
        try:
          if call in _helpers:
            retval = _helpers[call](**params)
            return make_call_reply(retval)
          elif call in _exported_callables:
            retval = _exported_callables[call](**params)
            return make_call_reply(retval)
          else:
            logger.error("[type=call] Unknown call: {}".format(call))
            return reply_bad_call
        except TypeError as e:
          logger.error("[type=call] Type mismatch (bad params?): {}".format(e))
          return reply_bad_params
      else:
        logger.error("Unknown request type: {}".format(request_type))
        return reply_bad_request
    except KeyError as e:
      logger.error("Missing key: {}".format(e))
      return reply_bad_request
  elif isinstance(request, list):
    logger.error("Unable to use JSON (in list form): {}".format(request))
    return reply_error


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
  
  refresh()
  start()
