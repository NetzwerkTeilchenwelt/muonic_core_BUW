
import os
import datetime
import logging
from threading import Thread
from queue import Queue
from .analyzers import DataTypes
from uuid import UUID

class AbstractConsumer(object):

    def __init__(self):
        pass

    def push(self, data, data_type, run_id, analyzer_id=''):
        """
        Handle data received from analyzers

        :param data: the data
        :param data_type: type of data - depends on analyzer in the general case
        :type data_type: DataTypes|str|int
        :param run_id: unique id of the current run
        :type run_id: UUID
        :param analyzer_id: name or id of analyzer
        :type analyzer_id: str
        :return:
        """
        raise NotImplementedError

    def start(self, run_id, analyzer_id='', expected_data_types=[]):
        """
        Start receiving data

        :param run_id: unique id of the current run
        :type run_id: UUID
        :param analyzer_id: name or id of analyzer
        :param expected_data_types: list of data types sent by analyzer
        :type expected_data_types: list
        :return:
        """
        pass

    def stop(self, run_id, analyzer_id=''):
        """
        Stop receiving data

        :param run_id: unique id of the current run
        :type run_id: UUID
        :param analyzer_id: name or id of analyzer
        :type analyzer_id: str
        :return:
        """
        pass

    def finish(self, analyzer_id=''):
        """
        Finish up

        :param analyzer_id: name or id of analyzer
        :type analyzer_id: str
        :return:
        """
        pass


class AbstractMuonicConsumer(AbstractConsumer):
    """
    An abstract Consumer for the default muonic analyzers,
    limited to their data types, with specific methods to handle these types
    """

    def __init__(self, logger=None):
        if logger is None:
            logger = logging.getLogger(self.__module__ + '.' + self.__class__.__name__)
        self.logger = logger

    def push(self, data, data_type, run_id, analyzer_id=''):
        meta = {'run_id': run_id, 'analyzer_id': analyzer_id}
        switcher = {
            DataTypes.RAW: lambda: self.push_raw(data, meta),
            DataTypes.RATE: lambda: self.push_rate(data.get('rates') +
                                                     [data.get('max_rate')] +
                                                     [data.get('min_rate')],
                                                   data.get('counts'), data.get('time_window'),
                                                   data.get('query_time'), meta),
            DataTypes.DECAY: lambda: self.push_decay(data.get('decay_time'), data.get('event_time'), meta),
            DataTypes.VELOCITY: lambda: self.push_velocity(data.get('flight_time'), data.get('event_time'), meta),
            DataTypes.PULSE: lambda: self.push_pulse(data.get('pulse_widths'), data.get('event_time'), meta)
        }

        switcher.get(data_type, lambda: 0)()

    def push_raw(self, data, meta):
        """
        Handle raw data

        :param data: raw data from daq
        :type data: str
        :param meta: meta info (run_id and analyzer_id)
        :type meta: dict
        :return:
        """
        raise NotImplementedError

    def push_rate(self, rates, counts, time_window, query_time, meta):
        """
        Handle rate data

        :param rates: calculated rates from channels
        :type rates: list
        :param counts: pulse counts for each channel
        :type counts: list
        :param time_window: time between last two daq queries
        :type time_window float
        :param query_time: last daq query time
        :type query_time: datetime
        :param meta: meta info (run_id and analyzer_id)
        :type meta: dict
        :return:
        """
        raise NotImplementedError

    def push_pulse(self, pulse_widths, event_time, meta):
        """
        Handle pulse data

        :param pulse_widths: extracted pulse widths
        :type pulse_widths: list
        :param event_time: timestamp of pulses
        :type event_time: datetime
        :param meta: meta info (run_id and analyzer_id)
        :type meta: dict
        :return:
        """
        raise NotImplementedError

    def push_decay(self, decay_time, event_time, meta):
        """
        Handle decay data

        :param decay_time: length of decay in seconds
        :type decay_time: float
        :param event_time: time of decay
        :type event_time: datetime
        :param meta: meta info (run_id and analyzer_id)
        :type meta: dict
        :return:
        """
        raise NotImplementedError

    def push_velocity(self, flight_time, event_time, meta):
        """
        Handle velocity data

        :param flight_time: flight duration
        :type flight_time: float
        :param event_time: utc time of measurement
        :type event_time: datetime
        :param meta: meta info (run_id and analyzer_id)
        :type meta: dict
        :return:
        """
        raise NotImplementedError


class DummyConsumer(AbstractConsumer):
    """
    Prints every piece of data received to stdOut
    """

    def push(self, data, data_type, run_id, analyzer_id):
        print("Data type: %s, Data: %s" % (data_type, repr(data)))


class BufferedConsumer(AbstractConsumer):
    """
    Adds data to an in-memory queue from where it is passed to registered consumers asynchronously.
    Note: It's not guaranteed that push won't be called after stop on registered consumers.
          Such calls should be silently ignored.
    """

    def __init__(self, buffer_size, *consumers):
        self.logger = logging.getLogger(self.__module__ + '.' + self.__class__.__name__)
        self.consumers = consumers
        self.queue = Queue(buffer_size)
        self.process_thread = Thread(target=self._process_data)
        self._buffer_size = buffer_size
        self.cancel = False
        self.analyzer_count = 0
        self._joinable = False

    def start(self, run_id, analyzer_id='', expected_data_types=[]):
        for consumer in self.consumers:
            consumer.start(run_id, analyzer_id, expected_data_types)

        if self.analyzer_count == 0:
            self.logger.info('Starting buffer thread')
            self._init_process_thread()

        self.analyzer_count += 1

    def stop(self, run_id, analyzer_id=''):
        # print("DEBUG BufferedConsumer.stop START")

        self.analyzer_count -= 1

        if self.analyzer_count == 0:
            self.logger.info('Shutting down buffer thread')
            self.queue.join()
            self.queue.put(None)    # poison process_data thread
            self.process_thread.join()

        for consumer in self.consumers:
            consumer.stop(run_id, analyzer_id)

        # print("DEBUG BufferedConsumer.stop END")

    def finish(self, analyzer_id=''):
        for consumer in self.consumers:
            consumer.finish(analyzer_id)

    def push(self, data, data_type, run_id, analyzer_id=''):
        self.queue.put([data, data_type, run_id, analyzer_id])

    def _process_data(self):
        # print("DEBUG BufferedConsumer._process_data BEGIN")

        while not self.cancel:
            self.logger.debug('Processing next item. Buffer size: %d' % self.queue.qsize())

            if self.queue.full():
                self.logger.warning('Buffer limit reached')

            data = self.queue.get()

            if data is None:
                break

            for consumer in self.consumers:
                consumer.push(*data)

            self.queue.task_done()

        self._joinable = True

        # print("DEBUG BufferedConsumer._process_data END")

    def _init_process_thread(self):
        if self.process_thread.is_alive():
            return

        if self._joinable:
            self.process_thread.join()
            self._joinable = False

        self.queue = Queue(self._buffer_size)
        self.process_thread = Thread(target=self._process_data)
        self.process_thread.start()

class FileConsumer(AbstractMuonicConsumer):
    """
    Writes data to files
    """

    # TODO: This consumer can be further simplified by abstracting the string creation with formaters
    # TODO: (i.e. formater receives data and data type) - can then derive from AbstractConsumer instead
    def __init__(self, data_dir, logger = None):
        super(FileConsumer, self).__init__(logger=logger)
        self.data_dir = data_dir
        self.open_files = {}

    def __del__(self):
        self.close_files()

    def start(self, run_id, analyzer_id='', expected_data_types=[]):
        self.open_files[analyzer_id] = {}
        for dt in expected_data_types:
            try:
                self.open_files[analyzer_id][dt] = open(self.create_path(run_id, analyzer_id, dt), 'a')
            except IOError:
                self.logger.warning('Could not open file for run %s, analyzer %s, data type %s'
                                    % (run_id, analyzer_id, dt))

    def stop(self, run_id, analyzer_id=''):
        self.close_files(analyzer_id)

    def finish(self, analyzer_id=''):
        pass

    def close_files(self, analyzer_id=None):
        if analyzer_id is not None:
            for dt, file in self.open_files[analyzer_id].items():
                file.close()
                self.logger.debug('Closing %s' % file.name)
            self.open_files.pop(analyzer_id)
        else:
            for k, v in self.open_files.items():
                for dt, file in v.items():
                    file.close()
                    self.logger.debug('Closing %s' % file.name)
            self.open_files = {}

    def create_path(self, run_id, analyzer_id, data_type):
        start_date = datetime.datetime.utcnow()
        dir_name = os.path.join(self.data_dir, analyzer_id)
        if not os.path.isdir(dir_name):
            try:
                os.makedirs(dir_name)
            except OSError:
                self.logger.warning('Could not create directory for analyzer %s' % analyzer_id)

        return os.path.join(dir_name,
                            "%s_%s_%s" %
                            (start_date.strftime('%Y-%m-%d_%H-%M-%S'), run_id, data_type))

    def push_rate(self, rates, counts, time_window, query_time, meta):
        aid = meta.get('analyzer_id')
        if aid not in self.open_files:  # push called after stop for aid - ignore silently
            return
        file = self.open_files[aid].get(DataTypes.RATE, None)
        if file:
            file.write(
                "%s %f %f %f %f %f %f %f %f %f %f %f \n" %
                (query_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                 rates[0], rates[1], rates[2],
                 rates[3], rates[4],
                 counts[0], counts[1],
                 counts[2], counts[3], counts[4],
                 time_window))
        else:
            self.logger.warning('Received %s data from %s: Not in expected data types!'
                                % (DataTypes.RATE.name, meta.get('analyzer_id')))

    def push_velocity(self, flight_time, event_time, meta):
        aid = meta.get('analyzer_id')
        if aid not in self.open_files:  # push called after stop for aid - ignore silently
            return
        file = self.open_files[aid].get(DataTypes.VELOCITY, None)
        if file:
            file.write("%s %s\n" % (
                event_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                repr(flight_time)))
        else:
            self.logger.warning('Received %s data from %s: Not in expected data types!'
                                % (DataTypes.VELOCITY.name, meta.get('analyzer_id')))

    def push_decay(self, decay_time, event_time, meta):
        aid = meta.get('analyzer_id')
        if aid not in self.open_files:  # push called after stop for aid - ignore silently
            return
        file = self.open_files[aid].get(DataTypes.DECAY, None)
        if file:
            file.write("%s %d\n" % (event_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                                    decay_time))
        else:
            self.logger.warning('Received %s data from %s: Not in expected data types!'
                                % (DataTypes.DECAY.name, meta.get('analyzer_id')))

    def push_pulse(self, pulse_widths, event_time, meta):
        aid = meta.get('analyzer_id')
        if aid not in self.open_files:  # push called after stop for aid - ignore silently
            return
        file = self.open_files[aid].get(DataTypes.PULSE, None)
        if file:
            l = event_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + ' ' + ' '.join([str(value) for (key, value) in pulse_widths.items()])
            file.write(l + '\n')
        else:
            self.logger.warning('Received %s data from %s: Not in expected data types!'
                                % (DataTypes.PULSE.name, meta.get('analyzer_id')))

    def push_raw(self, data, meta):
        aid = meta.get('analyzer_id')
        if aid not in self.open_files:  # push called after stop for aid - ignore silently
            return
        file = self.open_files[aid].get(DataTypes.RAW, None)
        if file:
            file.write(data + '\n')
        else:
            self.logger.warning('Received %s data from %s: Not in expected data types!'
                                % (DataTypes.RAW.name, meta.get('analyzer_id')))


# class GuiConsumer(AbstractMuonicConsumer):
#
#     def __init__(self, daqwidget=None, ratewidget=None, pulsewidget=None,
#                  decaywidget=None, velocitywidget=None, logger=None):
#         self._daqwidget = daqwidget
#         self._ratewidget = ratewidget
#         self._pulsewidget = pulsewidget
#         self._decaywidget = decaywidget
#         self._velocitywidget = velocitywidget
#         self._running = True
#         super().__init__(logger)
#
#         self._thread = Thread(target=self._process())
#
#     def __del__(self):
#         self._running = False
#         self._thread.join()
#
#     def set_daqwidget(self, daqwidget):
#         if not isinstance(daqwidget, widgets.DAQWidget):
#             return
#
#         self._daqwidget = daqwidget
#
#     def set_ratewidget(self, ratewidget):
#         if not isinstance(ratewidget, widgets.RateWidget):
#             return
#
#         self._ratewidget = ratewidget
#
#     def set_pulsewidget(self, pulsewidget):
#         if not isinstance(pulsewidget, widgets.PulseAnalyzerWidget):
#             return
#
#         self._pulsewidget = pulsewidget
#
#     def set_decaywidget(self, decaywidget):
#         if not isinstance(decaywidget, widgets.DecayWidget):
#             return
#
#         self._decaywidget = decaywidget
#
#     def set_velocitywidget(self, velocitywidget):
#         if not isinstance(velocitywidget, widgets.VelocityWidget):
#             return
#
#         self._velocitywidget = velocitywidget
#
#     def push_raw(self, data, meta):
#         if self._daqwidget is None:
#             return
#
#     def push_rate(self, rates, counts, time_window, query_time, meta):
#         if self._ratewidget is None:
#             return
#
#         for r in rates:
#             if r > self._ratewidget.max_rate:
#                 self._ratewidget.max_rate = r
#                 self._ratewidget.update_info_field("max_rate", "%.3f 1/s" % self._ratewidget.max_rate)
#
#         data = rates
#         data.append(time_window)
#         self._ratewidget.scalars_monitor.update_plot(data)
#         self._ratewidget.update_info_field("daq_time", "%.2f s" % time_window)
#
#     def push_pulse(self, pulse_widths, event_time, meta):
#         if self._pulsewidget is None:
#             return
#
#         for i in range(4):
#             self._pulsewidget.pulse_width_canvases[i].update_plot(pulse_widths[i])
#
#
#     def push_decay(self, decay_time, event_time, meta):
#         if self._decaywidget is None:
#             return
#
#         self._decaywidget.plot_canvas.update_plot([decay_time])
#
#     def push_velocity(self, flight_time, event_time, meta):
#         if self._velocitywidget is None:
#             return
#
#         self._velocitywidget.plot_canvas.update_plot([flight_time])
#
#     def _process(self):
#         while self._running:
#             QtGui.QApplication.processEvents()
