#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import os
import sys
import struct
import pwd
import signal
from gettext import gettext as _

from PyQt5.QtCore import Qt, QSocketNotifier, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox

from .config import load_config, validate_font
from .constants import appname, str_version, config_dir
from .boss import Boss
from .utils import fork_child


class MainWindow(QMainWindow):

    report_error = pyqtSignal(object)

    def __init__(self, opts):
        QMainWindow.__init__(self)
        self.setWindowTitle(appname)
        sys.excepthook = self.on_unhandled_error
        self.report_error.connect(self.show_error, type=Qt.QueuedConnection)
        self.handle_unix_signals()
        self.boss = Boss(opts, self)
        self.setCentralWidget(self.boss.term)

    def on_unhandled_error(self, etype, value, tb):
        if etype == KeyboardInterrupt:
            return
        sys.__excepthook__(etype, value, tb)
        try:
            msg = str(value)
        except Exception:
            msg = repr(value)
        self.report_error.emit(msg)

    def show_error(self, msg):
        QMessageBox.critical(self, _('Unhandled exception'), msg)

    def handle_unix_signals(self):
        read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda x, y: None)
            signal.siginterrupt(sig, False)
        signal.set_wakeup_fd(write_fd)
        self.signal_notifier = QSocketNotifier(read_fd, QSocketNotifier.Read, self)
        self.signal_notifier.setEnabled(True)
        self.signal_notifier.activated.connect(self.signal_received, type=Qt.QueuedConnection)

    def signal_received(self, read_fd):
        try:
            data = os.read(read_fd, 1024)
        except BlockingIOError:
            return
        if data:
            signals = struct.unpack('%uB' % len(data), data)
            if signal.SIGINT in signals or signal.SIGTERM in signals:
                self.shutdown()

    def child_process_died(self):
        self.shutdown()

    def shutdown(self):
        self.close()
        self.boss.shutdown()


def option_parser():
    parser = argparse.ArgumentParser(prog=appname, description=_('The {} terminal emulator').format(appname))
    a = parser.add_argument
    a('--name', default=appname, help=_('Set the name part of the WM_CLASS property'))
    a('--class', default=appname, dest='cls', help=_('Set the class part of the WM_CLASS property'))
    a('--config', default=os.path.join(config_dir, 'kitty.conf'), help=_('Specify a path to the config file to use'))
    a('--cmd', '-c', default=None, help=_('Run python code in the kitty context'))
    a('--exec', '-e', dest='child', default=pwd.getpwuid(os.geteuid()).pw_shell or '/bin/sh', help=_('Run the specified command instead of the shell'))
    a('-d', '--directory', default='.', help=_('Change to the specified directory when launching'))
    a('--version', action='version', version='{} {} by Kovid Goyal'.format(appname, '.'.join(str_version)))
    return parser


def main():
    args = option_parser().parse_args()
    if args.cmd:
        exec(args.cmd)
        return
    # Ensure the child process gets no environment from Qt
    opts = load_config(args.config)
    fork_child(args.child, args.directory, opts)

    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
    app = QApplication([appname])
    app.setOrganizationName(args.cls)
    app.setApplicationName(args.name)
    try:
        validate_font(opts)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    w = MainWindow(opts)
    w.show()
    try:
        app.exec_()
    except KeyboardInterrupt:
        pass
