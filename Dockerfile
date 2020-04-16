#FROM theshadowx/qt5:latest
FROM ubuntu:18.04
RUN rm /bin/sh && ln -s /bin/bash /bin/sh

ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8

RUN sed -i 's/ universe/ universe multiverse/' /etc/apt/sources.list

ENV TZ=Europe/Berlin
ENV DEBIAN_FRONTEND="noninteractive"
RUN apt install
RUN apt update
RUN apt -y dist-upgrade
RUN apt -y install \
    libgl1-mesa-glx \
    cm-super \
    dvipng \
    texlive-base \
    texlive-binaries \
    texlive-fonts-recommended \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-latex-recommended \
    texlive-pictures \
    texlive-plain-generic \
    python3 \
    python3-pip \
    git                        \
    wget                       \
    xvfb                       \
    flex                       \
    dh-make                    \
    debhelper                  \
    checkinstall               \
    fuse                       \
    snapcraft                  \
    bison                      \
    libxcursor-dev             \
    libxcomposite-dev          \
    software-properties-common \
    build-essential            \
    libssl-dev                 \
    libxcb1-dev                \
    libx11-dev                 \
    libgl1-mesa-dev            \
    libudev-dev                \
    qt5-default                \
    software-properties-common \
    qtbase5-private-dev &&\
    apt clean


RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt update
RUN apt -y install python3.7
RUN mkdir /app
WORKDIR /app

RUN git clone https://github.com/wutzi15/muonic_core_BUW.git
WORKDIR /app/muonic_core_BUW
RUN cp muonic/settings.conf /app

RUN python3.7 -m pip install ConfigArgParse future numpy serial matplotlib scipy PyQt5==5.9.2
RUN python3.7 setup.py install

WORKDIR /app
RUN git clone https://github.com/wutzi15/muonic_gui_BUW.git
WORKDIR /app/muonic_gui_BUW
RUN python3.7 setup.py install


WORKDIR /app