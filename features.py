#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of Beremiz
#
# Copyright (C) 2007: Laurent BESSARD
# Copyright (C) 2007-2018: Edouard TISSERANT
#
# See COPYING file for copyrights details.

libraries = [
    ('Native', 'NativeLib.NativeLibrary', True),
]

catalog = [
    ('c_ext', _('C extension'), _('Add C code accessing located variables synchronously'), 'c_ext.CFile'),
]

file_editors = []
