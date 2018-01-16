#!/usr/bin/env python
from __future__ import print_function
import os
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

import muonic


def read_file(filename):
    return open(os.path.join(os.path.dirname(__file__), filename)).read()

setup(name=muonic.__name__,
      version=muonic.__version__,

      author=muonic.__author__,
      author_email=muonic.__author_email__,

      description=muonic.__description__,
      long_description=read_file("README.md"),

      license=muonic.__license__,

      url=muonic.__source_location__,
      download_url=muonic.__download_url__,

      scripts=["bin/which_tty_daq"],

      packages=["muonic", "muonic.lib", "muonic.daq", "muonic.analysis_scripts"],

      package_data={"muonic": ["settings.conf", "daq/simdaq.txt"]},

      classifiers=[
          "License :: OSI Approved :: GNU General Public License v3 or " +
          "later (GPLv3+)",
          "Development Status :: 4 - Beta",
          "Intended Audience :: Science/Research",
          "Intended Audience :: Education",
          "Intended Audience :: Developers",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3",
          "Topic :: Scientific/Engineering :: Physics"
      ],

      entry_points={
          "console_scripts": ["muonic=muonic.muonic:main"]
      })
