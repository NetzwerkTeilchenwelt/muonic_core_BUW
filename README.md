# muonic - a python application for QNET experiments

The muonic project provides an interface to communicate with QuarkNet DAQ cards and to perform simple analysis of the generated data.
Its goal is to ensure easy and stable access to the QuarkNet cards and visualize some of the features of the cards. It is meant to be used in school projects, so it should be easy to use even by people who do not have lots of LINUX backround or experience with scientific software. Automated data taking ensures no measured data is lost.

## License and terms of agreement

Muonic is distributed under the terms of GPL (GNU Public License). With the use of the software you accept the conditions of the GPL. This also means that the authors cannot be made responsible for any damage of any kind of hard- or software.

## muonic setup and installation

Muonic consists of a core lib and a number of add-ons. Currently available are:

1. **muonic_gui:** PyQt5 GUI
1. **muonic_mysql:** Streams measurement data to a MySQL database
1. **muonic_django:** Streams measurement data to the database of a Django project
1. **muonic_webapp:** Django example project that uses muonic_django

### prerequisites

muonic (and its add-ons) is distributed via [conda](https://conda.io/docs).
You can either install single packages with `conda install <PACKAGE-NAME> -c phyz777` or use one of the distributed environments ([full](https://github.com/phyz777/muonic_core_BUW/blob/dev_GUI_consumer_app/muonic_BUW_full.yaml), [minimal](https://github.com/phyz777/muonic_core_BUW/blob/dev_GUI_consumer_app/muonic_BUW_min.yaml)) with `conda env create --file <FILE>`.

### preparing your computer to connect to the DAQ card

The DAQ card uses a serial connection via the USB port. If muonic does not find the DAQ card even though it is connected to the computer, try adding the user that you use for login to the group dialout:

`sudo adduser username dialout`.

# How to use muonic

## start muonic

Use `muonic -h/--help` to get started.
You should supply some configuration, a number of measurement types and a number of ways to present data.
An easy configuration uses: `muonic -c ~/.muonic.conf/settings.conf`. This default [configuration file](https://github.com/phyz777/muonic_core_BUW/blob/dev_GUI_consumer_app/muonic/settings.conf) is distributed with Linux distributions and can be manually downloaded for Windows systems.

Availible measurement types are:

- `--rate`
- `--pulse`
- `--decay`
- `--velocity`

Available data presentations are:

- `--raw`
- `--data-path <PATH>`

Add-ons extend the number of available presentations.

## Build with Docker

Just run `docker build -t muonic .`.

## Running on Mac

Basically follow this link to setup a GUI on macOS (https://cntnr.io/running-guis-with-docker-on-mac-os-x-a14df6a76efc)[https://cntnr.io/running-guis-with-docker-on-mac-os-x-a14df6a76efc]. The steps are listed below

### Install dependencies

- `brew install socat xquartz`
- Open XQuartz and in settings open the advances tab. Here allow connections from network clients.
- `socat TCP-LISTEN:6000,reuseaddr,fork UNIX-CLIENT:\"\$DISPLAY\"` Run the GUI with your IP:
- `docker run -e DISPLAY=<YOUR_IP>:0 -v /dev:/dev --privileged -it muonic muonic -G`

## Representation of the pulses:

`(69.15291364, [(0.0, 12.5)], [(2.5, 20.0)], [], [])`

This is a python-tuple which contains the trigger time of the event and four lists with more tuples. The lists represent the channels (0-3 from left to right) and each tuple stands for a leading and a falling edge of a registered pulse. To get the exact time of the pulse start, one has to add the pulse LE and FE times to the triggertime

_For calculation of the LE and FE pulse times a TMC is used. It seems that for some DAQs cards a TMC bin is 1.25 ns wide, although the documentation says something else.
The trigger time is calculated using a CPLD which runs in some cards at 25MHz, which gives a bin width of the CPLD time of 40 ns.
Please keep this limited precision in mind when adding CPLD and TMC times._
