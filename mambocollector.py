#!/usr/bin/python -u
#
# Statsd data collector for mysql
# (c) Balazs Pocze <banyek@gmail.com>
#
import ConfigParser         # Handle config file
import socket               # Send data to statsd
import MySQLdb              # Query Mysql
import threading            # To start Worker threads
import time                 # To wait, log time etc.
from daemon import runner   # Daemonize collector


class Worker(threading.Thread):
    # Worker class (hero :-)
    # Run in threaded mode, queries database for mysql checks, sends the key and the value to statsd
    hostname = socket.gethostname()
    mysql_host = ""
    mysql_user = ""
    mysql_password = ""
    statsd_host = ""
    statsd_port = ""
    name = ""
    rate = 0
    query = ""

    # Initializes worker thread, the connecton data is taken from config.cfg's [config] section, the others from per thread section
    def __init__(self, mysql_host, mysql_user, mysql_password, statsd_host, statsd_port, name, rate, query):
        self.mysql_host = mysql_host
        self.mysql_user = mysql_user
        self.mysql_password = mysql_password
        self.name = name
        self.rate = rate
        self.query = query
        self.statsd_host = statsd_host
        self.statsd_port = statsd_port
        super(Worker, self).__init__()
        #print "Worker thread created!"

    # Connects database, run the query in every 'rate' seconds

    def run(self):
        while True:
                db = MySQLdb.connect(host=self.mysql_host,     # your host, usually localhost
                                     user=self.mysql_user,        # your username
                                     passwd=self.mysql_password,  # your password
                                     db="information_schema")     # name of the data base
                cur = db.cursor()
                cur.execute(self.query)

                for row in cur.fetchone():
                        metricdata = self.hostname+"."+self.name+":"+str(row)+"|c"
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
                        sock.sendto(metricdata, (self.statsd_host, int(self.statsd_port)))
                        print metricdata
                time.sleep(float(self.rate))

# First we open the config files and set up the Worker threads


class Collector():
        def __init__(self):
                self.stdin_path = '/dev/null'
                self.stdout_path = '/var/log/mysqls_statsd_collector.log'
                self.stderr_path = '/dev/tty'
                self.pidfile_path = '/var/log/mysql_statsd_collector.pid'
                self.pidfile_timeout = 5

        def ConfigSectionMap(self, section):
                dict1 = {}
                options = Cfg.options(section)
                for option in options:
                        try:
                                dict1[option] = Cfg.get(section, option)
                                if dict1[option] == -1:
                                        print("skip: %s" % option)
                        except:
                                print("exception on %s!" % option)
                                dict1[option] = None
                return dict1

        def run(self):
                sections = Cfg.sections()
                mysql_host = self.ConfigSectionMap("config")['mysql_host']
                mysql_user = self.ConfigSectionMap('config')['mysql_user']
                statsd_host = self.ConfigSectionMap('config')['statsd_host']
                statsd_port = self.ConfigSectionMap('config')['statsd_port']
                mysql_password = self.ConfigSectionMap('config')['mysql_password']
                sections.remove('config')
                workers = []
                for section in sections:
                        rate = self.ConfigSectionMap(section)['rate']
                        sql = self.ConfigSectionMap(section)['sql']
                        worker = Worker(mysql_host, mysql_user, mysql_password, statsd_host, statsd_port, section, rate, sql)
                        workers.append(worker)
                for worker in workers:
                        worker.daemon = True
                        worker.start()
                while True:
                        time.sleep(10)

Cfg = ConfigParser.ConfigParser()
Cfg.read('/usr/local/bin/mysql_statsd_collector.cfg')  # YEAH THIS IS UGLY - need to fix
collector = Collector()
daemon_runner = runner.DaemonRunner(collector)
daemon_runner.do_action()
