Mambo-collector
===============

Data collector for statsd.
Currently only for MySQL but I have a plan to rewrite it to a bit more common data collector, with a numerous backends. (shell scripts, other SQL servers, NoSQL etc.)

The main idea of this, that we use a lot of metrics visualised in graphite, but I have no MySQL data there, but it would be useful.

The collector currently has 2 files, the collector daemon, and the configuration file. (See mambocollector.cfg.sample for more information)

How it works
------------

The mambocollector reads it's configuraton file, daemonizes itself, and start background collector threads which are defined in the configuration file. All the threads runs separately, wakes up in configured seconds, queries the database, and send the data towards the statsd server.

Usage
-----

# mambocollector start
# mambocollector stop
# mambocollector restart

Dependencies
------------

mysql2
daemon
