# script to convert daq raw files to muonic pulse files
#
# output format (relative time, [(re0_channel0,fe0_channel0),
#                                (re1_channel0,fe1_channel0),...],
#                               [(..],[..],[..])
# -> each channel is represented by a list of leading/falling edge
#    tuples of the recorded pulses
#
from __future__ import print_function
import logging
import re
import sys

from muonic.analysis.analyzer import PulseExtractor


def daq_converter():
    pe = PulseExtractor(logging.getLogger(), '')

    f = open(sys.argv[1])

    converted_file = open("converted.txt", "w")

    # match against this to supress daq garbage
    good_pattern = re.compile("^[a-zA-Z0-9+-.,:()=$/#?!%_@*|~' ]*[\n\r]*$")

    for line in f.readlines():
        if good_pattern.match(line) is None:
            continue
        try:
            pulses = pe.extract(line)
        except Exception as e:
            print(line, "Failed to convert", e)
            continue

        if pulses is not None:
            converted_file.write(pulses.__repr__() + "\n")
    

if __name__ == "__main__":
    daq_converter()
