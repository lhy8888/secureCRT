"""Command-line parsing and GUI field population; never accept CLI passwords."""
import argparse
from pathlib import Path

from .authentication import AUTH_METHODS
from .endpoint import parse_destination


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self,message):
        super().error('Invalid parameters. Use --help; authentication secrets are not command-line arguments.')


def argument_parser():
    parser=SafeArgumentParser(description='Harbor Terminal: SSH and serial sessions')
    parser.add_argument('destination',nargs='?',help='[user@]host[:port], [IPv6]:port or ssh://user@host')
    parser.add_argument('--username','-l')
    parser.add_argument('--port','-p',type=int)
    parser.add_argument('--known-hosts',type=Path)
    parser.add_argument('--identity-file','-i',type=Path)
    parser.add_argument('--certificate-file',type=Path,help='OpenSSH public user certificate')
    parser.add_argument('--allow-legacy-ssh',action='store_true',help='Explicitly consent to a saved profile compatibility policy')
    parser.add_argument('--auth-method',choices=tuple(AUTH_METHODS))
    parser.add_argument('--profile',help='Saved session name')
    parser.add_argument('--sessions',type=Path,help='Explicit session database path')
    parser.add_argument('--channels-only',action='store_true',help='SSH without a shell, for SFTP and forwarding')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--run-flow',type=Path,help='Execute an explicit JSON send/wait flow, without a GUI')
    modes.add_argument('--smoke-test-report',type=Path)
    modes.add_argument('--serial-report',type=Path)
    parser.add_argument('--output',type=Path,help='New JSON report for headless flow execution')
    parser.add_argument('--serial-mode',choices=('inventory','loopback','hotplug'),default='inventory')
    parser.add_argument('--serial-port')
    parser.add_argument('--seconds',type=float,default=60,help='Serial diagnostic duration')
    parser.add_argument('--baudrate',type=int)
    parser.add_argument('--loopback-only',action='store_true')
    return parser


def populate_window(window,args):
    if args.destination and args.serial_port:raise ValueError('Choose either an SSH or a serial destination')
    if args.profile:
        if args.profile not in window.profiles:raise ValueError('Unknown session profile')
        window.load_profile(args.profile)
    if args.destination:
        endpoint=parse_destination(args.destination,username=args.username if args.username is not None else window.user.text(),port=args.port if args.port is not None else 22)
        window.mode.setCurrentText('SSH');window.host.setText(endpoint.host);window.port.setText(str(endpoint.port));window.user.setText(endpoint.username)
    elif args.serial_port:
        baud=args.baudrate if args.baudrate is not None else 115200
        if not 50<=baud<=4000000:raise ValueError('Invalid baud rate')
        window.mode.setCurrentText('Serial');window.host.setText(args.serial_port);window.port.setText(str(baud))
    else:
        if args.username:window.user.setText(args.username)
        if args.port is not None:
            if not 1<=args.port<=65535:raise ValueError('Invalid SSH port')
            window.port.setText(str(args.port))
    if args.known_hosts:window.known.setText(str(args.known_hosts))
    if args.identity_file:window.options['private_key']=str(args.identity_file)
    if args.certificate_file:window.options['client_certificate']=str(args.certificate_file)
    if args.auth_method:window.options['auth_method']=args.auth_method
    if args.channels_only:window.options['ssh_mode']='channels'
    return bool(args.destination or args.profile or args.serial_port or args.username or args.port is not None
                or args.known_hosts or args.identity_file or args.certificate_file or args.auth_method or args.channels_only)
