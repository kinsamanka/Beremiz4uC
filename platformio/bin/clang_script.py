from os import environ
import platform

win = platform.system() == "Windows"

Import("env")

env.Append(LINKFLAGS=["-shared"])

if win:
    env.Append(LINKFLAGS=["-lwinmm"])
    env.Append(CCFLAGS=["-D__WIN32"])
else:
    env.Append(LINKFLAGS=["-lrt"])
    env.Append(CCFLAGS=["-fPIC"])

if environ.get('PROGNAME'):
    env.Replace(PROGNAME=environ.get('PROGNAME'))

