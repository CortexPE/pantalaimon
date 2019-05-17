from collections import defaultdict
from queue import Empty

import attr
from gi.repository import GLib
from pydbus import SessionBus
from pydbus.generic import signal

from pantalaimon.log import logger
from pantalaimon.store import PanStore
from pantalaimon.thread_messages import (AcceptSasMessage, CancelSasMessage,
                                         ConfirmSasMessage, DaemonResponse,
                                         DeviceBlacklistMessage,
                                         DeviceUnblacklistMessage,
                                         DeviceUnverifyMessage,
                                         DeviceVerifyMessage,
                                         ExportKeysMessage, ImportKeysMessage,
                                         InviteSasSignal, SasDoneSignal,
                                         ShowSasSignal, StartSasMessage,
                                         UpdateDevicesMessage,
                                         UpdateUsersMessage)


class IdCounter:
    def __init__(self):
        self._message_id = 0

    @property
    def message_id(self):
        ret = self._message_id
        self._message_id += 1

        return ret


class Control:
    """
    <node>
        <interface name='org.pantalaimon1.control'>
            <method name='ListUsers'>
                <arg type='a(ss)' name='users' direction='out'/>
            </method>

            <method name='ExportKeys'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='file_path' direction='in'/>
                <arg type='s' name='passphrase' direction='in'/>
                <arg type='u' name='id' direction='out'/>
            </method>

            <method name='ImportKeys'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='file_path' direction='in'/>
                <arg type='s' name='passphrase' direction='in'/>
                <arg type='u' name='id' direction='out'/>
            </method>

            <signal name="Response">
                <arg direction="out" type="i" name="id"/>
                <arg direction="out" type="s" name="pan_user"/>
                <arg direction="out" type="a{ss}" name="message"/>
            </signal>
        </interface>
    </node>
    """

    Response = signal()

    def __init__(self, queue, user_list, id_counter):
        self.users = user_list
        self.queue = queue
        self.id_counter = id_counter

    @property
    def message_id(self):
        return self.id_counter.message_id

    def ListUsers(self):
        """Return the list of pan users."""
        return self.users

    def ExportKeys(self, pan_user, filepath, passphrase):
        message = ExportKeysMessage(
            self.message_id,
            pan_user,
            filepath,
            passphrase
        )
        self.queue.put(message)
        return message.message_id

    def ImportKeys(self, pan_user, filepath, passphrase):
        message = ImportKeysMessage(
            self.message_id,
            pan_user,
            filepath,
            passphrase
        )
        self.queue.put(message)
        return message.message_id


class Devices:
    """
    <node>
        <interface name='org.pantalaimon1.devices'>
            <method name='List'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='aa{ss}' name='devices' direction='out'/>
            </method>

            <method name='ListUserDevices'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='user_id' direction='in'/>
                <arg type='aa{ss}' name='devices' direction='out'/>
            </method>

            <method name='StartKeyVerification'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='user_id' direction='in'/>
                <arg type='s' name='device_id' direction='in'/>
                <arg type='u' name='id' direction='out'/>
            </method>

            <method name='CancelKeyVerification'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='user_id' direction='in'/>
                <arg type='s' name='device_id' direction='in'/>
                <arg type='u' name='id' direction='out'/>
            </method>

            <method name='AcceptKeyVerification'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='user_id' direction='in'/>
                <arg type='s' name='device_id' direction='in'/>
                <arg type='u' name='id' direction='out'/>
            </method>

            <method name='ConfirmKeyVerification'>
                <arg type='s' name='pan_user' direction='in'/>
                <arg type='s' name='user_id' direction='in'/>
                <arg type='s' name='device_id' direction='in'/>
                <arg type='u' name='id' direction='out'/>
            </method>

            <signal name="VerificationInvite">
                <arg direction="out" type="s" name="pan_user"/>
                <arg direction="out" type="s" name="user_id"/>
                <arg direction="out" type="s" name="device_id"/>
                <arg direction="out" type="s" name="transaction_id"/>
            </signal>

            <signal name="VerificationString">
                <arg direction="out" type="s" name="pan_user"/>
                <arg direction="out" type="s" name="user_id"/>
                <arg direction="out" type="s" name="device_id"/>
                <arg direction="out" type="s" name="transaction_id"/>
                <arg direction="out" type="a(ss)" name="emoji"/>
            </signal>

            <signal name="VerificationCancel">
                <arg direction="out" type="s" name="pan_user"/>
                <arg direction="out" type="s" name="user_id"/>
                <arg direction="out" type="s" name="device_id"/>
                <arg direction="out" type="s" name="transaction_id"/>
                <arg direction="out" type="s" name="reason"/>
                <arg direction="out" type="s" name="code"/>
            </signal>

            <signal name="VerificationDone">
                <arg direction="out" type="s" name="pan_user"/>
                <arg direction="out" type="s" name="user_id"/>
                <arg direction="out" type="s" name="device_id"/>
                <arg direction="out" type="s" name="transaction_id"/>
            </signal>

        </interface>
    </node>
    """

    VerificationInvite = signal()
    VerificationCancel = signal()
    VerificationString = signal()
    VerificationDone = signal()

    def __init__(self, queue, store, id_counter):
        self.store = store
        self.device_list = None
        self.queue = queue
        self.id_counter = id_counter
        self.update_devices()

    @property
    def message_id(self):
        return self.id_counter.message_id

    def List(self, pan_user):
        device_store = self.device_list.get(pan_user, None)

        if not device_store:
            return []

        device_list = [
            device for device_list in device_store.values() for device in
            device_list.values()
        ]

        return device_list

    def ListUserDevices(self, pan_user, user_id):
        device_store = self.device_list.get(pan_user, None)

        if not device_store:
            return []

        device_list = device_store.get(user_id, None)

        if not device_list:
            return []

        return device_list.values()

    def Verify(self, pan_user, user_id, device_id):
        message = DeviceVerifyMessage(
            self.message_id,
            pan_user,
            user_id,
            device_id
        )
        self.queue.put(message)
        return message.message_id

    def UnVerify(self, pan_user, user_id, device_id):
        message = DeviceUnverifyMessage(
            self.message_id,
            pan_user,
            user_id,
            device_id
        )
        self.queue.put(message)
        return message.message_id

    def StartKeyVerification(self, pan_user, user_id, device_id):
        message = StartSasMessage(
            self.message_id,
            pan_user,
            user_id,
            device_id
        )
        self.queue.put(message)
        return message.message_id

    def CancelKeyVerification(self, pan_user, user_id, device_id):
        message = CancelSasMessage(
            self.message_id,
            pan_user,
            user_id,
            device_id
        )
        self.queue.put(message)
        return message.message_id

    def ConfirmKeyVerification(self, pan_user, user_id, device_id):
        message = ConfirmSasMessage(
            self.message_id,
            pan_user,
            user_id,
            device_id
        )
        self.queue.put(message)
        return message.message_id

    def AcceptKeyVerification(self, pan_user, user_id, device_id):
        message = AcceptSasMessage(
            self.message_id,
            pan_user,
            user_id,
            device_id
        )
        self.queue.put(message)
        return message.message_id

    def update_devices(self):
        self.device_list = self.store.load_all_devices()


@attr.s
class GlibT:
    receive_queue = attr.ib()
    send_queue = attr.ib()
    data_dir = attr.ib()

    loop = attr.ib(init=False)
    store = attr.ib(init=False)
    users = attr.ib(init=False)
    devices = attr.ib(init=False)
    bus = attr.ib(init=False)
    control_if = attr.ib(init=False)
    device_if = attr.ib(init=False)

    def __attrs_post_init__(self):
        self.loop = None

        self.store = PanStore(self.data_dir)
        self.users = self.store.load_all_users()

        id_counter = IdCounter()

        self.control_if = Control(self.send_queue, self.users, id_counter)
        self.device_if = Devices(self.send_queue, self.store, id_counter)

        self.bus = SessionBus()
        self.bus.publish("org.pantalaimon1", self.control_if, self.device_if)

    def message_callback(self):
        try:
            message = self.receive_queue.get_nowait()
        except Empty:
            return True

        logger.debug(f"UI loop received message {message}")

        if isinstance(message, UpdateDevicesMessage):
            self.device_if.update_devices()

        elif isinstance(message, InviteSasSignal):
            self.device_if.VerificationInvite(
                message.pan_user,
                message.user_id,
                message.device_id,
                message.transaction_id
            )

        elif isinstance(message, ShowSasSignal):
            self.device_if.VerificationString(
                message.pan_user,
                message.user_id,
                message.device_id,
                message.transaction_id,
                message.emoji,
            )

        elif isinstance(message, SasDoneSignal):
            self.device_if.VerificationDone(
                message.pan_user,
                message.user_id,
                message.device_id,
                message.transaction_id,
            )

        elif isinstance(message, DaemonResponse):
            self.control_if.Response(
                message.message_id,
                message.pan_user,
                {
                    "code": message.code,
                    "message": message.message
                }
            )

        self.receive_queue.task_done()
        return True

    def run(self):
        self.loop = GLib.MainLoop()
        GLib.timeout_add(100, self.message_callback)
        self.loop.run()

    def stop(self):
        if self.loop:
            self.loop.quit()
            self.loop = None
