#!/usr/bin/python -u

import ConfigParser             # Read config files
import threading                # Multithreading
import MySQLdb                  # Connect Mysql
import sys                      # Write data to stdout/stderr
import time                     # time.sleep()
import socket                   # Send data to statsd (UDP)
import os                       # Get environmental variables
import Queue                    # Handle logging because of threads
from daemon import runner       # Run mambo as a daemon
from datetime import datetime   # Write log messages


class MySQLWorker(threading.Thread):
# MySQL Worker class. Connects to MySQL server, runs queries against it, and prepare data to send to Statsd.

    def __init__(self, mysqlconf, command, statsdsender, logger):
        self.mysql_host = mysqlconf["mysql_host"][0]
        self.mysql_user = mysqlconf["mysql_user"][0]
        self.mysql_password = mysqlconf["mysql_password"][0]
        self.mysql_database = mysqlconf["mysql_database"][0]
        self.metricname = command["metricname"][0]
        self.rate = float(command["rate"][0])
        self.query = command["query"][0]
        self.statsdsender = statsdsender
        self.logger = logger
        super(MySQLWorker, self).__init__()
        self.logger.log("MySQLWorker created")

    def run(self):
    # Runs queries against server in an infinite loop

        self.logger.log("MySQLWorker started")
        while True:
            try:
                db = MySQLdb.connect(host=self.mysql_host, user=self.mysql_user, passwd=self.mysql_password, db=self.mysql_database)
            	dbcursor = db.cursor()
            	dbcursor.execute(self.query)
            	for rawdata in dbcursor.fetchone():
                	metricdata = self.metricname+":"+str(rawdata)+"|c"
            	self.statsdsender.send(metricdata)
            	self.logger.debuglog(metricdata)
            	db.close()
            except:
                self.logger.log("Cannot connect to MySQL host")
            time.sleep(self.rate)


class StatsdSender(object):
# This class sends data to Statsd server

    def __init__(self, statsdconf, logger):
        self.statsd_host = statsdconf["statsd_host"][0]
        self.statsd_port = int(statsdconf["statsd_port"][0])
        super(StatsdSender, self).__init__()
        self.logger = logger
        self.logger.log("StatsdSender created")

    def send(self, message):
        # Send data
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
        sock.sendto(message, (self.statsd_host, self.statsd_port))


class Logger(threading.Thread):
# Logger, to maintain threads logging in human readable format.

    def __init__(self, debug):
        self.msgqueue = Queue.Queue()
        self.debug = debug
        super(Logger, self).__init__()

    def log(self, message):
        # Puts message to message queue
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fullmsg = now + " - " + message + "\n"
        self.msgqueue.put(fullmsg)

    def debuglog(self, message):
        # If debug set (MAMBODBG environmental variable set to 1) puts debug message to message queue
        if self.debug == "1":
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            fullmsg = now + " - DEBUG: " + message + "\n"
            self.msgqueue.put(fullmsg)

    def run(self):
        # Runs message queue, prints out data.
        while True:
            msg = self.msgqueue.get()
            sys.stdout.write(msg)
            self.msgqueue.task_done()


class Mambo(object):
# Main program. Initializes the logger, the statsd sender, and mysql workers

    def __init__(self):
        self.stdin_path = '/dev/null'
        self.stdout_path = os.getenv('MAMBOLOG', '/var/log/mambo.log')
        self.stderr_path = os.getenv('MAMBOERR', '/dev/tty')
        self.pidfile_path = os.getenv('MAMBOPID', '/var/run/mambo.pid')
        self.configfile = os.getenv('MAMBOCFG', '/etc/mambo/config.cnf')
        self.commandfile = os.getenv('MAMBOCMD', '/etc/mambo/commands.cnf')
        self.debug = os.getenv('MAMBODBG', '0')
        self.pidfile_timeout = 5

    def configreader(self, config, section):
        # Configuration reader helper. Reads keys/values from a given section, returns dict.
        cnf = ConfigParser.RawConfigParser()
        cnf.read(config)
        configItems = cnf.items(section)
        configuration = {}
        for key, value in configItems:
            configuration.setdefault(key, []).append(value)
        return configuration

    def commandreader(self, commandfile):
        # Reads commands from commandfile. (Reads section names from an ini file, returns a list)
        cmd = ConfigParser.RawConfigParser()
        cmd.read(commandfile)
        commands = cmd.sections()
        return commands

    def checkfile(self, file):
        # Checks file if exists.
        try:
            with open(file):
                pass
        except IOError:
            sys.stderr.wirte("Can't open file")
            exit(1)

    def run(self):
        # Main program thread.

        # Set up, and start logger threads.
        logger = Logger(self.debug)
        logger.daemon = True
        logger.start()
        logger.log("Mambo started")

        # Initializes workers
        workers = []
        self.checkfile(self.configfile)
        # Read statsd configuration, and creates an instance
        statsdconf = self.configreader(self.configfile, 'statsd')
        statsd = StatsdSender(statsdconf, logger)
        # Reads mysql configs and mysql commands, sets up mysql workers
        mysqlconf = self.configreader(self.configfile, 'mysql')
        commands = self.commandreader(self.commandfile)
        for command in commands:
            com = self.configreader(self.commandfile, command)
            worker = MySQLWorker(mysqlconf, com, statsd, logger)
            workers.append(worker)
        for worker in workers:
            worker.daemon = True
            worker.start()
        # Run 'till end.
        while True:
            time.sleep(10.0)

# Program execution starts here

mambo = Mambo()
mambo_runner = runner.DaemonRunner(mambo)
mambo_runner.do_action()
