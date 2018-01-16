"""
Provides DAQ server and connection classes to interface with the serial port.
"""

from __future__ import print_function
import abc
from future.utils import with_metaclass
import logging
import os
import queue
import serial
import subprocess
from time import sleep

try:
    import zmq
except ImportError:
    # DAQMissingDependencyError will be raised when trying to use zmq
    pass

from muonic.daq import DAQMissingDependencyError


class BaseDAQConnection(with_metaclass(abc.ABCMeta, object)):
    """
    Base DAQ Connection class.

    Raises SystemError if serial connection cannot be established.

    :param logger: logger object
    :type logger: logging.Logger
    :raises: SystemError
    """

    def __init__(self, logger=None):
        if logger is None:
            logger = logging.getLogger()
        self.logger = logger
        self.running = 1

        try:
            self.serial_port = self.get_serial_port()
        except serial.SerialException as e:
            self.logger.fatal("SerialException thrown! Value: %s" % e.message)
            raise SystemError(e)

    def get_serial_port(self):
        """
        Check out which device (/dev/tty) is used for DAQ communication.

        Raises OSError if binary 'which_tty_daq' cannot be found.

        :returns: serial.Serial -- serial connection port
        :raises: OSError
        """
        connected = False
        serial_port = None

        def get_dev_path(script):
            tty = subprocess.Popen(
                    [script], stdout=subprocess.PIPE).communicate()[0]
            return "/dev/%s" % tty.rstrip('\n')

        while not connected:
            try:
                dev = get_dev_path("which_tty_daq")
            except OSError:
                # try using package script ../../bin/which_tty_daq
                which_tty_daq = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), os.pardir,
                                     os.pardir, 'bin', 'which_tty_daq'))

                if not os.path.exists(which_tty_daq):
                    raise OSError("Can not find binary which_tty_daq")

                dev = get_dev_path(which_tty_daq)

            self.logger.info("Daq found at %s", dev)
            self.logger.info("trying to connect...")

            try:
                serial_port = serial.Serial(port=dev, baudrate=115200,
                                            bytesize=8, parity='N', stopbits=1,
                                            timeout=0.5, xonxoff=True)
                connected = True
            except serial.SerialException as e:
                self.logger.error(e)
                self.logger.error("Waiting 5 seconds")
                sleep(5)

        self.logger.info("Successfully connected to serial port")

        return serial_port

    @abc.abstractmethod
    def read(self):
        """
        Get data from the DAQ. Read it from the provided Queue.

        :returns: None
        """
        return

    @abc.abstractmethod
    def write(self):
        """
        Put messages from the inqueue which is filled by the DAQ

        :returns: None
        """
        return


class DAQConnection(BaseDAQConnection):
    """
    Client connection with DAQ card

    :param in_queue: queue for incoming data
    :type in_queue: multiprocessing.Queue
    :param out_queue: queue for outgoing data
    :type out_queue: multiprocessing.Queue
    :param logger: logger object
    :type logger: logging.Logger
    """

    def __init__(self, in_queue, out_queue, logger=None):
        BaseDAQConnection.__init__(self, logger)
        self.in_queue = in_queue
        self.out_queue = out_queue

    def read(self):
        """
        Get data from the DAQ. Read it from the provided Queue.

        :returns: None
        """
        min_sleep_time = 0.01  # seconds
        max_sleep_time = 0.2  # seconds
        sleep_time = min_sleep_time  #seconds

        while self.running:
            try:
                if self.serial_port.inWaiting():
                    while self.serial_port.inWaiting():
                        self.out_queue.put(self.serial_port.readline().strip())
                    sleep_time = max(sleep_time / 2, min_sleep_time)
                else:
                    sleep_time = min(1.5 * sleep_time, max_sleep_time)
                sleep(sleep_time)
            except (IOError, OSError):
                self.logger.error("IOError")
                self.serial_port.close()
                self.serial_port = self.get_serial_port()
                # this has to be implemented in the future
                # for now, we assume that the card does not forget
                # its settings, only because the USB connection is
                # broken
                # self.setup_daq.setup(self.commandqueue)

    def write(self):
        """
        Put messages from the inqueue which is filled by the DAQ

        :returns: None
        """
        while self.running:
            try:
                while self.in_queue.qsize():
                    try:
                        self.serial_port.write(str(self.in_queue.get(0)) +
                                               "\r")
                    except (queue.Empty, serial.SerialTimeoutException):
                        pass
            except NotImplementedError:
                self.logger.debug("Running Mac version of muonic.")
                while True:
                    try:
                        self.serial_port.write(str(self.in_queue.get(
                                timeout=0.01)) + "\r")
                    except (queue.Empty, serial.SerialTimeoutException):
                        pass
            sleep(0.1)


class DAQServer(BaseDAQConnection):
    """
    DAQ server

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
        BaseDAQConnection.__init__(self, logger)
        try:
            self.socket = zmq.Context().socket(zmq.PAIR)
            self.socket.bind("tcp://%s:%d" % (address, port))
        except NameError:
            raise DAQMissingDependencyError("no zmq installed...")

    def serve(self):
        """
        Runs the server

        :returns: None
        """
        while True:
            self.read()
            self.write()

    def read(self):
        """
        Get data from the DAQ. Read it from the provided Queue.

        :returns: None
        """
        min_sleep_time = 0.01  # seconds
        max_sleep_time = 0.2  # seconds
        sleep_time = min_sleep_time  # seconds
        while self.running:
            try:
                if self.serial_port.inWaiting():
                    while self.serial_port.inWaiting():
                        self.socket.send(self.serial_port.readline().strip())
                    sleep_time = max(sleep_time / 2, min_sleep_time)
                else:
                    sleep_time = min(1.5 * sleep_time, max_sleep_time)
                sleep(sleep_time)
            except (IOError, OSError):
                self.logger.error("IOError")
                self.serial_port.close()
                self.serial_port = self.get_serial_port()
                # this has to be implemented in the future
                # for now, we assume that the card does not forget
                # its settings, only because the USB connection is
                # broken
                # self.setup_daq.setup(self.commandqueue)

    def write(self):
        """
        Put messages from the inqueue which is filled by the DAQ

        :returns: None
        """
        while self.running:
            msg = self.socket.recv_string()
            self.serial_port.write(str(msg) + "\r")
            sleep(0.1)


if __name__ == "__main__":
    logger = logging.getLogger()
    server = DAQServer(port=5556, logger=logger)
    server.serve()
