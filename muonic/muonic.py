import os
import configargparse
import logging
from .lib.app import App
from .lib.analyzers import DummyAnalyzer, RateAnalyzer, PulseAnalyzer, DecayAnalyzer, VelocityAnalyzer
from .lib.consumers import DummyConsumer, FileConsumer, BufferedConsumer

# setup logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# create file handler which logs even debug messages
fh = logging.FileHandler('muonic.log')
fh.setLevel(logging.DEBUG)

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# create formatter and add it to the handlers
file_formatter = logging.Formatter('%(asctime)s - %(name)s: %(levelname)s - %(message)s')
console_formatter = logging.Formatter('%(name)s: %(levelname)s - %(message)s')
fh.setFormatter(file_formatter)
ch.setFormatter(console_formatter)

# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)

def main():

    #p = configargparse.YAMLConfigFileParser() #TODO: Yaml would be better

    p = configargparse.ArgParser(default_config_files=['settings.conf'])

    p.add('-c', '--config-file', required=False, is_config_file=True, help='config file path')
    p.add('-d', '--data-provider', required=False)
    p.add("-s", "--sim", dest="sim", help="use simulation mode for testing without hardware",
          action="store_true", default=False)
    p.add("--port", dest="port", help="listen to daq on port ", default=None)
    p.add("-t", "--timewindow", dest="time_window",
          help="time window for the measurement in s (default 5s)",
          type=float, default=5.0)
    p.add("-m", "--measurement-duration", dest="meas_duration", required=False,
          help="Duration of measurement in seconds", type=float)
    #p.add("-d", "--debug", dest="log_level", help="switch to loglevel debug", action="store_const", const=logging.DEBUG, default=logging.INFO)
    p.add("-n", "--nostatus", dest="write_daq_status",
          help="do not write DAQ status messages to RAW data files",
          action="store_false", default=True)
    p.add("-v", "--version", dest="version", help="show current version", action="store_true", default=False)

    # Consumers:
    p.add("--raw", dest="raw_consumer", help="View raw DAQ data", action="store_true", default=False)
    p.add("-P", "--data-path", dest="data_path", help="Store measurement data in the specified directory",
          type=str, default=None)
    p.add("-M", "--MySQL", nargs=3, metavar=('HOST', 'USER', 'DATABASE'),
          help="Stream measurement data to database. Arguments are: host user database - in this order")
    p.add("--MySQL-db-user-id", help="ID of user in 'users' table to be associated with the current measurements",
          dest="mysql_db_user_id", default=0, required=False)
    p.add("-D", "--Django", nargs=1, metavar=("USER"), help="Initialize Django consumer with USER", default=None)
    p.add("-G", "--GUI", dest="GUI", help="Invoke GUI", action="store_true", default=False)

    # Analyzers
    p.add("--buffer-size", dest="buf_size", help="Buffer size for analyzed data", type=int, default=255)
    p.add("--rate", dest="rate_analyzer", help="Analyze rates", action="store_true", default=False)
    p.add("--pulse", dest="pulse_analyzer", help="Analyze pulses", action="store_true", default=False)
    p.add("--decay", dest="decay_analyzer", help="Analyze decays", action="store_true", default=False)
    p.add("--velocity", dest="velocity_analyzer", help="Analyze velocity", action="store_true", default=False)

    options = vars(p.parse_args())

    consumers = []

    # consumers.append(DummyConsumer())

    if options.get("raw_consumer"):
        consumers.append(DummyConsumer())

    if options.get('data_path') is not None:
        consumers.append(FileConsumer(data_dir=options.get("data_path"), logger=logger))

    if options.get("Django") is not None:
        try:
            import django
            from django.conf import settings
            from muonic_django.consumer import Consumer as DjangoConsumer

        except:
            raise ImportError("Django consumer optional dependency missing")

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "muonic_webapp.settings")
        django.setup()

        consumers.append(DjangoConsumer(simulation=options.get("sim"),
                                        username=options.get("Django")[0]))

    if options.get("MySQL") is not None:
        try:
            from muonic_mysql.consumer import MySqlConsumer
        except:
            raise ImportError("MySQL consumer optional dependency missing")

        consumers.append(MySqlConsumer(options))

    analyzers = []

    # analyzers.append(DummyAnalyzer(consumers=[bf], **options))

    if options.get("GUI"):
        # TODO: move analyzers, consumers, bf to application.py, maybe __init__ -> property or so?
        try:
            from muonic_gui.gui import Application
        except:
            raise ImportError("muonic_gui optional dependency missing")

        try:
            from PyQt4.QtGui import QApplication
        except:
            raise ImportError("Qt4 optional dependency missing")

        root = QApplication([])
        root.setQuitOnLastWindowClosed(True)

        app = Application(logger=logger, opts=options,
                          consumers=consumers)

        app.showMaximized()

        root.exec()

        # gui_consumer = GuiConsumer(logger=logger)
        # consumers.append(gui_consumer)
        #
        # bf = BufferedConsumer(1000, *consumers)
        #

    else:
        # if options.get("decay_analyzer") and options.get("velocity_analyzer"):
        #     raise RuntimeError("Cannot analyze decay and velocity")

        bf = [BufferedConsumer(options.get("buf_size"), *consumers)]

        if options.get("rate_analyzer"):
           analyzers.append(RateAnalyzer(consumers=bf, **options))

        if options.get("pulse_analyzer"):
            analyzers.append(PulseAnalyzer(consumers=bf, **options))

        if options.get("decay_analyzer"):
            analyzers.append(DecayAnalyzer(consumers=bf, **options))

        if options.get("velocity_analyzer"):
            analyzers.append(VelocityAnalyzer(consumers=bf, **options))

        app = App(options=options, analyzers=analyzers, logger=logger)
        app.run()

#"""
