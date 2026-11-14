#!/usr/bin/env python3
"""Poll MySQL and send scalar metrics to StatsD."""

import argparse
from configparser import Error as ConfigParserError, RawConfigParser
from contextlib import closing
import logging
import math
import os
import re
import signal
import socket
import threading
import time


logger = logging.getLogger(__name__)
IO_TIMEOUT = 5
POLL_DEADLINE = 60
MAX_RETRY_DELAY = 60
METRIC_NAME = re.compile(r"[A-Za-z0-9_.-]+")
NUMERIC_VALUE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def read_config(path):
    config = RawConfigParser()
    try:
        with open(path, encoding="utf-8") as stream:
            config.read_file(stream)
    except (ConfigParserError, UnicodeError) as error:
        raise ValueError(f"{path}: invalid configuration ({type(error).__name__})") from error
    return config


def required(section, key, allow_empty=False):
    value = section.get(key)
    if value is None or (not value and not allow_empty):
        raise ValueError(f"missing or empty {key}")
    return value


class StatsdSender:
    def __init__(self, config):
        self.host = required(config, "statsd_host")
        try:
            self.port = int(required(config, "statsd_port"))
            if not 1 <= self.port <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError("statsd_port must be an integer from 1 to 65535") from None

    def send(self, message):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(IO_TIMEOUT)
            sock.sendto(message.encode("ascii"), (self.host, self.port))


class InvalidResult(ValueError):
    pass


class MySQLWorker(threading.Thread):
    def __init__(self, command, mysql_options, sender, connect, stop_event):
        super().__init__(name=command.name, daemon=True)
        self.metric_name = required(command, "metricname")
        if not METRIC_NAME.fullmatch(self.metric_name):
            raise ValueError("metricname may contain only ASCII letters, digits, dots, underscores, and hyphens")
        self.metric_type = command.get("metrictype", "c")
        if self.metric_type not in {"c", "g"}:
            raise ValueError("metrictype must be c or g")
        try:
            self.rate = float(required(command, "rate"))
            if not math.isfinite(self.rate) or not 0 < self.rate <= threading.TIMEOUT_MAX:
                raise ValueError
        except ValueError:
            raise ValueError("rate must be a finite, positive polling interval in seconds") from None
        self.query = required(command, "query")
        self.mysql_options = mysql_options
        self.sender = sender
        self.connect = connect
        self.stop_event = stop_event
        self.poll_started = None

    def poll(self):
        with closing(self.connect(**self.mysql_options)) as db:
            with closing(db.cursor()) as cursor:
                cursor.execute(self.query)
                row = cursor.fetchone()
                if row is None or len(row) != 1 or cursor.fetchone() is not None:
                    raise InvalidResult("query must return exactly one row with one column")

        value = str(row[0])
        if not NUMERIC_VALUE.fullmatch(value) or not math.isfinite(float(value)):
            raise InvalidResult("query must return a finite numeric value")
        value = value.lstrip("+")
        message = f"{self.metric_name}:{value}|{self.metric_type}"
        if self.metric_type == "g" and value.startswith("-"):
            # In StatsD, a signed gauge value is relative to the current value.
            message = f"{self.metric_name}:0|g\n{message}"
        if not self.stop_event.is_set():
            self.sender.send(message)
            logger.debug("Sent metric %s", self.metric_name)

    def run(self):
        retry_delay = min(max(self.rate, 1), MAX_RETRY_DELAY)
        delay = self.rate
        while not self.stop_event.is_set():
            self.poll_started = time.monotonic()
            try:
                self.poll()
            except Exception as error:
                delay = max(self.rate, retry_delay)
                # Driver errors can contain query text or connection details.
                detail = str(error) if isinstance(error, InvalidResult) else type(error).__name__
                logger.error("[%s] Collection failed (%s). Retrying in %g seconds.",
                             self.name, detail, delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
            else:
                delay = self.rate
                retry_delay = min(max(self.rate, 1), MAX_RETRY_DELAY)
            finally:
                self.poll_started = None
            self.stop_event.wait(delay)


def load_workers(config_path, command_path, connect, stop_event):
    config = read_config(config_path)
    try:
        sender = StatsdSender(config["statsd"])
        mysql = config["mysql"]
        mysql_options = {
            "host": required(mysql, "mysql_host"),
            "user": required(mysql, "mysql_user"),
            "password": required(mysql, "mysql_password", allow_empty=True),
            "database": required(mysql, "mysql_database"),
            "connect_timeout": IO_TIMEOUT,
            "read_timeout": IO_TIMEOUT,
            "write_timeout": IO_TIMEOUT,
            "local_infile": False,
        }
    except (KeyError, ValueError) as error:
        raise ValueError(f"{config_path}: {error}") from error

    commands = config if command_path == config_path else read_config(command_path)
    sections = [name for name in commands.sections()
                if commands is not config or name not in {"mysql", "statsd"}]
    if not sections:
        raise ValueError(f"{command_path}: no command sections configured")
    workers = []
    for section in sections:
        try:
            workers.append(MySQLWorker(commands[section], mysql_options, sender, connect, stop_event))
        except ValueError as error:
            raise ValueError(f"{command_path} [{section}]: {error}") from error
    return workers


def supervise(workers, stop_event):
    for worker in workers:
        worker.start()
    while not stop_event.wait(1):
        for worker in workers:
            started = worker.poll_started
            if not worker.is_alive():
                raise RuntimeError(f"[{worker.name}] worker exited unexpectedly")
            if started is not None and time.monotonic() - started > POLL_DEADLINE:
                raise RuntimeError(f"[{worker.name}] collection exceeded {POLL_DEADLINE} seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "check"), nargs="?", default="run")
    args = parser.parse_args()
    try:
        logging.basicConfig(
            filename=os.getenv("MAMBOLOG"),
            format="%(asctime)s %(levelname)s %(message)s",
            level=logging.DEBUG if os.getenv("MAMBODBG") == "1" else logging.INFO,
        )
        import MySQLdb

        stop_event = threading.Event()
        workers = load_workers(
            os.getenv("MAMBOCFG", "/etc/mambo/config.cnf"),
            os.getenv("MAMBOCMD", "/etc/mambo/commands.cnf"),
            MySQLdb.connect,
            stop_event,
        )
        if args.action == "check":
            return 0

        def stop(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        logger.info("Starting %d collection workers", len(workers))
        try:
            supervise(workers, stop_event)
        finally:
            stop_event.set()
            deadline = time.monotonic() + IO_TIMEOUT
            for worker in workers:
                if worker.ident is not None:
                    worker.join(max(0, deadline - time.monotonic()))
    except KeyboardInterrupt:
        return 0
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
