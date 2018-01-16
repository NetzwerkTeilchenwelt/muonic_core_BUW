"""
Utility classes and functions needed by DAQ related modules
"""


class DAQIOError(IOError):
    """
    DAQ IOError Exception class
    """
    pass


class DAQMissingDependencyError(Exception):
    """
    Exception class which is thrown if runtime dependencies are not met
    """
    pass
