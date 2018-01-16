"""
Provides a simple DAQ card simulation, so that software can be tested.
"""
from __future__ import print_function
import abc
from future.utils import with_metaclass
import logging
import numpy as np
from os import path
import queue
from random import choice
import time

try:
    import zmq
except ImportError:
    # DAQMissingDependencyError will be raised when trying to use zmq
    pass

from muonic.daq import DAQMissingDependencyError


class DAQSimulation(object):
    """
    Simulates reading from and writing to DAQ card.

    :param logger: logger object
    :type logger: logging.Logger
    :param simulation_file: path to the simulation data file
    :type simulation_file: str
    """

    DEFAULT_SIMULATION_FILE = path.abspath(path.join(
            path.dirname(__file__), "simdaq.txt"))
    LINES_TO_PUSH = 10

    def __init__(self, logger, simulation_file=None):
        self.logger = logger
        self.initial = True
        self._pushed_lines = 0

        if simulation_file is None:
            # use packaged simulation file
            simulation_file = self.DEFAULT_SIMULATION_FILE
        self._simulation_file = simulation_file
        self._daq = open(self._simulation_file)
        self._in_waiting = True
        self._return_info = False

        self._scalars_ch = [0, 0, 0, 0]
        self._scalars_trigger = 0
        self._scalars_to_return = ''

    def __del__(self):
        """
        Closes simulation file on object destruction

        :returns: None
        """
        #if isinstance(self._daq, file) and not self._daq.closed:
        try:
            self._daq.close()
        except:
            pass

    def _physics(self):
        """
        This routine will increase the scalars variables using predefined
        rates. Rates are drawn from Poisson distributions.

        :returns: None
        """
 #       print("DEBUG DAQSimulation._physics START")

        def poisson_choice(lam, size):
            return int(choice(np.random.poisson(lam, size)))

        def format_to_8digits(hex_string):
            return hex_string.zfill(8)

        def format_scalar(val):
            return format_to_8digits(hex(val)[2:])

        # draw rates from a poisson distribution.
        self._scalars_ch[0] += poisson_choice(12, 100)
        self._scalars_ch[1] += poisson_choice(10, 100)
        self._scalars_ch[2] += poisson_choice(8, 100)
        self._scalars_ch[3] += poisson_choice(11, 100)
        self._scalars_trigger += poisson_choice(2, 100)
        self._scalars_to_return = 'DS S0=%s S1=%s S2=%s S3=%s S4=%s' % \
                                  (format_scalar(self._scalars_ch[0]),
                                   format_scalar(self._scalars_ch[1]),
                                   format_scalar(self._scalars_ch[2]),
                                   format_scalar(self._scalars_ch[3]),
                                   format_scalar(self._scalars_trigger))
        self.logger.debug("Scalars to return %s" % self._scalars_to_return)

#        print("DEBUG DAQSimulation._physics END")

    def readline(self):
        """
        Read dummy pulses from the simdaq file till the configured value is
        reached.

        :returns: str -- next simulated DAQ output
        """
        if self.initial:
            self.initial = False
            return "T0=42  T1=42  T2=42  T3=42"

        if self._return_info:
            self._return_info = False
            return self._scalars_to_return

        self._pushed_lines += 1
        if self._pushed_lines < self.LINES_TO_PUSH:
            line = self._daq.readline()
            if not line:
                self._daq = open(self._simulation_file)
                self.logger.debug("File reloaded")
                line = self._daq.readline()

            return line
        else:
            self._pushed_lines = 0
            self._in_waiting = False
            return self._daq.readline()

    def write(self, command):
        """
        Trigger a simulated daq response with command.

        :param command: Command to send (simulated) to the DAQ card
        :type command: str
        :returns: None
        """
        self.logger.debug("got the following command %s" % command)
        if "DS" in command:
            self._return_info = True

    def in_waiting(self):
        """
        Simulate a busy DAQ.

        :returns: bool
        """
#        print("DEBUG DAQSimulation.in_waiting START")

        if self._in_waiting:
            time.sleep(0.1)
            self._physics()
#            print("DEBUG DAQSimulation.in_waiting END")
            return True
        else:
            self._in_waiting = True
#            print("DEBUG DAQSimulation.in_waiting END")
            return False


class BaseDAQSimulationConnection(with_metaclass(abc.ABCMeta, object)):
    """
    Base class for a simulated connection to DAQ card.

    :param logger: logger object
    :type logger: logging.Logger
    """

    def __init__(self, logger=None):
        if logger is None:
            logger = logging.getLogger()
        self.logger = logger
        self.serial_port = DAQSimulation(self.logger)
        self.running = 1

    @abc.abstractmethod
    def read(self):
        """
        Simulate DAQ I/O.

        :returns: None
        """
        return


class DAQSimulationConnection(BaseDAQSimulationConnection):
    """
    Simulated client connection to DAQ card.

    :param in_queue: queue for incoming data
    :type in_queue: multiprocessing.Queue
    :param out_queue: queue for outgoing data
    :type out_queue: multiprocessing.Queue
    :param logger: logger object
    :type logger: logging.Logger
    """

    def __init__(self, in_queue, out_queue, logger=None):
        BaseDAQSimulationConnection.__init__(self, logger)
        self.in_queue = in_queue
        self.out_queue = out_queue

    def read(self):
        """
        Simulate DAQ I/O.

        :returns: None
        """
        while self.running:
            try:
                self.logger.debug("inqueue size is %d" % self.in_queue.qsize())
                while self.in_queue.qsize():
                    try:
                        self.serial_port.write(str(self.in_queue.get(0)) +
                                               "\r")
                    except queue.Empty:
                        self.logger.debug("Queue empty!")
            except NotImplementedError:
                self.logger.debug("Running Mac version of muonic.")
                while True:
                    try:
                        self.serial_port.write(str(self.in_queue.get(
                                timeout=0.01)) + "\r")
                    except queue.Empty:
                        pass

            while self.serial_port.in_waiting():
                self.out_queue.put(self.serial_port.readline().strip())
            time.sleep(0.02)


class DAQSimulationServer(BaseDAQSimulationConnection):
    """
    Simulated DAQ server.

    Raises DAQMissingDependencyError if zmq is not installed.

    :param address: address to listen on
    :type address: str
    :param port: TCP port to listen on
    :type port: int
    :param logger: logger object
    :type logger: logging.Logger
    :raises: DAQMissingDependencyError
    """

    def __init__(self, address='127.0.0.1', port=5556, logger=None):
        BaseDAQSimulationConnection.__init__(self, logger)
        try:
            self.socket = zmq.Context().socket(zmq.PAIR)
            self.socket.bind("tcp://%s:%d" % (address, port))
        except NameError:
            raise DAQMissingDependencyError("no zmq installed...")

    def serve(self):
        """
        Runs the server.

        :returns: None
        """
        while True:
            self.read()

    def read(self):
        """
        Simulate DAQ I/O.

        :returns: None
        """
        while self.running:
            msg = self.socket.recv_string()
            self.serial_port.write(str(msg) + "\r")
            
            while self.serial_port.in_waiting():
                self.socket.send_string(self.serial_port.readline().strip())
            time.sleep(0.02)

if __name__ == "__main__":
    logger = logging.getLogger()
    server = DAQSimulationServer(port=5556, logger=logger)
    server.serve()
