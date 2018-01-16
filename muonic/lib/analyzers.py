
from enum import Enum
import logging
import datetime
import time
import threading
from muonic.daq.provider import BaseDAQProvider
from .utils import DecayTriggerThorough, VelocityTrigger


class DataTypes(Enum):
    """
    Basic Muonic result data types. Can be consumed by MuonicConsumers
    """
    RAW = 1
    RATE = 2
    PULSE = 3
    DECAY = 4
    VELOCITY = 5

    def __eq__(self, other):
        return self.value == other or self.name == other

    def __hash__(self):
        return self.value

    def __str__(self):
        return self.name


class BaseAnalyzer(object):

    RESULT_DATA_TYPES = []

    def __init__(self, consumers=[], logger=None):
        if logger is None:
            logger = logging.getLogger(self.__module__ + '.' + self.__class__.__name__)
        self.logger = logger
        self.daq = None
        self._active = False
        self._disabled = False
        self._last_run_id = None
        self._last_daq = None
        self.consumers = consumers
        self.current_run_id = None

    def __call__(self, *args, **kwargs):
        return self.calculate(*args)

    def calculate(self, msg):
        """
        Calculates data related to this analyzer.
        Returns True if the analysis chain should continue, False otherwise

        :param msg: message from daq
        :type msg: dict
        :returns: bool
        """
        return True

    def publish(self, data, data_type):
        """
        Publish results to consumers

        :param data: the data
        :param data_type: the type of data published
        :return:
        """
        if not self.active:
            return

        for consumer in self.consumers:
            consumer.push(data, data_type, self.current_run_id, self.__class__.__name__)

    @property
    def active(self):
        """
        Getter for active

        :returns: bool
        """
        return self._active

    @property
    def disabled(self):
        """
        Getter for disabled

        :return: bool
        """
        return self._disabled

    @disabled.setter
    def disabled(self, val):
        """
        Setter for disabled

        :param val: new value
        :return:
        """
        # print("DEBUG BaseAnalyzer.disabled.setter START")

        if val is True:
            if self.active:
                self._last_run_id = self.current_run_id
                self._last_daq = self.daq
                self._active = False

                for consumer in self.consumers:
                    consumer.stop(self.current_run_id, self.__class__.__name__)

                self.current_run_id = None
                self.daq = None
            self._disabled = True
        elif val is False:
            self._disabled = False

            if self._last_run_id is not None:
                self.start(self._last_run_id, self._last_daq)

        # print("DEBUG BaseAnalyzer.disabled.setter END")

    def start(self, run_id, daq=None):
        """
        Perform setup here like resetting variables when the
        widget goes into active state

        :return: None
        """
        # print("DEBUG BaseAnalyzer.start START")

        if not self.disabled:
            self.daq = daq

            self.current_run_id = run_id
            if not self.active:
                self._active = True

                for consumer in self.consumers:
                    consumer.start(run_id, self.__class__.__name__, self.RESULT_DATA_TYPES)
        else:
            self._last_run_id = run_id
            self._last_daq = daq

        # print("DEBUG BaseAnalyzer.start END")

    def stop(self):
        """
        Perform actions like saving data when the widget goes
        into inactive state

        :return:
        """
        # print("DEBUG BaseAnalyzer.stop START")

        self._last_run_id = None
        self._last_daq = None

        if not self.active:
            # print("DEBUG BaseAnalyzer.stop END")

            return

        if not self.disabled:
            for consumer in self.consumers:
                consumer.stop(self.current_run_id, self.__class__.__name__)

            self.current_run_id = None
            self._active = False

        # print("DEBUG BaseAnalyzer.stop END")

    def daq_put(self, msg):
        """
        Send message to DAQ cards. Reuses the connection of the parent widget
        if present.

        Returns True if operation was successful.

        :param msg: message to send to the DAQ card
        :type msg: str
        :returns: bool
        """
        if self.daq is None:
            self.logger.error("no daq handle found")
            return False

        if isinstance(self.daq, BaseDAQProvider):
            self.daq.put(msg)
            return True
        return False

    def finish(self):
        """
        Gets called upon closing application. Implement cleanup routines like
        closing files here.

        :returns: None
        """
        # print("DEBUG BaseAnalyzer.finish START")

        for consumer in self.consumers:
            consumer.finish(self.__class__.__name__)

        # print("DEBUG BaseAnalyzer.finish END")


class DummyAnalyzer(BaseAnalyzer):

    RESULT_DATA_TYPES = [DataTypes.RAW]

    def __init__(self, consumers=[], logger=None, **options):
        super().__init__(consumers, logger)

    def calculate(self, msg):
        raw_msg = msg.get('raw')
        if 'pulses' in msg:
            self.logger.debug('Pulses: %s' % str(msg.get('pulses')))
        else:
            self.logger.debug('Message has no pulses')
        self.publish(raw_msg, DataTypes.RAW)
        return True


class RateAnalyzer(BaseAnalyzer):

    RESULT_DATA_TYPES = [DataTypes.RATE]
    SCALAR_BUF_SIZE = 5

    def __init__(self, consumers=[], logger=None, **options):
        # print("DEBUG RateAnalyzer.__init__ START")

        super().__init__(consumers, logger)

        # time window for updates
        self.update_interval = float(options.get('time_window', 1.0))

        # measurement start and duration
        self.measurement_duration = datetime.timedelta()
        self.start_time = datetime.datetime.utcnow()

        # define the begin of the time interval for the rate calculation
        self.last_query_time = 0
        self.query_time = time.time()
        self.time_window = 0
        self.show_trigger = True
        self.last_data = {}

        # lists of channel and trigger scalars
        # 0..3: channel 0-3
        # 4:    trigger
        self.previous_scalars = self.new_scalar_buffer()
        self.scalar_buffer = self.new_scalar_buffer()

        # maximum and minimum seen rate across channels and trigger
        self.max_rate = 0
        self.min_rate = 99999999999999999999999999999999999

        # we will write the column headers of the data into
        # data_file in the first run
        self.first_run = True

        # are we in first cycle after start button is pressed?
        self.first_cycle = False

        # rates store
        self.rates = None

        # setup update thread
        self.update_thread = threading.Thread(target=self.update_loop)

        self._joinable = False

        # print("DEBUG RateAnalyzer.__init__ END")

    def start(self, run_id, daq=None):
        # print("DEBUG RateAnalyzer.start START")

        super().start(run_id, daq)

        self.start_time = datetime.datetime.utcnow()

        # time.sleep(0.2)

        self.first_cycle = True
        self.time_window = 0

        # reset scalar buffer
        self.scalar_buffer = self.new_scalar_buffer()

        # start update thread
        self.init_update_thread()

        # print("DEBUG RateAnalyzer.start END")

    def stop(self):
        # print("DEBUG RateAnalyzer.stop START")

        super().stop()

        self.update_thread.join()

        # print("DEBUG RateAnalyzer.stop END")

    def update_loop(self):
        # print("DEBUG RateAnalyzer.update_loop START")

        while self.active:
            # send the rates to the consumers, clear buffer
            if self.last_data and self.last_data['query_time'] != self.last_query_time \
                    and self.last_data['time_window'] >= self.update_interval:
                self.publish(self.last_data, DataTypes.RATE)

            self.last_data = {}

            # request new scalars
            self.logger.debug('Query for scalars')
            self.query_daq_for_scalars()
            time.sleep(self.update_interval)

        self._joinable = True

        # print("DEBUG RateAnalyzer.update_loop END")

    def new_scalar_buffer(self):
        """
        Return new zeroed list of self.SCALAR_BUF_SIZE

        :returns: list of int
        """
        return [0] * self.SCALAR_BUF_SIZE

    def query_daq_for_scalars(self):
        """
        Send command to DAQ to query for scalars.

        :returns: None
        """
        self.last_query_time = self.query_time
        self.daq_put("DS")
        self.query_time = time.time()

    def extract_scalars_from_message(self, msg):
        """
        Extracts the scalar values for channel 0-3 and
        the trigger channel from daq message

        :param msg: DAQ message
        :type: str
        :return: list of ints
        """
        scalars = self.new_scalar_buffer()

        for item in msg.split():
            for i in range(self.SCALAR_BUF_SIZE):
                if item.startswith("S%d" % i) and len(item) == 11:
                    scalars[i] = int(item[3:], 16)

        return scalars

    def calculate(self, msg_dict):
        """
        Get the rates from the observed counts by dividing by the
        measurement interval.

        :returns: bool
        """

        # get the raw message
#        print("DEBUG RateAnalyzer.calculate START")

        msg = msg_dict.get('raw')

        if not (len(msg) >= 2 and msg.startswith("DS")):
            #self.query_daq_for_scalars()

#            print("DEBUG RateAnalyzer.calculate END")

            return True

        # extract scalars from daq message
        scalars = self.extract_scalars_from_message(msg)

        # if this is the first time calculate is called, we want to set all
        # counters to zero. This is the beginning of the first bin.
        if self.first_cycle:
            self.logger.debug("Buffering muon counts for the first bin " +
                              "of the rate plot.")
            self.previous_scalars = scalars
            self.first_cycle = False

 #           print("DEBUG RateAnalyzer.calculate END")

            return True

        # initialize temporary buffers for the scalar diffs
        scalar_diffs = self.new_scalar_buffer()

        # calculate differences and store current scalars for reuse
        # in the next cycle
        for i in range(self.SCALAR_BUF_SIZE):
            if scalars[i] > 0:  # discard erroneous scalars
                scalar_diffs[i] = scalars[i] - self.previous_scalars[i]
                self.previous_scalars[i] = scalars[i]
            else:
#                print("DEBUG RateAnalyzer.calculate END")

                return True

        time_window = self.query_time - self.last_query_time

        # rates for scalars of channels and trigger
        self.rates = [(_scalar / time_window) for _scalar in scalar_diffs]
        # current time window
        self.rates += [time_window]
        # scalars for channels and trigger
        self.rates += [_scalar for _scalar in scalar_diffs]

        self.time_window += time_window

        # add scalar diffs for channels and trigger to buffer
        self.scalar_buffer = [x + scalar_diffs[i]
                              for i, x in enumerate(self.scalar_buffer)]

        # get minimum and maximum rate
        # min_rate = min(self.rates[:5])
        # max_rate = max(self.rates[:5])
        #
        # update minimum and maximum rate if needed
        # if min_rate < self.min_rate:
        #     self.min_rate = min_rate
        # if max_rate > self.max_rate:
        #     self.max_rate = max_rate

        if self.rates[4] < self.min_rate:
            self.min_rate = self.rates[4]

        if self.rates[4] > self.max_rate:
            self.max_rate = self.rates[4]

        # buffer the data
        self.last_data = {
            'rates': self.rates[:5],
            'counts': scalars,
            'max_rate': self.max_rate,
            'min_rate': self.min_rate,
            'time_window': time_window,
            'query_time': datetime.datetime.utcfromtimestamp(self.query_time)
        }

#        print("DEBUG RateAnalyzer.calculate END")

        return True

    def init_update_thread(self):
        # print("DEBUG RateAnalyzer.init_update_thread START")

        if self.update_thread.is_alive():
            return

        if self._joinable:
            self.update_thread.join()
            self._joinable = False

        self.update_thread = threading.Thread(target=self.update_loop)
        self.update_thread.start()

        # print("DEBUG RateAnalyzer.init_update_thread END")

class DecayAnalyzer(BaseAnalyzer):
    """
    Searches for muon decays
    ATTENTION: This analyzer seems to be incompatible with the velocity analyzer

    """

    RESULT_DATA_TYPES = [DataTypes.DECAY]

    def __init__(self, consumers=[], logger=None, **options):
        super().__init__(consumers, logger)

        # default decay configuration
        self.min_single_pulse_width = options.get('min_single_pulse_width', 0)
        self.max_single_pulse_width = options.get('max_single_pulse_width', 12000)    # inf
        self.min_double_pulse_width = options.get('min_double_pulse_width', 0)
        self.max_double_pulse_width = options.get('max_double_pulse_width', 12000)    # inf
        self.muon_counter = 0
        self.single_pulse_channel = options.get('single_pulse_channel', 0)
        self.double_pulse_channel = options.get('double_pulse_channel', 1)
        self.veto_pulse_channel = options.get('veto_pulse_channel', 2)
        self.decay_min_time = options.get('decay_min_time', 0)

        self.last_event_time = None
        self.active_since = None

        # measurement duration and start time
        self.measurement_duration = datetime.timedelta()
        self.start_time = datetime.datetime.utcnow()

        self.previous_coinc_time_03 = "00"
        self.previous_coinc_time_02 = "0A"

        # decay trigger
        self.trigger = DecayTriggerThorough()

        self.running_status = None

    def set_previous_coincidence_times(self, time_03, time_02):
        """
        Sets the previous coincidence times obtained from the DAQ card

        :param time_03: time 03
        :type time_03: str
        :param time_02: time 03
        :type time_02: str
        :return:
        """
        self.previous_coinc_time_03 = time_03
        self.previous_coinc_time_02 = time_02

    def calculate(self, msg):
        """
        Trigger muon decay

        :param msg: daq message
        :type msg: dict
        :returns: bool
        """

        # update previous coincidence config
        raw_msg = msg.get('raw')
        if raw_msg.startswith('DC') and len(raw_msg) > 2:
            try:
                split_msg = raw_msg.split(" ")
                t_03 = split_msg[4].split("=")[1]
                t_02 = split_msg[3].split("=")[1]
                self.set_previous_coincidence_times(t_03, t_02)
            except Exception:
                self.logger.debug('Wrong DC command.')
            return True

        if 'pulses' not in msg:
            return True
        pulses = msg.get('pulses')

        if pulses is None:
            return True

        self.logger.info('Got pulses: %s' % str(pulses))

        decay = self.trigger.trigger(
                pulses[1:], single_channel=self.single_pulse_channel,
                double_channel=self.double_pulse_channel,
                veto_channel=self.veto_pulse_channel,
                min_decay_time=self.decay_min_time,
                min_single_pulse_width=self.min_single_pulse_width,
                max_single_pulse_width=self.max_single_pulse_width,
                min_double_pulse_width=self.min_double_pulse_width,
                max_double_pulse_width=self.max_double_pulse_width)

        if decay is not None:
            when = datetime.datetime.utcnow()
            self.muon_counter += 1
            self.last_event_time = when
            self.logger.info("We have found a decaying muon with a " +
                             "decay time of %f at %s" % (decay, when))
            self.logger.info("Muon count: %s" % self.muon_counter)

            self.publish({'decay_time': decay / 1000, 'event_time': when}, DataTypes.DECAY)
        else:
            self.logger.info('Decay was None')

        return True

    def start(self, run_id, daq=None):
        """
        Start check for muon decay

        :returns: None
        """
        super().start(run_id, daq)

        self.active_since = datetime.datetime.utcnow()

        # if self.parent.is_widget_active("decay"):
        #    self.parent.get_widget("velocity").stop()

        self.logger.warning("We now activate the muon decay mode!\n" +
                         "All other Coincidence/Veto settings will " +
                         "be overridden!")

        self.logger.warning("Changing gate width and enabeling pulses")
        self.logger.info("Looking for single pulse in Channel %d" %
                         (self.single_pulse_channel - 1))
        self.logger.info("Looking for double pulse in Channel %d" %
                         (self.double_pulse_channel - 1))
        self.logger.info("Using veto pulses in Channel %i" %
                         (self.veto_pulse_channel - 1))

        # configure DAQ card with coincidence/veto settings
        self.daq_put("DC")
        self.daq_put("CE")
        self.daq_put("WC 03 04")
        self.daq_put("WC 02 0A")

        # this should set the veto to none (because we have a
        # software veto) and the coincidence to single,
        # so we take all pulses
        self.daq_put("WC 00 0F")

        self.start_time = datetime.datetime.utcnow()

        # restart rate measurement
        #self.parent.get_widget("rate").stop()
        #self.parent.get_widget("rate").start()
        # needs pulses!

    def stop(self):
        """
        Stop check for muon decay

        :returns: None
        """
        super().stop()

        stop_time = datetime.datetime.utcnow()
        self.measurement_duration += stop_time - self.start_time

        # reset coincidence times
        self.daq_put("WC 03 " + self.previous_coinc_time_03)
        self.daq_put("WC 02 " + self.previous_coinc_time_02)

    def finish(self):
        """
        Cleanup, close and rename decay file

        :returns: None
        """
        super().finish()

        stop_time = datetime.datetime.utcnow()

        # add duration
        self.measurement_duration += stop_time - self.start_time


class VelocityAnalyzer(BaseAnalyzer):
    """
    Calculate muon flight time between two channels
    ATTENTION: This analyzer seems to be incompatible with the DecayAnalyzer

    """
    RESULT_DATA_TYPES = [DataTypes.VELOCITY]

    def __init__(self, consumers=[], logger=None, **options):
        super().__init__(consumers, logger)

        self.upper_channel = options.get('upper_channel', 0)
        self.lower_channel = options.get('lower_channel', 1)
        self.muon_counter = 0

        self.last_event_time = None

        # measurement duration and start time
        self.measurement_duration = datetime.timedelta()
        self.start_time = datetime.datetime.utcnow()

        # velocity trigger
        self.trigger = VelocityTrigger()
        self.running_status = None

    def calculate(self, msg):
        """
        Trigger muon flight

        :param pulses: extracted pulses
        :type pulses: list
        :returns: None
        """

        pulses = msg.get('pulses', None)

        if pulses is None:
            return True

        flight_time = self.trigger.trigger(pulses[1:],
                                           upper_channel=self.upper_channel,
                                           lower_channel=self.lower_channel)

        if flight_time is not None and flight_time > 0:
            self.muon_counter += 1
            self.last_event_time = datetime.datetime.utcnow()
            self.logger.info("measured flight time %s" % flight_time)
            self.publish(
                {'flight_time': flight_time, 'event_time': self.last_event_time, 'muon_count': self.muon_counter},
                DataTypes.VELOCITY
            )

        return True

    def start(self, run_id, daq=None):
        super().start(run_id, daq)

        # switch off decay measurement - incompatible!!!

        self.start_time = datetime.datetime.utcnow()

        # restart rate measurement!
        # self.parent.get_widget("rate").stop()
        # self.parent.get_widget("rate").start()

        # enable counter
        self.daq_put("CE")

    def stop(self):
        super().stop()

        stop_time = datetime.datetime.utcnow()
        self.measurement_duration += stop_time - self.start_time

        self.logger.info("Muon velocity mode now deactivated, returning to " +
                         "previous setting (if available)")


class PulseAnalyzer(BaseAnalyzer):

    RESULT_DATA_TYPES = [DataTypes.PULSE]

    def __init__(self, consumers=[], logger=None, **options):
        super().__init__(consumers, logger)

    def calculate(self, msg):
        """
        Calculates the pulse widths.

        :param msg: daq message
        :type msg: dict
        :returns: bool
        """

        if 'pulses' not in msg:
            return True

        pulses = msg.get('pulses')

        if pulses is None:
            self.logger.debug("Not received any pulses")
            return True

        # pulse_widths changed because falling edge can be None.
        # pulse_widths = [fe - le for chan in pulses[1:] for le,fe in chan]

        pulse_widths = {i: [] for i in range(4)}
        pulse_timestamp = datetime.datetime.utcnow()

        for i, channel in enumerate(pulses[1:]):
            for le, fe in channel:
                if fe is not None:
                    pulse_widths[i].append(fe - le)
                else:
                    pulse_widths[i].append(0.)

        self.publish({'pulse_widths': pulse_widths, 'event_time': pulse_timestamp}, DataTypes.PULSE)

        return True

    def start(self, run_id, daq=None):
        """
        Starts the pulse analyzer

        :returns: None
        """
        super().start(run_id, daq)

        self.logger.debug("switching on pulse analyzer.")

        self.daq_put("CE")

    def stop(self):
        """
        Stops the pulse analyzer

        :returns: None
        """
        super().stop()

        self.logger.debug("switching off pulse analyzer.")

