mport ConfigParser
import threading
import MySQLdb
import sys
import time
import socket
import os
import Queue
from daemon import runner
from datetime import datetime

class MySQLWorker(threading.Thread):

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
		self.logger.log("MySQLWorker started")
		while True:
			try:
				db = MySQLdb.connect(host=self.mysql_host,user=self.mysql_user,passwd=self.mysql_password,db=self.mysql_database)
			except:
                                print "Cannot connect to MySQL host"
			dbcursor = db.cursor()
			dbcursor.execute(self.query)
			for rawdata in dbcursor.fetchone():
				metricdata = self.metricname+":"+str(rawdata)+"|c"
			self.statsdsender.send(metricdata)
			self.logger.debuglog(metricdata)
			db.close()
			time.sleep(self.rate)

class StatsdSender(object):

	def __init__(self, statsdconf, logger):
		self.statsd_host = statsdconf["statsd_host"][0]
		self.statsd_port = int(statsdconf["statsd_port"][0])
		super(StatsdSender, self).__init__()
		self.logger = logger
		self.logger.log("StatsdSender created")

	def send(self, message):
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.sendto(message, (self.statsd_host, self.statsd_port))

class Mambo(object):

	def __init__(self):
		self.stdin_path = '/dev/null'
		self.stdout_path = os.getenv('MAMBOLOG','/var/log/mambocollector.log')
		self.stderr_path = os.getenv('MAMBOERR','/dev/tty')
		self.pidfile_path = os.getenv('MAMBOPID','/var/run/mambocollector.pid')
		self.configfile = os.getenv('MAMBOCFG','/etc/mambo/mambocollector.cnf')
		self.commandfile = os.getenv('MAMBOCMD','/etc/mambo/mambocollector.cmd')
		self.debug = os.getenv('MAMBODBG','0')
		self.pidfile_timeout = 5


	def configreader(self, config, section):
		cnf = ConfigParser.RawConfigParser()
		cnf.read(config)
		configItems = cnf.items(section)
		configuration = {}
		for key, value in configItems:
			configuration.setdefault(key, []).append(value)
		return configuration

	def commandreader(self, commandfile):
		cmd = ConfigParser.RawConfigParser()
		cmd.read(commandfile)
		commands = cmd.sections()
		return commands

	def checkfile(self, file):
		try:
			with open(file): pass
		except IOError:
			logger.log("Can't open file","error")
			exit(1)

	def run(self):
		logger = Logger(self.debug)
		logger.daemon = True
		logger.start()
		logger.log("Mambo started")
		workers = []
		self.checkfile(self.configfile)
		statsdconf = self.configreader(self.configfile, 'statsd')
		statsd = StatsdSender(statsdconf,logger)
		mysqlconf = self.configreader(self.configfile, 'mysql')
		commands = self.commandreader(self.commandfile)
		for command in commands:
			com = self.configreader(self.commandfile, command)
			worker = MySQLWorker(mysqlconf, com, statsd, logger)
			workers.append(worker)
		for worker in workers:
			worker.daemon = True
			worker.start()
		while True:
			time.sleep(10.0)

class Logger(threading.Thread):


	def __init__(self, debug):
		self.msgqueue = Queue.Queue()
		self.debug = debug
		super(Logger, self).__init__()

	def log(self, message):
		now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
		fullmsg = now + " - " + message + "\n"
		self.msgqueue.put(fullmsg)

	def debuglog(self, message):
		if self.debug == "1":
			now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                	fullmsg = now + " - DEBUG: " + message + "\n"
                	self.msgqueue.put(fullmsg)

	def run(self):
		while True:
			msg = self.msgqueue.get()
			sys.stdout.write(msg)
			self.msgqueue.task_done()


mambo = Mambo()
mambo_runner = runner.DaemonRunner(mambo)
mambo_runner.do_action()
