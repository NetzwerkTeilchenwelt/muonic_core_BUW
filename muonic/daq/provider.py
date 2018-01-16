"""
Provides the public interfaces to read from and send to a DAQ card
"""

from __future__ import print_function
import abc
from future.utils import with_metaclass
import logging
import multiprocessing as mp
import re
import queue

try:
    import zmq
except ImportError:
    # DAQMissingDependencyError will be raised when trying to use zmq
    pass

from muonic.daq import DAQIOError, DAQMissingDependencyError
from muonic.daq import DAQSimulationConnection, DAQConnection


class BaseDAQProvider(with_metaclass(abc.ABCMeta, object)):
    """
    Base class defining the public API and helpers for the
    DAQ provider implementations

    :param logger: logger object
    :type logger: logging.Logger
    """

    LINE_PATTERN = re.compile("^[a-zA-Z0-9+-.,:()=$/#?!%_@*|~' ]*[\n\r]*$")

    def __init__(self, logger=None):
        if logger is None:
            logger = logging.getLogger(self.__module__ + '.' + self.__class__.__name__)
        self.logger = logger

    @abc.abstractmethod
    def get(self, *args):
        """
        Get something from the DAQ.

        :param args: queue arguments
        :type args: list
        :returns: str or None
        """
        return

    @abc.abstractmethod
    def put(self, *args):
        """
        Send information to the DAQ.

        :param args: queue arguments
        :type args: list
        :returns: None
        """
        return

    @abc.abstractmethod
    def data_available(self):
        """
        Tests if data is available from the DAQ.

        :returns: int or bool
        """
        return

    def _validate_line(self, line):
        """
        Validate line against pattern. Returns None it the provided line is
        invalid or the line if it is valid.

        :param line: line to validate
        :type line: str
        :returns: str or None
        """
        if self.LINE_PATTERN.match(line) is None:
            # Do something more sensible here, like stopping the DAQ then
            # wait until service is restarted?
            self.logger.warning("Got garbage from the DAQ: %s" %
                                line.rstrip('\r\n'))
            return None
        return line


class DAQProvider(BaseDAQProvider):
    """
    DAQProvider

    :param logger: logger object
    :type logger: logging.Logger
    :param sim: enables DAQ simulation if set to True
    :type sim: bool
    """

    def __init__(self, logger=None, sim=False):
        BaseDAQProvider.__init__(self, logger)
        self.out_queue = mp.Queue()
        self.in_queue = mp.Queue()

        if sim:
            self.daq = DAQSimulationConnection(self.in_queue, self.out_queue,
                                               self.logger)
        else:
            self.daq = DAQConnection(self.in_queue, self.out_queue,
                                     self.logger)
        
        # Set up the thread to do asynchronous I/O. More can be made if
        # necessary. Set daemon flag so that the threads finish when the main
        # app finishes
        self.read_thread = mp.Process(target=self.daq.read, name="pREADER")
        self.read_thread.daemon = True
        self.read_thread.start()

        if not sim:
            self.write_thread = mp.Process(target=self.daq.write,
                                           name="pWRITER")
            self.write_thread.daemon = True
            self.write_thread.start()
        
    def get(self, *args):
        """
        Get something from the DAQ.

        Raises DAQIOError if the queue is empty.

        :param args: queue arguments
        :type args: list
        :returns: str or None -- next item from the queue
        :raises: DAQIOError
        """
        try:
            line = self.out_queue.get(*args)
        except queue.Empty:
            raise DAQIOError("Queue is empty")

        return self._validate_line(line)

    def put(self, *args):
        """
        Send information to the DAQ.

        :param args: queue arguments
        :type args: list
        :returns: None
        """
        self.in_queue.put(*args)

    def data_available(self):
        """
        Tests if data is available from the DAQ.

        :returns: int or bool
        """
        try:
            size = self.out_queue.qsize()
        except NotImplementedError:
            self.logger.debug("Running Mac version of muonic.")
            size = not self.out_queue.empty()
        return size


class DAQClient(BaseDAQProvider):
    """
    DAQClient

    Raises DAQMissingDependencyError if zmq is not installed.

    :param address: address to connect to
    :type address: str
    :param port: TCP port to connect to
    :type port: int
    :param logger: logger object
    :type logger: logging.Logger
    :raises: DAQMissingDependencyError
    """
    
    def __init__(self, address='127.0.0.1', port=5556, logger=None):
        BaseDAQProvider.__init__(self, logger)
        try:
            self.socket = zmq.Context().socket(zmq.PAIR)
            self.socket.connect("tcp://%s:%d" % (address, port))
        except NameError:
            raise DAQMissingDependencyError("no zmq installed...")

    def get(self, *args):
        """
        Get something from the DAQ.

        Raises DAQIOError if the queue is empty.

        :param args: queue arguments
        :type args: list
        :returns: str or None -- next line read from socket
        :raises: DAQIOError
        """
        try:
            line = self.socket.recv_string()
        except Exception:
            raise DAQIOError("Socket error")
        
        return self._validate_line(line)

    def put(self, *args):
        """
        Send information to the DAQ.

        :param args: queue arguments
        :type args: list
        :returns: None
        """
        self.socket.send_string(*args)

    def data_available(self):
        """
        Tests if data is available from the DAQ.

        :returns: int or bool
        """
        return self.socket.poll(200)
