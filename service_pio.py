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


import argparse
import asyncio
from contextlib import suppress
from functools import partial
import hashlib
import logging
import os
from queue import Queue, Empty
import shutil
from struct import pack, unpack
import sys
from tempfile import mkstemp
import threading
from time import time, time_ns
import wx
import wx.adv

import Pyro5
from Pyro5.server import expose, Daemon
from pubsub import pub
from serial import Serial, SerialException

from min import MINTransport, MINConnectionError
from runtime import PlcStatus
import util.paths as paths
from util.ProcessLogger import ProcessLogger

logging.basicConfig(level=logging.INFO)

ROOT = paths.AbsDir(__file__)
TRAY_TOOLTIP = 'PLCOpen Service'
TRAY_ICON = f'{ROOT}/images/brz.png'
TRAY_START_ICON = f'{ROOT}/images/icoplay24.png'
TRAY_STOP_ICON = f'{ROOT}/images/icostop24.png'

KEEP_ALIVE_PERIOD = 1.0
IDLE_COUNT = 10

(MIN_KEEP_ALIVE,
 MIN_PLC_START,
 MIN_PLC_STOP,
 MIN_PLC_RESET,
 MIN_PLC_INIT,
 MIN_PLC_UPLOAD,
 MIN_PLC_TICK,
 MIN_PLC_SET_TRACE,
 MIN_PLC_GET_TRACE,
 MIN_PLC_WAIT_TRACE,
 MIN_PLC_RESET_TRACE) = range(0, 11)

IEC_SIZES = {'BOOL': 1, 'BYTE': 1, 'DATE': 8, 'DINT': 4, 'DT': 8, 'DWORD': 4,
             'INT': 2, 'LINT': 8, 'LREAL': 8, 'LWORD': 8, 'REAL': 4, 'SINT': 1,
             'STRING': 1, 'TIME': 8, 'TOD': 8, 'UDINT': 4, 'UINT': 2,
             'ULINT': 8, 'USINT': 1, 'WORD': 2}

IEC_FORMAT = {
    'BOOL': '?',
    'BYTE': 'b',
    'DATE': 'Q',
    'DINT': 'i',
    'DT': 'Q',
    'DWORD': 'i',
    'INT': 'h',
    'LINT': 'q',
    'LREAL': 'd',
    'LWORD': 'q',
    'REAL': 'f',
    'SINT': 'b',
    'STRING': 's',
    'TIME': 'Q',
    'TOD': 'Q',
    'UDINT': 'I',
    'UINT': 'H',
    'ULINT': 'Q',
    'USINT': 'B',
    'WORD': 'h'}

Pyro5.config.SERPENT_BYTES_REPR = True

[ITEM_PLC_START, ITEM_PLC_STOP, ITEM_EXIT] = range(3)

ITEM_PLC_STATE = {
    PlcStatus.Started: ('Stop PLC', ITEM_PLC_START, TRAY_START_ICON),
    PlcStatus.Stopped: ('Start PLC', ITEM_PLC_STOP, TRAY_STOP_ICON),
}


class PLCOpenTaskBar(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.myapp_frame = frame
        self.set_icon(TRAY_ICON)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, frame.on_left_down)
        self.plcstate = PlcStatus.Empty
        pub.subscribe(self.set_plcstate, 'plc_state')

    def _create_menu_item(self, menu, label, id=None):
        item = wx.MenuItem(menu, -1, label)
        menu.Bind(wx.EVT_MENU, lambda e: self.on_menu(e, id), id=item.GetId())
        menu.Append(item)
        return item

    def CreatePopupMenu(self):
        menu = wx.Menu()
        if self.plcstate in (PlcStatus.Started, PlcStatus.Stopped):
            a, b, _ = ITEM_PLC_STATE[self.plcstate]
            self._create_menu_item(menu, a, id=b)
            menu.AppendSeparator()
        self._create_menu_item(menu, 'Exit', id=ITEM_EXIT)
        return menu

    def set_icon(self, path):
        icon = wx.Icon(wx.Bitmap(path))
        self.SetIcon(icon, TRAY_TOOLTIP)

    def on_menu(self, e, i):
        if i in (ITEM_PLC_START, ITEM_PLC_STOP):
            pub.sendMessage('set plc', state=(i == ITEM_PLC_STOP))

        if i == ITEM_EXIT:
            self.myapp_frame.Close()

    def set_plcstate(self, state, tick):
        self.plcstate = state
        if state in (PlcStatus.Started, PlcStatus.Stopped):
            _, _, i = ITEM_PLC_STATE[state]
            self.set_icon(i)
        else:
            self.set_icon(TRAY_ICON)


class PLCOpenService(wx.Frame):
    def __init__(self):
        super().__init__(None, size=(1, 1))
        panel = wx.Panel(self)
        self.tb = PLCOpenTaskBar(self)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        pub.subscribe(self.on_shutdown, 'shutdown')

    def on_close(self, evt):
        self.tb.RemoveIcon()
        self.tb.Destroy()
        wx.CallAfter(self.Destroy)

    def on_left_down(self, evt):
        self.tb.PopupMenu(self.tb.CreatePopupMenu())

    def on_shutdown(self):
        wx.CallAfter(self.Destroy)


class PLCObject():
    def __init__(self, wdir, queue):
        self.plcstate = PlcStatus.Empty
        self.debug_token = 0
        self.event = threading.Event()
        self.starting = False
        self.queue = queue
        self.log = [[], [], [], []]
        self.wdir = wdir
        self.blobs = {}

        if os.path.exists(self.wdir):
            shutil.rmtree(self.wdir)
        os.mkdir(self.wdir)

        pub.subscribe(self.set_plcstate, 'plc_state')
        pub.subscribe(self.log_msg, 'log_msg')

    @expose
    def GetLogMessage(self, level, msgid):
        return self.log[level][msgid]

    @expose
    def GetPLCID(self):
        return None

    @expose
    def GetPLCstatus(self):
        l = []
        for n in self.log:
            l.append(len(n))

        return (self.plcstate, l)

    @expose
    def MatchMD5(self, MD5):
        return False

    @expose
    def SeedBlob(self, seed):
        blob = (mkstemp(dir=self.wdir) + (hashlib.new('md5'),))
        _, _, _hash = blob

        _hash.update(seed.encode())
        _hash = hashlib.new('md5')
        _hash.update(seed.encode())

        md5 = _hash.digest()
        self.blobs[md5] = blob

        return md5

    @expose
    def AppendChunkToBlob(self, data, blobID):
        blob = self.blobs.pop(blobID, None)

        if blob is None:
            return None

        _fd, _, _hash = blob

        _hash.update(data)
        md5 = _hash.digest()
        os.write(_fd, data)
        self.blobs[md5] = blob

        return md5

    @expose
    def PurgeBlobs(self):
        for i in self.blobs.values():
            os.close(i[0])

        self.blobs = {}

        if os.path.exists(self.wdir):
            shutil.rmtree(self.wdir)
        os.mkdir(self.wdir)

    def BlobAsFile(self, blobID, newpath):
        blob = self.blobs.pop(blobID, None)
        if blob:
            fd, path, _ = blob
            fobj = os.fdopen(fd)
            fobj.flush()
            os.fsync(fd)
            fobj.close()
            shutil.move(path, newpath)
            return True

        return False

    @expose
    def GetTraceVariables(self, DebugToken):
        if DebugToken is not None and DebugToken == self.debug_token:
            t = []
            with suppress(Empty):
                while not self.queue.empty():
                    t.append(self.queue.get(block=False))

            return self.plcstate, t

        return PlcStatus.Broken, []

    @expose
    def SetTraceVariablesList(self, idxs):
        pub.sendMessage(
            'run async cmd',
            e={'cmd': 'set_trace', 'args': [idxs]})

        self.debug_token += 1

        if idxs:
            return self.debug_token

        return 4

    @expose
    def NewPLC(self, md5sum, plc_object, extrafiles):
        if self.plcstate not in [
                PlcStatus.Stopped,
                PlcStatus.Empty,
                PlcStatus.Broken]:
            return False

        e = ''
        files = []
        for fn, md5 in extrafiles:
            if 'env.' in fn:
                e = fn.split('.')[1]
            else:
                files.append((fn, md5))

        if not e:
            stdout_write("PLCOpen: Missing PlatformIO Environment!")
            return False

        p = os.path.join(self.wdir, 'pio', e)

        if os.path.exists(p):
            shutil.rmtree(p)
        os.makedirs(p, exist_ok=True)

        fn = os.path.join(p, 'firmware.bin')
        if not self.BlobAsFile(plc_object, fn):
            stdout_write(f"PLCOpen: error creating {fn}!")
            return False

        for fn, md5 in files:
            if not self.BlobAsFile(md5, os.path.join(p, fn)):
                stdout_write(f"PLCOpen: error creating {fn}!")
                return False

        env = {
            'BUILD_DIR': self.wdir,
            'PLATFORMIO_DEFAULT_ENVS': e,
        }
        command = ['pio', 'run', '-t', 'nobuild', '-t', 'upload',
                   '--disable-auto-clean']
        cwd = os.path.join(paths.AbsDir(__file__), "platformio")

        status, _res, _err = ProcessLogger(
            None, command, cwd=cwd, env={**os.environ, **env}).spin()

        if status:
            self.plcstate = PlcStatus.Broken
            stdout_write(_res)
            stdout_write(_err)
            stdout_write('Problem uploading firmware to PLC')
            return False

        self.plcstate = PlcStatus.Stopped
        return self.plcstate == PlcStatus.Stopped

    @expose
    def StartPLC(self, *args, **kwargs):
        self.event.clear()
        self.log = [[], [], [], []]

        pub.sendMessage('run async cmd',
                        e={'cmd': 'run_plc',
                           'args': [True]})
        self.starting = True

        self.event.wait()

    @expose
    def StopPLC(self, *args, **kwargs):
        if self.plcstate == PlcStatus.Started:
            self.event.clear()

            pub.sendMessage('run async cmd',
                            e={'cmd': 'run_plc',
                               'args': [False]})

            self.event.wait()

            stdout_write('PLCObject : PLC stopped\n')
            return True

        return False

    def log_msg(self, level, msg, tick):
        t = time_ns()
        s = t // 1000000000
        ns = t % 1000000000

        self.log[level].append((msg, tick, s, ns))

    def set_plcstate(self, state, tick):
        self.plcstate = state

        if state == PlcStatus.Stopped:
            self.log_msg(3, 'PLC stopped', tick)

        if self.starting:
            self.starting = False
            if self.plcstate == PlcStatus.Started:
                stdout_write('PLCObject : PLC started\n')
                self.log_msg(3, 'PLC started', tick)
            else:
                stdout_write('PLCObject : Problem starting PLC\n')
                self.log_msg(0, 'Problem starting PLC', tick)

        self.event.set()


def stdout_write(msg):
    sys.stdout.write(msg)
    sys.stdout.flush()


class PyroDaemon(threading.Thread):
    def __init__(self, host, port, wdir, event, queue):
        super().__init__()
        self.event = event
        self.uri = None
        self.plcobj = None
        self.host = host
        self.port = port
        self.wdir = wdir
        self.pyro_daemon = None
        self.queue = queue

        pub.subscribe(self.set_plc, 'set plc')

    def run(self):
        self.pyro_daemon = Daemon(host=self.host, port=self.port)
        self.plcobj = PLCObject(self.wdir, self.queue)
        self.uri = self.pyro_daemon.register(self.plcobj, 'PLCObject')
        self.event.set()

        stdout_write(f'Pyro port : {str(self.uri).split(":")[-1]}\n'
                     f'Current working directory : {self.wdir}\n')

        self.pyro_daemon.requestLoop()
        stdout_write('Pyro: thread terminated.\n')

    def shutdown(self):
        stdout_write('Pyro: shutting down ...\n')
        self.pyro_daemon.shutdown()

    def set_plc(self, state):
        if state:
            self.plcobj.StartPLC()
        else:
            self.plcobj.StopPLC()


async def event_wait(evt, timeout, clear=False):
    '''
    Await for event with timeout

    Set timeout to None to wait indefinitely.
    Set clear to True to automatically reset the event.
    '''
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(evt.wait(), timeout)

    if clear and evt.is_set():
        evt.clear()
        return True

    return evt.is_set()


class MINPLCObject(MINTransport):
    """
    """

    def __init__(self, serial, queue, loglevel=logging.ERROR):
        self.serial = serial
        super().__init__(loglevel=loglevel)

        self._abort = False
        self._run = True
        self._ready = False
        self._busy = False
        self.plc_state = PlcStatus.Empty
        self.trace_ids = []
        self.trace_id = 0
        self.trace_list = []
        self.trace = {}
        self.trace_tick = 0
        self.loop = None
        self.alive = None
        self.trace_ready = None
        self.queue = queue

        pub.subscribe(self.do_cmd, 'run async cmd')

    def do_cmd(self, e):
        a = e['args']

        if e['cmd'] == 'run_plc':
            if self._ready:
                asyncio.run_coroutine_threadsafe(self.run_plc(*a), self.loop)

        elif e['cmd'] == 'set_trace':
            if self._ready:
                asyncio.run_coroutine_threadsafe(self.set_trace(*a), self.loop)

    def _now_ms(self):
        return int(time() * 1000.0)

    def _serial_write(self, data):
        try:
            self.serial.write(data)
        except (OSError, SerialException):
            logging.error("Error writing to serial port")
            self.serial.close()
            self._abort = True

    def _serial_read_all(self):
        try:
            return self.serial.read_all()
        except (OSError, SerialException):
            logging.error("Error reading from serial port")
            self.serial.close()
            self._abort = True
            return b''

    def _serial_close(self):
        logging.debug("Closing serial port")
        self.serial.close()

    def shutdown(self):
        self._run = False

    async def set_trace(self, idxs):
        self.trace_ids = []
        self.trace = {}
        self.trace_list = []        # clear previous traces

        if not idxs:
            self.send_cmd(MIN_PLC_RESET_TRACE, b'')
        else:
            for ids, t, v in idxs:
                self.trace_ids.append(ids)
                # init trace
                self.trace.update({ids: bytes(IEC_SIZES[t])})

                val = v
                if v is None:
                    if IEC_FORMAT[t] != 's':
                        val = 0
                    else:
                        val = b''

                p = (pack('I', ids)
                     + pack('I', IEC_SIZES[t])
                     + pack('?', v is not None)
                     + pack(IEC_FORMAT[t], val))

                self.send_cmd(MIN_PLC_SET_TRACE, p)

    async def run_plc(self, state):
        if state:
            self.send_cmd(MIN_PLC_INIT, b'')
            self.send_cmd(MIN_PLC_START, b'')
        else:
            self.send_cmd(MIN_PLC_STOP, b'')

    async def task_poll(self):
        while not self._abort and self._run:
            frames = self.poll()
            if frames:
                self.alive.set()

            for frame in frames:
                if frame.min_id == MIN_PLC_START:
                    self.plc_state = PlcStatus.Started
                    asyncio.create_task(
                        self.send_message(
                            'plc_state',
                            state=PlcStatus.Started,
                            tick=self.trace_tick))

                elif frame.min_id == MIN_PLC_STOP:
                    self.plc_state = PlcStatus.Stopped
                    asyncio.create_task(
                        self.send_message(
                            'plc_state',
                            state=PlcStatus.Stopped,
                            tick=self.trace_tick))

                elif frame.min_id == MIN_PLC_TICK:
                    self.trace_tick = unpack('I', frame.payload)[0]

                elif frame.min_id == MIN_PLC_GET_TRACE:
                    self.trace.update({self.trace_id: frame.payload})
                    self.trace_ready.set()

            await asyncio.sleep(0.01)

        return not self._abort

    async def task_keepalive(self):
        # reset PLC on connect
        await event_wait(self.alive, None)
        if not self.send_cmd(MIN_PLC_RESET, b''):
            return False

        asyncio.create_task(
            self.send_message(
                'plc_state',
                state=PlcStatus.Empty,
                tick=self.trace_tick))

        idle_count = 0
        while not self._abort and self._run:

            if await event_wait(self.alive, KEEP_ALIVE_PERIOD, clear=True):

                self._ready = True
                idle_count = 0

            else:
                idle_count += 1
                if idle_count > IDLE_COUNT:
                    idle_count = IDLE_COUNT
                    self._ready = False

                if not self._busy:
                    if not self.send_cmd(MIN_KEEP_ALIVE, b''):
                        return False

            await asyncio.sleep(0.01)

        return not self._abort

    async def send_message(self, arg, **kwargs):
        await self.loop.run_in_executor(None, partial(pub.sendMessage,
                                                      arg, **kwargs))

    async def send_trace(self, trace):
        await self.loop.run_in_executor(None, partial(self.queue.put_nowait,
                                                      trace))

    def send_cmd(self, cmd, arg):
        try:
            self.queue_frame(cmd, arg)
            return True

        except MINConnectionError as e:
            logging.error('%s', e)
            self._abort = True
            return False

    async def task_main(self):
        while True:
            self._busy = False
            overflow = 0

            while self.plc_state == PlcStatus.Started and self.trace_ids:

                self._busy = True

                self.trace_id = self.trace_ids[0]

                a = pack('H', self.trace_id)
                if not self.send_cmd(MIN_PLC_WAIT_TRACE, a):
                    return False

                await event_wait(self.trace_ready, None, clear=True)

                tick = self.trace_tick

                for self.trace_id in self.trace_ids[1:]:

                    a = pack('H', self.trace_id)
                    if not self.send_cmd(MIN_PLC_GET_TRACE, a):
                        return False

                    await event_wait(self.trace_ready, None, clear=True)

                if tick != self.trace_tick and overflow < 4:
                    overflow += 1
                    if overflow == 3:
                        overflow = 4
                        n = self.trace_tick - tick
                        s = 'tick' if n < 2 else 'ticks'
                        stdout_write(
                            f'Debug Trace period too slow by {n} {s}.\n'
                            '   To resolve this issue:\n'
                            '      Reduce the number of trace variables\n'
                            '      or increase the PLC cycle time.\n')
                        asyncio.create_task(
                            self.send_message(
                                'log_msg',
                                level=1,
                                msg='Debug Trace Period too slow',
                                tick=0))

                v = b''.join(self.trace.values())
                asyncio.create_task(self.send_trace((tick, v)))

            await asyncio.sleep(0.01)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.alive = asyncio.Event()
        self.trace_ready = asyncio.Event()

        main = asyncio.create_task(self.task_main())

        res = await asyncio.gather(self.task_poll(),
                                   self.task_keepalive())

        main.cancel()
        self.send_frame(MIN_PLC_RESET, b'')

        return res


class MainWorker(threading.Thread):
    def __init__(self, host, tcp_port, wdir, port, baud=115200):
        super().__init__()

        self.queue = Queue()
        self.event = threading.Event()
        self.pyro_daemon = PyroDaemon(host, tcp_port, wdir, self.event,
                                      self.queue)
        self.pyro_daemon.daemon = True
        self._shutdown = False
        self.daemon = True
        try:
            self.serial = Serial(port=port, baudrate=baud, timeout=0.1)
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
        except SerialException as e:
            logging.error('Error opening port %s', port)
            raise e
        self.async_min = MINPLCObject(self.serial, self.queue)

    def run(self):
        logging.info('MainThread: started.\n')
        self.start_pyro()

        res = asyncio.run(self.async_min.run())

        if False in res:
            pub.sendMessage('shutdown')

        logging.info('MainThread: stopped.\n')

    def start_pyro(self):
        self.pyro_daemon.start()
        self.event.wait()

    def shutdown(self):
        self.pyro_daemon.shutdown()
        self.pyro_daemon.join()
        self.async_min.shutdown()
        self.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', type=int, default=0, help='listen on port')
    parser.add_argument('-i', help='listen on address')
    parser.add_argument('-x', type=int, default=1,
                        choices=[0, 1],
                        help='enable GUI (0=disabled)')
    parser.add_argument('tmpdir',
                        help='temporary location for PLC files')
    parser.add_argument('port',
                        help='serial port name')
    args = parser.parse_args()

    if args.x:
        app = wx.App()
        PLCOpenService()

    try:
        pyro_thread = MainWorker(args.i, args.p, args.tmpdir, args.port)
        pyro_thread.daemon = True
        pyro_thread.start()
        pyro_thread.event.wait()

        if args.x:
            app.MainLoop()
        else:
            try:
                pyro_thread.join()
            except (KeyboardInterrupt, SystemExit):
                stdout_write('\nExiting...\n')

        pyro_thread.shutdown()

    except SerialException:
        pass
