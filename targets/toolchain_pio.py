#
# This file is part of Beremiz for uC
#
# Copyright (C) 2023 GP Orcullo
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
# along with this program; If not, see <http://www.gnu.org/licenses/>.
#

from configparser import ConfigParser
import os
import shutil
from util.ProcessLogger import ProcessLogger
import util.paths as paths

base_folder = paths.AbsParentDir(__file__)
pio_env = {}


def generate_elements():
    cfg = os.path.join(base_folder, 'platformio', 'platformio.ini')
    cp = ConfigParser()
    cp.read(cfg)

    elements = ''
    for i in cp:
        if 'env:' in i:
            try:
                name = cp[i]['board_name'].replace(" ", "_")
                elements += f'<xsd:element name="{name}"/>'
                pio_env.update({name: i.replace('env:', '')})
            except KeyError:
                pass

    return elements


XSD = f'''
    <xsd:element name="PlatformIO">
      <xsd:complexType>
        <xsd:sequence>
          <xsd:element name="Platform">
            <xsd:complexType>
              <xsd:choice>
                <xsd:element name="Native"/>
                <xsd:element name="Embedded">
                  <xsd:complexType>
                    <xsd:sequence>
                      <xsd:element name="Board">
                        <xsd:complexType>
                          <xsd:choice>
                            {generate_elements()}
                          </xsd:choice>
                        </xsd:complexType>
                      </xsd:element>
                    </xsd:sequence>
                    <xsd:attribute name="Enable_Debug" type="xsd:boolean"/>
                  </xsd:complexType>
                </xsd:element>
              </xsd:choice>
            </xsd:complexType>
          </xsd:element>
        </xsd:sequence>
        <xsd:attribute name="Verbose_Mode" type="xsd:boolean"/>
      </xsd:complexType>
    </xsd:element>
'''


class toolchain_pio():
    def __init__(self, CTRInstance):
        self.CTRInstance = CTRInstance
        self.md5key = None
        self.buildpath = None
        self.SetBuildPath(self.CTRInstance._getBuildPath())
        self.bin = ""
        self.bin_path = ""

    def SetBuildPath(self, buildpath):
        if not os.path.isabs(buildpath):
            buildpath = os.path.join(os.getcwd(), buildpath)

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
        src = []
        for _, files, _ in self.CTRInstance.LocationCFilesAndCFLAGS:
            for cfile, _ in files:
                if os.path.isabs(cfile):
                    src.append(cfile)
                else:
                    src.append(os.path.join(os.getcwd(), cfile))

        verbose = self.CTRInstance.GetTarget().getcontent().getVerbose_Mode()
        target = self.CTRInstance.GetTarget().getcontent().getPlatform()
        platform = target.getcontent().getLocalTag()

        if platform == 'Native':
            self.bin = self.CTRInstance.GetProjectName() + self.extension

            src_filter = '-<*>'
            for s in src:
                src_filter += f' +<{s}>'

            env = {
                'BUILD_DIR': self.buildpath,
                'PLATFORMIO_BUILD_SRC_FILTER': src_filter,
                'PROGNAME': self.bin,
            }
            self.bin_path = os.path.join(
                self.buildpath, 'pio', 'default', self.bin)
        else:
            try:
                board = target.getcontent().getBoard().getcontent().getLocalTag()
            except AttributeError:
                board = ''

            if not board:
                self.CTRInstance.logger.write_error(
                    "Please select an embedded board first.\n")
                return False

            self.bin = "firmware.bin"

            src_filter = '+<*>'
            for s in src:
                if 'plc_' not in s:
                    src_filter += f' +<{s}>'

            env = {
                'BUILD_DIR': self.buildpath,
                'PLATFORMIO_BUILD_SRC_FILTER': src_filter,
                'PLATFORMIO_DEFAULT_ENVS': pio_env[board],
            }
            self.bin_path = os.path.join(
                self.buildpath, 'pio', pio_env[board], self.bin)

            with open(os.path.join(self.buildpath,
                                   'extra_files',
                                   f'env.{pio_env[board]}'), 'w') as f:
                f.write(str(env))

        command = ['pio', 'run']
        if verbose:
            command.append('-v')
        if platform == 'Native':
            command.extend(['-c', 'platformio_clang.ini'])

        cwd = os.path.join(base_folder, "platformio")

        status, _result, _err_result = ProcessLogger(
            self.CTRInstance.logger, command, cwd=cwd,
            env={**os.environ, **env}).spin()

        if status:
            self.md5key = None
            self.CTRInstance.logger.write_error("C compilation failed.\n")
            return False

        if platform == 'Embedded':
            src = self.bin_path.rsplit('.', 1)[0] + '.elf'
            shutil.copy(src, os.path.join(self.buildpath, 'extra_files'))

        sha1_file = os.path.join(self.buildpath, 'pio', 'project.checksum')
        try:
            self.md5key = open(sha1_file, 'r').read()[:32]
        except IOError:
            self.CTRInstance.logger.write_error("Reading project.checksum "
                                                "failed.\n")
            return False

        f = open(self._GetMD5FileName(), "w")
        f.write(self.md5key)
        f.close()

        return True
