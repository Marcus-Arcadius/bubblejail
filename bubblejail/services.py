# SPDX-License-Identifier: GPL-3.0-or-later

# Copyright 2019-2022 igo95862

# This file is part of bubblejail.
# bubblejail is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# bubblejail is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with bubblejail.  If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations

from os import environ, readlink
from pathlib import Path
from random import choices
from string import ascii_letters, hexdigits
from typing import (
    Dict,
    FrozenSet,
    Generator,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)

from xdg import BaseDirectory

from .bwrap_config import (
    Bind,
    BwrapConfigBase,
    DbusCommon,
    DbusSessionOwn,
    DbusSessionTalkTo,
    DevBind,
    DevBindTry,
    DirCreate,
    EnvrimentalVar,
    FileTransfer,
    LaunchArguments,
    ReadOnlyBind,
    ReadOnlyBindTry,
    SeccompDirective,
    SeccompSyscallErrno,
    ShareNetwork,
    Symlink,
)

# region Service Typing


class ServiceWantsSend:
    ...


class ServiceWantsHomeBind(ServiceWantsSend):
    ...


ServiceIterTypes = Union[BwrapConfigBase, FileTransfer,
                         SeccompDirective,
                         LaunchArguments, ServiceWantsSend, DbusCommon]

ServiceSendType = Union[Path]

ServiceGeneratorType = Generator[ServiceIterTypes, ServiceSendType, None]

# endregion Service Typing

# region Service Options

ServiceOptionTypes = Union[str, List[str], bool]


class ServiceOption:
    def __init__(self, name: str, description: str, pretty_name: str):
        self.name = name
        self.description = description
        self.pretty_name = pretty_name

    def get_value(self) -> ServiceOptionTypes:
        raise NotImplementedError('Default option value getter called')

    def get_gui_value(self) -> ServiceOptionTypes:
        return self.get_value()

    def set_value(self, new_value: ServiceOptionTypes) -> None:
        raise NotImplementedError('Default option value setter called')


class OptionStrList(ServiceOption):
    def __init__(self, str_list: List[str],
                 description: str, name: str,
                 pretty_name: str):
        super().__init__(
            description=description,
            name=name,
            pretty_name=pretty_name,
        )
        self.str_list = str_list

    def get_value(self) -> List[str]:
        return self.str_list

    def set_value(self, new_value: ServiceOptionTypes) -> None:
        if isinstance(new_value, list):
            self.str_list = new_value
        else:
            raise TypeError(f"Option StrList got {type(new_value)}")


class OptionSpaceSeparatedStr(OptionStrList):
    def __init__(self, str_or_list_str: Union[str, List[str]],
                 description: str, name: str,
                 pretty_name: str):

        if isinstance(str_or_list_str, str):
            str_list = str_or_list_str.split()
        elif isinstance(str_or_list_str, list):
            str_list = str_or_list_str
        else:
            raise TypeError(("Init of space separated got "
                             f"{repr(str_or_list_str)}"))

        super().__init__(
            description=description,
            name=name,
            pretty_name=pretty_name,
            str_list=str_list,
        )

    def get_gui_value(self) -> str:
        return '\t'.join(self.str_list)

    def set_value(self, new_value: ServiceOptionTypes) -> None:
        if isinstance(new_value, str):
            str_list = new_value.split()
        elif isinstance(new_value, list):
            str_list = new_value
        else:
            raise TypeError(f"Option space separated got {type(new_value)}")

        super().set_value(str_list)


class OptionStr(ServiceOption):
    def __init__(self, string: str,
                 description: str, name: str,
                 pretty_name: str):
        super().__init__(
            description=description,
            name=name,
            pretty_name=pretty_name,
        )
        self.string = string

    def get_value(self) -> str:
        return self.string

    def set_value(self, new_value: ServiceOptionTypes) -> None:
        if isinstance(new_value, str):
            self.string = new_value
        else:
            raise TypeError(f"Option Str got {type(new_value)}")


class OptionBool(ServiceOption):
    def __init__(self, boolean: bool,
                 description: str, name: str,
                 pretty_name: str):
        super().__init__(
            description=description,
            name=name,
            pretty_name=pretty_name,
        )
        self.boolean = boolean

    def get_value(self) -> bool:
        return self.boolean

    def set_value(self, new_value: ServiceOptionTypes) -> None:
        if isinstance(new_value, bool):
            self.boolean = new_value
        else:
            raise TypeError(f"Option Bool got {type(new_value)}")

# endregion Service Options


# region HelperFunctions
XDG_DESKTOP_VARS: FrozenSet[str] = frozenset({
    'XDG_CURRENT_DESKTOP', 'DESKTOP_SESSION',
    'XDG_SESSION_TYPE', 'XDG_SESSION_DESKTOP'})


def generate_path_var() -> str:
    """Filters PATH variable to locations with /usr prefix"""

    # Split by semicolon
    paths = environ['PATH'].split(':')
    # Filter by /usr and /tmp then join by semicolon
    return ':'.join(filter(
        lambda s: s.startswith('/usr/')
        or s == '/bin'
        or s == '/sbin',
        paths))


def generate_passwd() -> FileTransfer:
    passwd = '\n'.join((
        'root:x:0:0::/root:/bin/nologin',
        'user:x:1000:1000::/home/user:/bin/nologin',
        'nobody:x:65534:65534:Nobody:/:/usr/bin/nologin',
    ))

    return FileTransfer(passwd.encode(), '/etc/passwd')


def generate_group() -> FileTransfer:
    group = '\n'.join((
        'root:x:0:root',
        'user:x:1000:user',
        'nobody:x:65534:',
    ))

    return FileTransfer(group.encode(), '/etc/group')


def generate_nssswitch() -> FileTransfer:
    """
    Based on what Arch Linux packages by default

    Disables some systemd stuff that we don't need in sandbox
    """

    nsswitch = '''passwd: files
group: files
shadow: files

publickey: files

hosts: files myhostname dns
networks: files

protocols: files
services: files
ethers: files
rpc: files

netgroup: files'''
    return FileTransfer(nsswitch.encode(), '/etc/nsswitch.conf')


def random_hostname() -> str:
    random_hostname = choices(
        population=ascii_letters,
        k=10,
    )
    return ''.join(random_hostname)


def generate_hosts() -> Tuple[FileTransfer, FileTransfer]:
    hostname = random_hostname()
    hosts = '\n'.join((
        '127.0.0.1               localhost',
        '::1                     localhost',
        f'127.0.1.1               {hostname}.localdomain {hostname}',
    ))
    return (FileTransfer(hostname.encode(), '/etc/hostname'),
            FileTransfer(hosts.encode(), '/etc/hosts'))


def generate_toolkits() -> Generator[ServiceIterTypes, None, None]:
    config_home_path = Path(BaseDirectory.xdg_config_home)
    kde_globals_conf = config_home_path / 'kdeglobals'
    if kde_globals_conf.exists():
        yield ReadOnlyBind(
            str(kde_globals_conf),
            '/home/user/.config/kdeglobals')


def generate_machine_id_bytes() -> bytes:
    random_hex_string = choices(
        population=hexdigits.lower(),
        k=32,
    )

    return b''.join((x.encode() for x in random_hex_string))

# endregion HelperFunctions


# HACK: makes typing easier rather than None
EMPTY_LIST: List[str] = []


class BubblejailService:

    def __init__(self) -> None:
        self.option_list: List[ServiceOption] = []
        self.enabled: bool = False

    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        if False:
            yield None

    def add_option(self, option: ServiceOption) -> None:
        self.option_list.append(option)

    def iter_options(self) -> Iterator[ServiceOption]:
        return iter(self.option_list)

    def set_options(self, options_map: Dict[str, ServiceOptionTypes]) -> None:
        for option in self.iter_options():
            option_name = option.name
            try:
                option_new_value = options_map.pop(option_name)
            except KeyError:
                continue
            option.set_value(option_new_value)

        if options_map:
            raise TypeError(f"Unknown options {options_map}")

    def to_dict(self) -> Dict[str, ServiceOptionTypes]:
        new_dict = {}

        for option in self.iter_options():
            new_dict[option.name] = option.get_value()

        return new_dict

    name: str
    pretty_name: str
    description: str


class BubblejailDefaults(BubblejailService):

    def __iter__(self) -> ServiceGeneratorType:
        # Defaults can't be disabled

        # Distro packaged libraries and binaries
        yield ReadOnlyBind('/usr')
        yield ReadOnlyBind('/opt')
        # Recreate symlinks in / or mount them read-only if its not a symlink.
        # Should be portable between distros.
        for root_path in Path('/').iterdir():
            if (
                    root_path.name.startswith('lib')  # /lib /lib64 /lib32
                    or root_path.name == 'bin'
                    or root_path.name == 'sbin'):
                if root_path.is_symlink():
                    yield Symlink(str(readlink(root_path)), str(root_path))
                else:
                    yield ReadOnlyBind(str(root_path))

        # yield ReadOnlyBind('/etc/resolv.conf'),
        yield ReadOnlyBind('/etc/login.defs')  # ???: is this file needed
        # ldconfig: linker cache
        # particularly needed for steam runtime to work
        yield ReadOnlyBindTry('/etc/ld.so.cache')
        yield ReadOnlyBindTry('/etc/ld.so.conf')
        yield ReadOnlyBindTry('/etc/ld.so.conf.d')

        # Temporary directories
        yield DirCreate('/tmp')
        yield DirCreate('/var')

        yield DirCreate('/run/user/1000', permissions=0o700)
        yield DirCreate('/usr/local')  # Used for overwrites

        # Bind pseudo home
        home_path = yield ServiceWantsHomeBind()
        yield Bind(str(home_path), '/home/user')

        # Set environmental variables
        yield EnvrimentalVar('USER', 'user')
        yield EnvrimentalVar('USERNAME', 'user')
        yield EnvrimentalVar('HOME', '/home/user')
        yield EnvrimentalVar('PATH', generate_path_var())
        yield EnvrimentalVar('XDG_RUNTIME_DIR', '/run/user/1000')

        yield EnvrimentalVar('LANG')

        yield generate_passwd()
        yield generate_group()
        yield generate_nssswitch()
        yield FileTransfer(b'multi on', '/etc/host.conf')
        yield from generate_hosts()

        yield FileTransfer(generate_machine_id_bytes(), '/etc/machine-id')

        if not environ.get('BUBBLEJAIL_DISABLE_SECCOMP_DEFAULTS'):
            for blocked_syscal in (
                "bdflush", "io_pgetevents",
                "kexec_file_load", "kexec_load",
                "migrate_pages", "move_pages",
                "nfsservctl", "nice", "oldfstat",
                "oldlstat", "oldolduname", "oldstat",
                "olduname", "pciconfig_iobase", "pciconfig_read",
                "pciconfig_write", "sgetmask", "ssetmask", "swapcontext",
                "swapoff", "swapon", "sysfs", "uselib", "userfaultfd",
                "ustat", "vm86", "vm86old", "vmsplice",

                "bpf", "fanotify_init", "lookup_dcookie",
                "perf_event_open", "quotactl", "setdomainname",
                "sethostname", "setns",

                # "chroot",
                # Firefox and Chromium fails if chroot is not available

                "delete_module", "init_module",
                "finit_module", "query_module",

                "acct",

                "iopl", "ioperm",

                "settimeofday", "stime",
                "clock_settime", "clock_settime64"

                "vhangup",

            ):
                yield SeccompSyscallErrno(blocked_syscal, 1)

    def __repr__(self) -> str:
        return "Bubblejail defaults."

    name = 'default'
    pretty_name = 'Default settings'
    description = ('Settings that must be present in any instance')


class CommonSettings(BubblejailService):
    def __init__(
        self,
        executable_name: Union[str, List[str]] = EMPTY_LIST,
        share_local_time: bool = True,
        filter_disk_sync: bool = False,
        dbus_name: str = '',
    ):
        super().__init__()
        self.share_local_time = OptionBool(
            boolean=share_local_time,
            name='share_local_time',
            pretty_name='Share local time',
            description='Instance will know local time instead of UTC',
        )

        self.filter_disk_sync = OptionBool(
            boolean=filter_disk_sync,
            name='filter_disk_sync',
            pretty_name='Filter disk sync',
            description=(
                'Do not allow flushing disk\n'
                'Useful for EA Origin client that tries to flush\n'
                'to disk too often.'),
        )

        self.executable_name = OptionSpaceSeparatedStr(
            str_or_list_str=executable_name,
            name='executable_name',
            pretty_name='Executable arguments',
            description='Space separated arguments',
        )

        self.dbus_name = OptionStr(
            string=dbus_name,
            name='dbus_name',
            description='Name used for dbus ownership',
            pretty_name='Dbus name',
        )

        self.add_option(self.dbus_name)
        self.add_option(self.executable_name)
        self.add_option(self.filter_disk_sync)
        self.add_option(self.share_local_time)

    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        # Executable main arguments
        yield LaunchArguments(self.executable_name.get_value())

        if self.filter_disk_sync.get_value():
            yield SeccompSyscallErrno('sync', 0)
            yield SeccompSyscallErrno('fsync', 0)

        if self.share_local_time.get_value():
            yield ReadOnlyBind('/etc/localtime')

        dbus_name = self.dbus_name.get_value()
        if dbus_name:
            yield DbusSessionOwn(dbus_name)

    name = 'common'
    pretty_name = 'Common Settings'
    description = "Settings that don't fit any particular category"


class X11(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        for x in XDG_DESKTOP_VARS:
            if x in environ:
                yield EnvrimentalVar(x)

        yield EnvrimentalVar('DISPLAY')
        yield Bind(f"/tmp/.X11-unix/X{environ['DISPLAY'][1:]}")
        yield ReadOnlyBind(environ['XAUTHORITY'], '/tmp/.Xauthority')
        yield ReadOnlyBind('/etc/fonts')
        yield EnvrimentalVar('XAUTHORITY', '/tmp/.Xauthority')
        yield from generate_toolkits()

    name = 'x11'
    pretty_name = 'X11 windowing system'
    description = ('Gives access to X11 socket.\n'
                   'This is generally the default Linux windowing system.')


class Wayland(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        try:
            wayland_display_env = environ['WAYLAND_DISPLAY']
        except KeyError:
            print("No wayland display.")

        for x in XDG_DESKTOP_VARS:
            if x in environ:
                yield EnvrimentalVar(x)

        yield EnvrimentalVar('GDK_BACKEND', 'wayland')
        yield EnvrimentalVar('MOZ_DBUS_REMOTE', '1')
        yield EnvrimentalVar('MOZ_ENABLE_WAYLAND', '1')

        yield EnvrimentalVar('WAYLAND_DISPLAY', 'wayland-0')
        original_socket_path = (Path(BaseDirectory.get_runtime_dir())
                                / wayland_display_env)

        new_socket_path = Path('/run/user/1000') / 'wayland-0'
        yield Bind(str(original_socket_path), str(new_socket_path))
        yield from generate_toolkits()

    name = 'wayland'
    pretty_name = 'Wayland windowing system'
    description = (
        'Make sure you are running Wayland session\n'
        'and your application supports Wayland'
    )


class Network(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield ShareNetwork()
        yield ReadOnlyBind('/etc/resolv.conf')
        yield ReadOnlyBind('/etc/ca-certificates')
        yield ReadOnlyBind('/etc/ssl')

    name = 'network'
    pretty_name = 'Network access'
    description = 'Gives access to network.'


class PulseAudio(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield Bind(
            f"{BaseDirectory.get_runtime_dir()}/pulse/native",
            '/run/user/1000/pulse/native'
        )

    name = 'pulse_audio'
    pretty_name = 'Pulse Audio'
    description = 'Default audio system in most distros'


class HomeShare(BubblejailService):
    def __init__(self, home_paths: List[str] = EMPTY_LIST):
        super().__init__()
        self.home_paths = OptionStrList(
            str_list=home_paths,
            name='home_paths',
            pretty_name='List of paths',
            description='Add directory name and path to share',
        )
        self.add_option(self.home_paths)

    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        if self.home_paths is not None:
            for path_relative_to_home in self.home_paths.get_value():
                yield Bind(
                    str(Path.home() / path_relative_to_home),
                    str(Path('/home/user') / path_relative_to_home),
                )

    name = 'home_share'
    pretty_name = 'Home Share'
    description = 'Share directories relative to home'


class DirectRendering(BubblejailService):
    def __init__(self, enable_aco: bool = False):
        super().__init__()
        self.enable_aco = OptionBool(
            boolean=enable_aco,
            name='enable_aco',
            pretty_name='Enable ACO',
            description=(
                'Enables high performance vulkan shader\n'
                'compiler for AMD GPUs. No effect on Nvidia\n'
                'or Intel.'
            ),
        )
        self.add_option(self.enable_aco)

    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        # TODO: Allow to select which DRM devices to pass

        # Bind /dev/dri and /sys/dev/char and /sys/devices
        # Get names of cardX and renderX in /dev/dri
        dev_dri_path = Path('/dev/dri/')
        device_names = set()
        for x in dev_dri_path.iterdir():
            if x.is_char_device():
                device_names.add(x.stem)

        # Resolve links in /sys/dev/char/
        sys_dev_char_path = Path('/sys/dev/char/')
        # For each symlink in /sys/dev/char/ resolve
        # and see if they point to cardX or renderX
        for x in sys_dev_char_path.iterdir():
            x_resolved = x.resolve()
            if x_resolved.name in device_names:
                # Found the dri device
                # Add the /sys/dev/char/ path
                yield Symlink(str(x_resolved), str(x))
                # Add the two times parent (parents[1])
                # Seems like the dri devices are stored as
                # /sys/devices/..pcie_id../drm/dri
                # We want to bind the /sys/devices/..pcie_id../
                yield DevBind(str(x_resolved.parents[1]))

        yield DevBind('/dev/dri')

        if self.enable_aco.get_value():
            yield EnvrimentalVar('RADV_PERFTEST', 'aco')

        # Nvidia specifc binds
        for x in Path('/dev/').iterdir():
            if x.name.startswith('nvidia'):
                yield DevBind(str(x))

    name = 'direct_rendering'
    pretty_name = 'Direct Rendering'
    description = 'Provides access to GPU'


class Systray(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield DbusSessionTalkTo('org.kde.StatusNotifierWatcher')

    name = 'systray'
    pretty_name = 'System tray icons'
    description = (
        'Provides access to Dbus API for creating tray icons\n'
        'This is not the only way to create tray icons but\n'
        'the most common one.'
    )


class Joystick(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        look_for_names: Set[str] = set()

        dev_input_path = Path('/dev/input')
        sys_class_input_path = Path('/sys/class/input')
        js_names: Set[str] = set()
        for input_dev in dev_input_path.iterdir():
            if not input_dev.is_char_device():
                continue
            # If device dooes not have read permission
            # for others it is not a gamepad
            # Only jsX devices have this, we need to find eventX of gamepad
            if (input_dev.stat().st_mode & 0o004) == 0:
                continue

            js_names.add(input_dev.name)

        look_for_names.update(js_names)
        # Find event name of js device
        # Resolve the PCI name. Should be something like this:
        # /sys/devices/.../input/input23/js0
        # Iterate over names in this directory
        # and add eventX names
        for js_name in js_names:
            sys_class_input_js = sys_class_input_path / js_name

            js_reloved = sys_class_input_js.resolve()
            js_input_path = js_reloved.parents[0]
            for input_element in js_input_path.iterdir():
                if input_element.name.startswith('event'):
                    look_for_names.add(input_element.name)

        # Find the *-joystick in /dev/input/by-path/
        for dev_name in look_for_names:
            # Add /dev/input/X device
            yield DevBind(str(dev_input_path / dev_name))

            sys_class_path = sys_class_input_path / dev_name

            yield Symlink(
                str(readlink(sys_class_path)),
                str(sys_class_path)
            )

            pci_path = sys_class_path.resolve()
            yield DevBind(str(pci_path.parents[2]))

    name = 'joystick'
    pretty_name = 'Joysticks and gamepads'
    description = (
        'Windowing systems (x11 and wayland) do not support gamepads.\n'
        'Every game has to read from device files directly.\n'
        'This service provides access to required '
    )


class RootShare(BubblejailService):
    def __init__(self,
                 paths: List[str] = EMPTY_LIST,
                 read_only_paths: List[str] = EMPTY_LIST):
        super().__init__()

        self.paths = OptionStrList(
            str_list=paths,
            name='paths',
            pretty_name='Read/Write paths',
            description='Add directory path to share',
        )

        self.read_only_paths = OptionStrList(
            str_list=read_only_paths,
            name='read_only_paths',
            pretty_name='Read only paths',
            description='Add directory path to share',
        )

        self.add_option(self.read_only_paths)
        self.add_option(self.paths)

    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        for x in self.paths.get_value():
            yield Bind(x)

        for x in self.read_only_paths.get_value():
            yield ReadOnlyBind(x)

    name = 'root_share'
    pretty_name = 'Root share'
    description = (
        'Share directory relative to root /'
    )


class OpenJDK(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield ReadOnlyBind('/etc/java-openjdk')
        yield ReadOnlyBind('/etc/profile.d/jre.csh')
        yield ReadOnlyBind('/etc/profile.d/jre.sh')

    name = 'openjdk'
    pretty_name = 'Java'
    description = (
        'Enable for applications that require Java\n'
        'Example: Minecraft'
    )


class Notifications(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield DbusSessionTalkTo('org.freedesktop.Notifications')

    name = 'notify'
    pretty_name = 'Notifications'
    description = 'Ability to send notifications to desktop'


class GnomeToolkit(BubblejailService):
    def __init__(
        self,
        dconf_dbus: bool = False,
        gnome_vfs_dbus: bool = False,
        gnome_portal: bool = False,
    ):
        super().__init__()
        self.dconf_dbus = OptionBool(
            boolean=dconf_dbus,
            name='dconf_dbus',
            pretty_name='Dconf dbus',
            description='Access to dconf dbus API',
        )
        self.gnome_vfs_dbus = OptionBool(
            boolean=gnome_vfs_dbus,
            name='gnome_vfs_dbus',
            pretty_name='GNOME VFS',
            description='Access to GNOME Virtual File System dbus API',
        )
        self.gnome_portal = OptionBool(
            boolean=gnome_portal,
            name='gnome_portal',
            pretty_name='GNOME Portal',
            description='Access to GNOME Portal dbus API',
        )

        self.add_option(self.gnome_vfs_dbus)
        self.add_option(self.dconf_dbus)
        self.add_option(self.gnome_portal)

    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        if self.gnome_portal.get_value():
            yield EnvrimentalVar('GTK_USE_PORTAL', '1')
            yield DbusSessionTalkTo('org.freedesktop.portal.*')

        if self.dconf_dbus.get_value():
            yield DbusSessionTalkTo('ca.desrt.dconf')

        if self.gnome_vfs_dbus.get_value():
            yield DbusSessionTalkTo('org.gtk.vfs.*')

        # TODO: org.a11y.Bus accessibility services
        # Needs both dbus and socket, socket is address is
        # acquired from dbus

    name = 'gnome_toolkit'
    pretty_name = 'GNOME toolkit'
    description = 'Access to GNOME APIs'


class Pipewire(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        PIPEWIRE_SOCKET_NAME = 'pipewire-0'
        original_socket_path = (Path(BaseDirectory.get_runtime_dir())
                                / PIPEWIRE_SOCKET_NAME)

        new_socket_path = Path('/run/user/1000') / 'pipewire-0'

        yield ReadOnlyBind(str(original_socket_path), str(new_socket_path))

    name = 'pipewire'
    pretty_name = 'Pipewire'
    description = 'Pipewire sound and screencapture system'


class VideoForLinux(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield DevBindTry('/dev/v4l')
        yield DevBindTry('/sys/class/video4linux')
        yield DevBindTry('/sys/bus/media/')

        try:
            sys_v4l_iterator = Path('/sys/class/video4linux').iterdir()
            for sys_path in sys_v4l_iterator:
                pcie_path = sys_path.resolve()

                for char_path in Path('/sys/dev/char/').iterdir():
                    if char_path.resolve() == pcie_path:
                        yield Symlink(str(readlink(char_path)), str(char_path))

                yield DevBind(str(pcie_path.parents[1]))
        except FileNotFoundError:
            ...

        for dev_path in Path('/dev').iterdir():

            name = dev_path.name

            if not (name.startswith('video') or name.startswith('media')):
                continue

            if not name[5:].isnumeric():
                continue

            yield DevBind(str(dev_path))

    name = 'v4l'
    pretty_name = 'Video4Linux'
    description = 'Video capture. (webcams and etc.)'


class IBus(BubblejailService):
    def __iter__(self) -> ServiceGeneratorType:
        if not self.enabled:
            return

        yield EnvrimentalVar('IBUS_USE_PORTAL', '1')
        yield EnvrimentalVar('GTK_IM_MODULE', 'ibus')
        yield EnvrimentalVar('QT_IM_MODULE', 'ibus')
        yield EnvrimentalVar('XMODIFIERS', '@im=ibus')
        yield EnvrimentalVar('GLFW_IM_MODULE', 'ibus')
        yield DbusSessionTalkTo('org.freedesktop.portal.IBus.*')

    name = 'ibus'
    pretty_name = 'IBus input method'
    description = (
        'Gives access to IBus input method.\n'
        'This is generally the default input method for multilingual input.'
    )


SERVICES_CLASSES: Tuple[Type[BubblejailService], ...] = (
    CommonSettings, X11, Wayland,
    Network, PulseAudio, HomeShare, DirectRendering,
    Systray, Joystick, RootShare, OpenJDK, Notifications,
    GnomeToolkit, Pipewire, VideoForLinux, IBus,
)

ServicesConfDictType = Dict[str, Dict[str, ServiceOptionTypes]]


class ServiceContainer:
    def __init__(self, conf_dict: Optional[ServicesConfDictType] = None):
        self.services = list(
            (service_class() for service_class in SERVICES_CLASSES)
        )
        self.default_service = BubblejailDefaults()

        if conf_dict is not None:
            self.set_services(conf_dict)

    def set_services(
            self,
            new_services_datas: ServicesConfDictType) -> None:

        for service in self.services:
            try:
                new_service_data = new_services_datas.pop(service.name)
            except KeyError as e:
                if e.args != (service.name, ):
                    raise
                else:
                    service.enabled = False
                    continue

            service.set_options(new_service_data)
            service.enabled = True

        if new_services_datas:
            raise TypeError('Unknown conf dict keys', new_services_datas)

    def get_service_conf_dict(self) -> ServicesConfDictType:
        return {service.name: service.to_dict() for service
                in self.services
                if service.enabled}

    def iter_services(self,
                      iter_disabled: bool = False,
                      iter_default: bool = True,
                      ) -> Generator[BubblejailService, None, None]:
        if iter_default:
            yield self.default_service
        for service in self.services:
            if service.enabled or iter_disabled:
                yield service
