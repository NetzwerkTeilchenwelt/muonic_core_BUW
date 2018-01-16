
import logging
import time
import datetime
import signal
import uuid

from .analyzers import BaseAnalyzer
from .utils import PulseExtractor
from ..daq import DAQIOError


class App(object):

    _default_settings = {
        "write_daq_status": False,
        "time_window": 5.0,
        "meas_duration": None,
        "gate_width": 0.0,
        "veto": False,
        "veto_ch0": False,
        "veto_ch1": False,
        "veto_ch2": False,
        "active_ch0": True,
        "active_ch1": True,
        "active_ch2": True,
        "active_ch3": True,
        "coincidence0": True,
        "coincidence1": False,
        "coincidence2": False,
        "coincidence3": False,
        "threshold_ch0": 300,
        "threshold_ch1": 300,
        "threshold_ch2": 300,
        "threshold_ch3": 300
    }

    def __init__(self, options, analyzers=[], logger=None):

        self.daq = None

        if logger is None:
            logger = logging.getLogger(self.__module__ + '.' + self.__class__.__name__)

        self.logger = logger

        self.analyzers = [self.get_thresholds_from_msg, self.get_channels_from_msg, PulseExtractor(self.logger)]
        self.add_analyzers(analyzers)

        self._settings = App._default_settings
        self.running = False

        self.logger.debug('Got options: %s' % options)

        # import daq provider
        try:
            provider_name = options.get('data_provider', '').split('.')[-1]
            mod = __import__('%s' % '.'.join(options.get('data_provider', '').split('.')[:-1]), globals(), locals(), [provider_name])
            daq_class = getattr(mod, provider_name)
            self.daq = daq_class(sim=options.get('sim', False))
        except ImportError:
            self.logger.error('Importing DAQ provider failed')

        # last daq message
        self.last_daq_msg = False

        # store command line settings
        if 'write_daq_status' in options:
            self.update_setting("write_daq_status", options.get('write_daq_status'))
        if 'time_window' in options:
            self.update_setting("time_window", options.get('time_window'))      # FIXME: this is act. a setting for RateAnalyzer
        if 'meas_duration' in options:
            self.update_setting("meas_duration", options.get('meas_duration'))

        # we have to ensure that the DAQ card does not sent any automatic
        # status reports every x seconds if 'write_daq_status' is set to False
        if not self.get_setting('write_daq_status'):    # TODO: this should be in some status analyzer (if we need that)
            # disable status reporting
            self.daq.put('ST 0')

        # get the last configuration from the card
        self.get_configuration_from_daq_card()

        # catch signals
        signal.signal(signal.SIGINT, self.close)
        signal.signal(signal.SIGTERM, self.close)

    def update_setting(self, key, value):
        """
        Update value for settings key.

        Raises KeyError if key is None.

        :param key: settings key
        :type key: str
        :param value: setting value
        :type value: object
        :raises: KeyError
        :returns: None
        """

        if key is None:
            raise KeyError("key must not be of 'None-Type'")

        self._settings[key] = value

    def get_setting(self, key, default=None):
        """
        Retrieves the settings value for given key.

        :param key: settings key
        :type key: str
        :param default: the default value if setting is not found
        :type default: mixed
        :returns: object
        """
        return self._settings.get(key, default)

    def add_analyzer(self, analyzer):
        self.analyzers.append(analyzer)

    def add_analyzers(self, analyzers=[]):
        self.analyzers.extend(analyzers)

    def run(self, run_id = None):

        if not run_id:
            run_id = uuid.uuid4()
        self.logger.info('Analyzers: %s' % [x.__class__.__name__ for x in self.analyzers if isinstance(x, BaseAnalyzer)])
        self.running = True
        start_ts = datetime.datetime.utcnow()
        duration = self.get_setting('meas_duration')

        # setup analyzers - pass in daq handle and run_id
        for analyzer in self.analyzers:
            if isinstance(analyzer, BaseAnalyzer):
                analyzer.start(run_id, self.daq)

        self.logger.info('Running with run-id %s' % run_id)
        while self.running:
            self.process_incoming()
            time.sleep(1)

            if duration \
                    and datetime.datetime.utcnow() > start_ts + datetime.timedelta(seconds=duration):
                self.close()

    def stop(self):
        if self.running:
            self.logger.info('Stopping measurement')
            self.running = False

            # stop analyzers
            for analyzer in self.analyzers:
                if isinstance(analyzer, BaseAnalyzer):
                    analyzer.stop()

    def close(self, *args):
        self.stop()

        # finish analyzers
        for analyzer in self.analyzers:
            if isinstance(analyzer, BaseAnalyzer):
                analyzer.finish()

    def get_configuration_from_daq_card(self):
        """
        Get the initial threshold and channel configuration
        from the DAQ card.

        :returns: None
        """
        # get the thresholds
        self.daq.put('TL')
        # give the daq some time to react
        time.sleep(0.5)

        while self.daq.data_available():
            try:
                msg = self.daq.get(0)
                self.get_thresholds_from_msg(msg)

            except DAQIOError:
                self.logger.debug("Queue empty!")

        # get the channel config
        self.daq.put('DC')
        # give the daq some time to react
        time.sleep(0.5)

        while self.daq.data_available():
            try:
                msg = self.daq.get(0)
                self.get_channels_from_msg(msg)

            except DAQIOError:
                self.logger.debug("Queue empty!")

    def get_thresholds_from_msg(self, msg):
        """
        Explicitly scan message for threshold information.

        Return True if found, False otherwise.

        :param msg: daq message
        :type msg: str
        :returns: bool
        """

        # we only need the raw message here
        if isinstance(msg, dict):
            msg = msg.get('raw')

        if msg.startswith('TL') and len(msg) > 9:
            msg = msg.split('=')
            self.update_setting("threshold_ch0", int(msg[1][:-2]))
            self.update_setting("threshold_ch1", int(msg[2][:-2]))
            self.update_setting("threshold_ch2", int(msg[3][:-2]))
            self.update_setting("threshold_ch3", int(msg[4]))
            self.logger.debug("Got Thresholds %d %d %d %d" %
                              tuple([self.get_setting("threshold_ch%d" % i)
                                     for i in range(4)]))
            return False
        else:
            return True

    def get_channels_from_msg(self, msg):
        """
        Explicitly scan message for channel information.

        Return True if found, False otherwise.

        DC gives:

        DC C0=23 C1=71 C2=0A C3=00

        Which has the meaning:

        MM - 00 -> 8bits for channel enable/disable, coincidence and veto

        +---------------------------------------------------------------------+
        |                              bits                                   |
        +====+====+===========+===========+========+========+========+========+
        |7   |6   |5          |4          |3       |2       |1       |0       |
        +----+----+-----------+-----------+--------+--------+--------+--------+
        |veto|veto|coincidence|coincidence|channel3|channel2|channel1|channel0|
        +----+----+-----------+-----------+--------+--------+--------+--------+

        +-----------------+
        |Set bits for veto|
        +=================+
        |00 - ch0 is veto |
        +-----------------+
        |01 - ch1 is veto |
        +-----------------+
        |10 - ch2 is veto |
        +-----------------+
        |11 - ch3 is veto |
        +-----------------+

        +------------------------+
        |Set bits for coincidence|
        +========================+
        |00 - singles            |
        +------------------------+
        |01 - twofold            |
        +------------------------+
        |10 - threefold          |
        +------------------------+
        |11 - fourfold           |
        +------------------------+

        :param msg: daq message
        :type msg: str
        :returns: bool
        """

        # we only need the raw message here
        if isinstance(msg, dict):
            msg = msg.get('raw')

        if msg.startswith('DC ') and len(msg) > 25:
            msg = msg.split(' ')

            coincidence_time = msg[4].split('=')[1] + msg[3].split('=')[1]
            msg = bin(int(msg[1][3:], 16))[2:].zfill(8)
            veto_config = msg[0:2]
            coincidence_config = msg[2:4]
            channel_config = msg[4:8]

            self.update_setting("gate_width", int(coincidence_time, 16) * 10)

            # set default veto config
            for i in range(4):
                if i == 0:
                    self.update_setting("veto", True)
                else:
                    self.update_setting("veto_ch%d" % (i - 1), False)

            # update channel config
            for i in range(4):
                self.update_setting("active_ch%d" % i,
                               channel_config[3 - i] == '1')

            # update coincidence config
            for i, seq in enumerate(['00', '01', '10', '11']):
                self.update_setting("coincidence%d" % i,
                               coincidence_config == seq)

            # update veto config
            for i, seq in enumerate(['00', '01', '10', '11']):
                if veto_config == seq:
                    if i == 0:
                        self.update_setting("veto", False)
                    else:
                        self.update_setting("veto_ch%d" % (i - 1), True)

            self.logger.debug('gate width time window %d ns' %
                              self.get_setting("gate_width"))
            self.logger.debug("Got channel configurations: %d %d %d %d" %
                              tuple([self.get_setting("active_ch%d" % i)
                                     for i in range(4)]))
            self.logger.debug("Got coincidence configurations: %d %d %d %d" %
                              tuple([self.get_setting("coincidence%d" % i)
                                     for i in range(4)]))
            self.logger.debug("Got veto configurations: %d %d %d %d" %
                              tuple([self.get_setting("veto")] +
                                    [self.get_setting("veto_ch%d" % i)
                                     for i in range(3)]))

            return False
        else:
            return True

    def process_incoming(self):
        """
        This functions gets everything out of the daq.

        Handles all the messages currently in the daq
        and passes the results to the corresponding widgets.

        :returns: None
        """
        while self.daq.data_available():
            try:
                msg = self.daq.get(0)
            except DAQIOError:
                self.logger.debug("Queue empty!")
                return None

            # make daq msg public for child widgets
            self.last_daq_msg = msg

            # transform to dict - analyzers can add data to it as it passes the analysis stack
            msg = {'raw': msg}

            # iterate over analyzers and process message
            for analyzer in self.analyzers:
                if not isinstance(analyzer, BaseAnalyzer) or analyzer.active:
                    if not analyzer(msg): break

            """

            #TODO: replace qt dependencies!!! (check widgets.py)

            # ignore status messages
            if msg.startswith('ST') or len(msg) < 50:
                continue

            # extract pulses if needed
            if (self.get_setting("write_pulses")): # or
                    #self.is_widget_active("pulse") or
                    #self.is_widget_active("decay") or
                    #self.is_widget_active("velocity")):
                self.pulses = self.pulse_extractor.extract(msg)
            
            """
