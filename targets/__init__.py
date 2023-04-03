#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of Beremiz, a Integrated Development Environment for
# programming IEC 61131-3 automates supporting plcopen standard and CanFestival.
#
# Copyright (C) 2007: Edouard TISSERANT and Laurent BESSARD
# Copyright (C) 2017: Andrey Skvortsov
#
# See COPYING file for copyrights details.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# Package initialisation


from os import listdir, path
import util.paths as paths
import importlib
from .toolchain_pio import XSD as PIO_XSD
import sys

_base_path = paths.AbsDir(__file__)


def GetBuilder(targetname):
    return (lambda: getattr(
        importlib.import_module(f"targets.{targetname}"),
        f"{targetname}_target"))()


def GetTargetChoices():
    return PIO_XSD


def GetTargetCode(targetname):

    name = "Linux"
    if sys.platform.startswith('darwin'):
        name = "OSX"
    elif sys.platform.startswith('win'):
        name = "Win32"

    codedesc = {
        fname: path.join(_base_path, name, fname)
        for fname in listdir(path.join(_base_path, name))
        if (fname.startswith(f"plc_{name}_main")
            and fname.endswith(".c"))}
    code = "\n".join([open(fpath).read()
                     for _fname, fpath in sorted(codedesc.items())])
    return code


def GetHeader():
    filename = paths.AbsNeighbourFile(__file__, "beremiz.h")
    return open(filename).read()


def GetCode(name):
    filename = paths.AbsNeighbourFile(__file__, name)
    return open(filename).read()
