"""Unit testing for lumos.rpc module."""

import unittest
import logging

from lumos import rpc


class TestExportFunctions(unittest.TestCase):
  
  def setUp(self):
    unittest.TestCase.setUp(self)
    rpc.clear()
  
  def testDecoratorNoArgs(self):
    @rpc.export
    def foo():
      print "foo()"
    rpc.refresh()
    assert 'foo' in rpc._exported_callables and rpc._exported_callables['foo'] == foo
  
  def testDecoratorWithArgs(self):
    @rpc.export('bar')
    def bar_impl():
      print "bar_impl()"
    rpc.refresh()
    assert 'bar' in rpc.list_() and rpc._exported_callables['bar'] == bar_impl
  
  def testFunctionCall(self):
    def baz():
      print "baz()"
    rpc.export('mybaz', baz)
    rpc.refresh()
    assert 'mybaz' in rpc._exported_callables and rpc._exported_callables['mybaz'] == baz
  
  def testUnexport(self):
    @rpc.export
    def foo():
      print "foo()"
    
    rpc.refresh()
    assert 'foo' in rpc._exported_callables and rpc._exported_callables['foo'] == foo
    
    rpc.unexport('foo')
    rpc.refresh()
    assert 'foo' not in rpc._exported_callables


class TestExportObjects(unittest.TestCase):
  
  def setUp(self):
    unittest.TestCase.setUp(self)
    rpc.clear()
    
    @rpc.export
    class QueueService(object):
      @rpc.enable
      @classmethod
      def count(cls):
        print "QueueService.count() [classmethod]"
      
      @rpc.enable
      def push(self, item):
        print "QueueService.push()"
      
      @rpc.disable
      def pop(self):
        print "QueueService.pop()"
    
    self.QueueService = QueueService  # so that test cases can access this class definition
  
  def testClassDefaultName(self):
    rpc.refresh()
    assert 'QueueService.count' in rpc._exported_callables and rpc._exported_callables['QueueService.count'] == self.QueueService.count
    assert 'QueueService.push' not in rpc._exported_callables
    assert 'QueueService.pop' not in rpc._exported_callables
  
  def testInstanceDefaultName(self):
    q = self.QueueService()
    rpc.export(q)  # export an instance, use class name by default
    rpc.refresh()
    assert 'QueueService.count' not in rpc._exported_callables
    assert 'QueueService.push' in rpc._exported_callables and rpc._exported_callables['QueueService.push'] == q.push
    assert 'QueueService.pop' not in rpc._exported_callables
  
  def testInstanceExplicitName(self):
    q = self.QueueService()
    rpc.export('q', q)  # export an instance, explicitly specify name
    rpc.refresh()
    assert 'QueueService.count' in rpc._exported_callables and rpc._exported_callables['QueueService.count'] == self.QueueService.count
    assert 'q.push' in rpc._exported_callables and rpc._exported_callables['q.push'] == q.push
    assert 'q.pop' not in rpc._exported_callables
  
  def testClassMethodDisable(self):
    rpc.disable(self.QueueService.count)  # enable/disable a class method after class has been defined
    #rpc.export(self.QueueService)  # need to re-export class if a class method has been enabled/disabled (only if already started)
    rpc.refresh()
    assert 'QueueService.count' not in rpc._exported_callables
    assert 'QueueService.push' not in rpc._exported_callables
    assert 'QueueService.pop' not in rpc._exported_callables
  
  def testInstanceMethodEnable(self):
    q = self.QueueService()
    rpc.export('q', q)  # export an instance, explicitly specify name
    rpc.enable(q.pop)  # enable/disable an instance method after instance has been exported
    #rpc.export('q', q)  # need to re-export instance if an instance method has been enabled/disabled (only if already started)
    rpc.refresh()
    assert 'QueueService.count' in rpc._exported_callables
    assert 'q.push' in rpc._exported_callables and rpc._exported_callables['q.push'] == q.push
    assert 'q.pop' in rpc._exported_callables and rpc._exported_callables['q.pop'] == q.pop
  
  def testUnexport(self):
    q = self.QueueService()
    rpc.export('q', q)  # export an instance, explicitly specify name
    rpc.refresh()
    assert 'QueueService.count' in rpc._exported_callables and rpc._exported_callables['QueueService.count'] == self.QueueService.count
    assert 'q.push' in rpc._exported_callables and rpc._exported_callables['q.push'] == q.push
    assert 'q.pop' not in rpc._exported_callables
    
    rpc.unexport('QueueService')
    rpc.refresh()
    assert 'QueueService.count' not in rpc._exported_callables
    assert 'q.push' in rpc._exported_callables and rpc._exported_callables['q.push'] == q.push
    assert 'q.pop' not in rpc._exported_callables
    
    rpc.unexport('q')
    rpc.refresh()
    assert 'QueueService.count' not in rpc._exported_callables
    assert 'q.push' not in rpc._exported_callables
    assert 'q.pop' not in rpc._exported_callables


# TODO Test calling via real RPC (use named pipes for automated testing?)


if __name__ == "__main__":
    #import sys; sys.argv = ["", "TestExportFunctions.testDecoratorNoArgs"]  # to run a particular test case
    log_format = "%(levelname)s | %(name)s | %(funcName)s() | %(message)s"
    logging.basicConfig(format=log_format, level=logging.INFO)  # use desired logging format and level when this module is run directly
    unittest.main()
