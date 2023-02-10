#
# This file is part of Beremiz
#
# Copyright (C) 2023: GP Orcullo
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

import sys
from ..toolchain_pio import toolchain_pio

class PlatformIO_target(toolchain_pio):
    dlopen_prefix = "./"
    if sys.platform.startswith('linux'):
        extension = ".so"
    elif sys.platform.startswith('darwin'):
        extension = ".dynlib"
    elif sys.platform.startswith('win'):
        dlopen_prefix = ""
        extension = ".dll"

