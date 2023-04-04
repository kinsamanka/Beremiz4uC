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
import sys

from jinja2 import Environment, FileSystemLoader
from pubsub import pub

from PLCControler import LOCATION_CONFNODE, LOCATION_VAR_INPUT, LOCATION_VAR_OUTPUT
import util.paths as paths


class Modbus():
    PlugType = "Modbus"
    CTNMaxCount = 1

    def __init__(self):
        if self.CTNName()[-2:] == '_0':
            self.FindNewName(self.CTNName()[:-2])

    def GetCurrentNodeName(self):
        return self.CTNName()

    def CTNGenerate_C(self, buildpath, locations):
        return [], '', False


class IO():
    PlugType = "IO"
    CTNMaxCount = 1

    def __init__(self):
        if self.CTNName()[-2:] == '_0':
            self.FindNewName(self.CTNName()[:-2])

    def GetCurrentNodeName(self):
        return self.CTNName()

    def CTNGenerate_C(self, buildpath, locations):
        if self.CTNParent.skip:
            return [], '', False

        # remove location duplicates
        loc = [dict(t) for t in {tuple(d.items()) for d in locations}]

        iomap = {('I', 'W'): 'ain', ('Q', 'W'): 'aout',
                 ('I', 'X'): 'din', ('Q', 'X'): 'dout'}
        ain, aout, din, dout = {}, {}, {}, {}

        for l in loc:
            msg = (f"{l['NAME'].replace('__', '%').replace('_', '.')} "
                   f"is not a valid IO location for {self.CTNName()}\n")

            if l['SIZE'] not in ('X', 'W'):
                self.CTNParent.generate_exception('LocationError', msg)

            x = iomap[l['DIR'], l['SIZE']]
            src = getattr(self.CTNParent, x)
            idx = l['LOC'][2]

            if (idx + 1) > len(src):
                self.CTNParent.generate_exception('LocationError', msg)

            locals()[x].update({l['NAME']: src[idx]})

        hw = {'located_vars': ''}
        for x in ('ain', 'aout', 'din', 'dout'):
            sorted_used = dict(sorted(locals()[x].items()))
            used = list(sorted_used.values())
            unused = [a for a in getattr(self.CTNParent, x) if a not in used]

            hw[f'{x}_size'] = len(used)
            hw[x] = ('{' + ', '.join(used) +
                     (', ' if used else '') +
                     ', '.join(unused) + '}')

            c = ''
            for idx, var in enumerate(sorted_used):
                c += (f"const {'uint8_t' if 'X' in var else 'uint16_t'} "
                      f"*{var} = &_{x}[{idx}];\n")

            hw['located_vars'] += c

        base_folder = paths.AbsParentDir(__file__)
        loader = FileSystemLoader(
            os.path.join(base_folder, 'platformio', 'templates'))
        template = Environment(loader=loader).get_template('hw.cpp.j2')

        cfile = os.path.join(buildpath, 'hw.cpp')
        with open(cfile, 'w') as f:
            f.write(template.render(hw=hw))

        return [(cfile, '')], '', False

    def GetVariableLocationTree(self):
        cur_loc = ".".join([str(x) for x in self.GetCurrentLocation()])
        entries, ain, aout, din, dout = [], [], [], [], []

        prefix = ('IW', 'QW', 'IX', 'QX')
        labels = ('AD', 'DA', 'X', 'Y')
        names = ('Analog Input', 'Analog Output',
                 'Digital Input', 'Digital Output')
        items = ('ain', 'aout', 'din', 'dout')

        for idx, item in enumerate(items):
            for loc, name in enumerate(getattr(self.CTNParent, item)):
                label = f'{labels[idx]}{loc // 8}{loc % 8}'
                if 'I' in prefix[idx]:
                    typ = LOCATION_VAR_INPUT
                else:
                    typ = LOCATION_VAR_OUTPUT
                locals()[item].append({
                    'name': f'{label} (pin {name})',
                    'size': 1 if 'X' in prefix[idx] else 16,
                    'IEC_type': 'BOOL' if 'X' in prefix[idx] else 'WORD',
                    'var_name': f'{label}',
                    'location': f'%{prefix[idx]}{cur_loc}.{loc}',
                    'type': typ,
                    'children': []})

            entries.append({
                'name': names[idx],
                'type': LOCATION_CONFNODE,
                'children': locals()[item]})

        return {'name': self.BaseParams.getName(),
                'type': LOCATION_CONFNODE,
                'location': f'{cur_loc}.x',
                'children': entries}


class Root():
    CTNChildrenTypes = [('IO', IO, 'IO Support'),
                        ('Modbus', Modbus, 'Modbus Support')]
    CTNMaxCount = 1

    def __init__(self):
        self.ain, self.aout, self.din, self.dout = [], [], [], []
        self.skip = False

        target = self.GetCTRoot().BeremizRoot.getTargetType()

        name = ''
        if target.getcontent() is not None:
            platform = target.getcontent().getPlatform()
            if 'getBoard' in dir(platform.getcontent()):
                board = platform.getcontent().getBoard()
                if board is not None:
                    name = board.getcontent().getLocalTag()
                    self.FindNewName(name)

        pub.subscribe(
            self.update_name,
            'BeremizRoot.TargetType.Platform.Board')

        if name:
            self.load_config(name)

    def load_config(self, name):
        base_folder = paths.AbsParentDir(__file__)
        cfg = os.path.join(base_folder, 'platformio', 'platformio.ini')
        config = ConfigParser(
            converters={
                'list': lambda x: [
                    i.strip() for i in x.split(',')]})
        config.read(cfg)

        name = name.replace('_', ' ')
        board = ''
        for i in config:
            if 'env:' in i:
                if name in config.get(i, 'board_name', fallback=''):
                    board = config.get(i, 'board_hw', fallback='')
                    break

        if board:
            for a in ['ain', 'aout', 'din', 'dout']:
                v = config.getlist(board, a, fallback=[])
                setattr(self, a, v)

    def GetCurrentNodeName(self):
        return self.CTNName()

    def GetFileName(self):
        return os.path.join(self.CTNPath(), 'embed.ini')

    def OnCTNSave(self, from_project_path=None):
        return self.save_file(self.GetFileName())

    def CTNTestModified(self):
        return self.ChangesToSave

    def CTNGenerate_C(self, buildpath, locations):
        self.skip = False

        children = {}
        for child in self.IECSortedChildren():
            children.update({child.PlugType: child.GetCurrentLocation()})

        bad = []
        for l in locations:
            if l['LOC'][:2] not in children.values():
                bad.append(l['NAME'].replace('__', '%').replace('_', '.'))

        if bad:
            msg = (f"Invalid locations for {self.CTNName()}:\n" +
                   '\n'.join(bad) + '\n')
            self.generate_exception('LocationError', msg)

        target = self.GetCTRoot().BeremizRoot.getTargetType()
        platform = target.getcontent().getPlatform()
        if platform is not None:
            if platform.getcontent().getLocalTag() == 'Embedded':
                return [], '', False

        self.GetCTRoot().logger.write_warning(
            'Native mode, generating dummy locations.\n')
        self.skip = True

        # generate dummy locations

        loc = [dict(t) for t in {tuple(d.items()) for d in locations}]

        c_text = '#include "iec_types.h"\n\n'
        for l in loc:
            c_text += f"static IEC_{l['IEC_TYPE']} var{l['NAME']};\n"
            c_text += f"const IEC_{l['IEC_TYPE']} *{l['NAME']} = &var{l['NAME']};\n"

        cfile = os.path.join(buildpath, 'located.c')
        with open(cfile, 'w') as f:
            f.write(c_text)

        return [(cfile, '')], '', False

    def generate_exception(self, err, msg):
        self.GetCTRoot().logger.write_warning(msg)
        sys.tracebacklimit = 0
        raise Exception(err)

    def update_name(self, e):
        name = e.replace(' ', '_')
        try:
            self.FindNewName(name)
            self.CTNRequestSave()
        except FileNotFoundError:
            pass
        self.load_config(name)

    def save_file(self, filepath):
        return True
