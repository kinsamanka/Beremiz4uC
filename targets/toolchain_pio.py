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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

import os
from util.ProcessLogger import ProcessLogger
import util.paths as paths

XSD = '''
    <xsd:sequence/>
'''

base_folder = paths.AbsParentDir(__file__)


class toolchain_pio():
    def __init__(self, CTRInstance):
        self.CTRInstance = CTRInstance
        self.md5key = None
        self.buildpath = None
        self.SetBuildPath(self.CTRInstance._getBuildPath())

    def SetBuildPath(self, buildpath):
        if self.buildpath != buildpath:
            self.buildpath = buildpath
            self.md5key = None

    def GetBinaryPath(self):
        return self.bin_path

    def _GetMD5FileName(self):
        return os.path.join(self.buildpath, "lastbuildPLC.md5")

    def ResetBinaryMD5(self):
        self.md5key = None
        try:
            os.remove(self._GetMD5FileName())
        except Exception:
            pass

    def GetBinaryMD5(self):
        if self.md5key is not None:
            return self.md5key
        else:
            try:
                return open(self._GetMD5FileName(), "r").read()
            except IOError:
                return None

    def build(self):
        self.bin = self.CTRInstance.GetProjectName() + self.extension
        self.bin_path = os.path.join(
            self.buildpath, 'pio', 'default', self.bin)

        env = {
            'SRC_DIR': self.buildpath,
            'PROGNAME': self.bin,
        }
        command = ['pio', 'run', '-c', 'platformio_clang.ini']
        cwd = os.path.join(base_folder, "platformio")

        status, _result, _err_result = ProcessLogger(
            self.CTRInstance.logger, command, cwd=cwd,
            env={**os.environ, **env}).spin()

        if status:
            self.md5key = None
            self.CTRInstance.logger.write_error(_("C compilation failed.\n"))
            return False

        sha1_file = os.path.join(self.buildpath, 'pio', 'project.checksum')
        try:
            self.md5key = open(sha1_file, 'r').read()[:32]
        except IOError:
            self.CTRInstance.logger.write_error(_("Reading project.checksum"
                                                  " failed.\n"))
            return False

        f = open(self._GetMD5FileName(), "w")
        f.write(self.md5key)
        f.close()

        return True
