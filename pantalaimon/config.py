import configparser
import os

from typing import Union

from ipaddress import ip_address, IPv4Address, IPv6Address
from urllib.parse import urlparse, ParseResult

import logbook
import attr


class PanConfigParser(configparser.ConfigParser):
    def __init__(self):
        super().__init__(
            default_section="Default",
            defaults={
                "SSL": "True",
                "ListenAddress": "localhost",
                "ListenPort": "8009",
                "LogLevel": "warnig",
            },
            converters={
                "address": parse_address,
                "url": parse_url,
                "loglevel": parse_log_level,
            }
        )


def parse_address(value):
    # type: (str) -> Union[IPv4Address, IPv6Address]
    if value == "localhost":
        return ip_address("127.0.0.1")

    return ip_address(value)


def parse_url(value):
    # type: (str) -> ParseResult
    value = urlparse(value)

    if value.scheme not in ('http', 'https'):
        raise ValueError(f"Invalid URL scheme {value.scheme}. "
                         f"Only HTTP(s) URLs are allowed")
    value.port

    return value

def parse_log_level(value):
    # type: (str) -> logbook
    value = value.lower()

    if value == "info":
        return logbook.INFO
    elif value == "warning":
        return logbook.WARNING
    elif value == "error":
        return logbook.ERROR
    elif value == "debug":
        return logbook.DEBUG

    return logbook.WARNING


class PanConfigError(Exception):
    """Pantalaimon configuration error."""

    pass


@attr.s
class ServerConfig:
    """Server configuration.

    Args:
        homeserver (ParseResult): The URL of the Matrix homeserver that we want
            to forward requests to.
        listen_address (str): The local address where pantalaimon will listen
            for connections.
        listen_port (int): The port where pantalaimon will listen for
            connections.
        proxy (ParseResult):
            A proxy that the daemon should use when making connections to the
            homeserver.
        ssl (bool): Enable or disable SSL for the connection between
            pantalaimon and the homeserver.
    """

    homeserver = attr.ib()
    listen_address = attr.ib(type=Union[IPv4Address, IPv6Address])
    listen_port = attr.ib(type=int)
    proxy = attr.ib(type=str)
    ssl = attr.ib(type=bool, default=True)


@attr.s
class PanConfig:
    """Pantalaimon configuration.

    Args:
        config_path (str): The path where we should search for a configuration
            file.
        filename (str): The name of the file that we should read.
    """

    config_file = attr.ib()

    log_level = attr.ib(default=None)
    servers = attr.ib(init=False, default=attr.Factory(dict))

    def read(self):
        """Read the configuration file.

        Raises OSError if the file can't be read or PanConfigError if there is
        a syntax error with the config file.
        """
        config = PanConfigParser()
        try:
            config.read(os.path.abspath(self.config_file))
        except configparser.Error as e:
            raise PanConfigError(e)

        if self.log_level is None:
            self.log_level = config["Default"].getloglevel("LogLevel")

        listen_set = set()

        try:
            for section_name, section in config.items():

                if section_name == "Default":
                    continue

                homeserver = section.geturl("Homeserver")

                if not homeserver:
                    raise PanConfigError(f"Homserver is not set for "
                                         f"section {section_name}")

                listen_address = section.getaddress("ListenAddress")
                listen_port = section.getint("ListenPort")
                ssl = section.getboolean("SSL")
                proxy = section.geturl("Proxy")

                listen_tuple = (listen_address, listen_port)

                if listen_tuple in listen_set:
                    raise PanConfigError(f"The listen address/port combination"
                                         f" for section {section_name} was "
                                         f"already defined before.")
                listen_set.add(listen_tuple)

                server_conf = ServerConfig(
                    homeserver,
                    listen_address,
                    listen_port,
                    proxy,
                    ssl
                )

                self.servers[section_name] = server_conf

        except ValueError as e:
            raise PanConfigError(e)
