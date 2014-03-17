Mambo-collector
===============

MySQL data collector for statsd.


How it works
------------

+----------------+         +-----------------+       +-----------------+
|    MySQL       |  <--->  |  Mambocollector |  ---> |     Statsd      |
+----------------+         +-----------------+       +-----------------+

Long story short: the mambocollector runs predefinied SQL queries against a MySQL instance, and sends the results to a statsd server via UDP.
After startup, the daemon starts one thread for logging purposes, and one thread for each mysql commands which is needed to run.
All the command threads (MySQLWorker) initializes with connection parameters, and runs the defined query in defined time period until the daemon is not stopped. The logger thread gets log messages from workers, and writes them to the logfile.

Dependencies
------------

* MySQLdb
* daemon

You can install them both with pip

Configuration
-------------

There is two configuration files used, one for the connection parameters, and the second one is for the commands themselves.

* Config file

  It holds the connection parameters in standard .ini file format. The statsd parameters can be configured with the [statsd] section of configuration file, the 'statsd_host' and the 'statsd_port' parameters are configurable;
  The MySQL config parameters are under [mysql] section, and 'mysql_host', 'mysql_user', 'mysql_password', 'hostname' parameters are configurable.

* Command file

  The command file contains the actual MySQL queries which will run against the database. Each command is represented with its own section, and the following parameters are configurable:
  'metricname' the query will be sent to statsd server to put under this key
  'rate' this parameter configures the frequency of datac ollection. Each worker thread sleeps 'rate' seconds between two queries
  'query' This is the actual SQL query which will be run against the database to collect data.

* Enviromental variables

  The collector daemon can be fine tuned from different enviromental variables. I recommend to set up these variables in the daemon init scripts (See examples)

  MAMBOLOG this variable sets up the log file where the mambocollector logs data & debug data defaults to '/var/log/mambo.log'
  MAMBOERR this variable sets up where to log the error messages defaults to '/dev/tty' (console)
  MAMBOPID pidfile location defaults to '/var/run/mambo.pid'
  MAMBOCFG config file name, defaults to '/etc/mambo/config.cnf'
  MAMBOCMD command file name, defaults to '/etc/mambo/commands.cnf'
  

Usage
-----

* mambocollector start
* mambocollector stop
* mambocollector restart
