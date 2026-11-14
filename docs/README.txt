Mambo-collector
===============

Mambo-collector runs configured MySQL queries and sends their results to StatsD
over UDP. Each command has its own worker. Failed polls are logged and retried
with backoff. A dead worker or a poll that takes more than 60 seconds causes the
collector to exit with an error so a service supervisor can react.

Installation
------------

Use Python 3.10 or newer with a supported security release. Install the MySQL
client development libraries, pkg-config, and the Python build prerequisites
for mysqlclient, then install the Python dependencies from requirements.txt:

    python3 -m venv /opt/mambocollector/venv
    /opt/mambocollector/venv/bin/python3 -m pip install -r requirements.txt

For a service installation, keep /opt/mambocollector, its virtual environment,
and the installed mambocollector.py owned by root and writable only by root.
Use a dedicated system user and group named mambocollector. Keep /etc/mambo and
both configuration files under administrator control. For example, use
root:mambocollector ownership with directory mode 0750 and file mode 0640.
The password is stored in the main configuration file.

Use a dedicated MySQL user with only the permissions required for its queries.
Grant SELECT only on the tables or views it needs. The process-list examples
only see sessions visible to the collector account. Grant PROCESS only if
monitoring all sessions is required, since it exposes other users' query text.

Configuration
-------------

Copy EXAMPLES/mambocollector.cfg.sample to /etc/mambo/config.cnf and replace the
sample connection values. The [mysql] section requires mysql_host, mysql_user,
mysql_password, and mysql_database. The [statsd] section requires statsd_host
and statsd_port.

Copy EXAMPLES/mambocollector.cmd.sample to /etc/mambo/commands.cnf. Each command
section requires metricname, rate, and query, with optional metrictype:

- metricname accepts ASCII letters, digits, dots, underscores, and hyphens.
- rate is a finite positive number of seconds between polls.
- query must return exactly one row with one finite numeric value.
- metrictype is c for a counter increment (the default) or g for a gauge.

Adjust the heartbeat query to your schema or remove that section. The sample
queries use gauges. To use one file, point both configuration variables at the
same file and include the command sections alongside [mysql] and [statsd].

Running
-------

Set MAMBOCFG and MAMBOCMD to override the default configuration paths. Logs go
to standard error by default. Set MAMBOLOG to write to a file, and set
MAMBODBG=1 to enable debug logging.

    python3 mambocollector.py check
    python3 mambocollector.py run

The check command validates configuration and dependency loading without
connecting to MySQL or sending metrics. Run starts the collector in the
foreground and stops on SIGTERM or Ctrl+C.

For Debian-style SysV systems, install EXAMPLES/mambo.init as the root-owned
executable /etc/init.d/mambocollector. Install mambocollector.py and its virtual
environment at the paths above. Create /var/log/mambocollector with ownership
mambocollector:mambocollector and mode 0750 before starting the service. Use the
init script's start, stop, restart, and status commands to manage the process.
