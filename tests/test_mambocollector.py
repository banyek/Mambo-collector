from configparser import RawConfigParser
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from mambocollector import InvalidResult, MySQLWorker, StatsdSender, load_workers, supervise


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "EXAMPLES/mambocollector.cfg.sample"
COMMANDS = ROOT / "EXAMPLES/mambocollector.cmd.sample"


class ConfigurationTests(unittest.TestCase):
    def test_samples_validate(self):
        workers = load_workers(CONFIG, COMMANDS, Mock(), threading.Event())
        self.assertEqual(len(workers), 3)
        self.assertTrue(all(worker.metric_type == "g" for worker in workers))

    def test_missing_and_empty_command_file_fail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "commands.cnf"
            with self.assertRaises(FileNotFoundError):
                load_workers(CONFIG, path, Mock(), threading.Event())
            path.touch()
            with self.assertRaisesRegex(ValueError, "no command sections"):
                load_workers(CONFIG, path, Mock(), threading.Event())

    def test_combined_config_skips_connection_sections(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "combined.cnf"
            path.write_text(CONFIG.read_text() + "\n" + COMMANDS.read_text())
            workers = load_workers(path, path, Mock(), threading.Event())
        self.assertEqual(len(workers), 3)

    def test_rejects_invalid_poll_intervals(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "commands.cnf"
            for value in ("0", "-1", "nan", "inf", "1e99"):
                with self.subTest(value=value):
                    path.write_text(f"[bad]\nmetricname = valid\nrate = {value}\nquery = SELECT 1\n")
                    with self.assertRaisesRegex(ValueError, r"\[bad\].*rate"):
                        load_workers(CONFIG, path, Mock(), threading.Event())


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.cursor = Mock()
        self.db = Mock()
        self.db.cursor.return_value = self.cursor
        self.sender = Mock()
        self.stop_event = threading.Event()

    def worker(self, **overrides):
        config = RawConfigParser()
        config["test"] = {"metricname": "test", "rate": "1", "query": "SELECT 1", **overrides}
        return MySQLWorker(config["test"], {}, self.sender, Mock(return_value=self.db), self.stop_event)

    def test_one_numeric_result_sends_default_counter(self):
        self.cursor.fetchone.side_effect = [(15,), None]
        self.worker().poll()
        self.sender.send.assert_called_once_with("test:15|c")
        self.cursor.close.assert_called_once()
        self.db.close.assert_called_once()

    def test_negative_gauge_is_absolute(self):
        self.cursor.fetchone.side_effect = [(-15,), None]
        self.worker(metrictype="g").poll()
        self.sender.send.assert_called_once_with("test:0|g\ntest:-15|g")

    def test_invalid_results_never_send_metrics(self):
        for rows in ([None], [(2, 8)], [(2,), (8,)], [("9|c\nextra:1",), None],
                     [(None,), None], [(float("inf"),), None]):
            with self.subTest(rows=rows):
                self.cursor.reset_mock()
                self.db.reset_mock()
                self.cursor.fetchone.side_effect = rows
                with self.assertRaises(InvalidResult):
                    self.worker().poll()
                self.sender.send.assert_not_called()
                self.cursor.close.assert_called_once()
                self.db.close.assert_called_once()

    def test_query_error_closes_database_and_cursor(self):
        self.cursor.execute.side_effect = OSError("failed")
        with self.assertRaises(OSError):
            self.worker().poll()
        self.cursor.close.assert_called_once()
        self.db.close.assert_called_once()

    def test_dead_worker_fails_supervision(self):
        worker = Mock(poll_started=None)
        worker.is_alive.return_value = False
        event = Mock()
        event.wait.return_value = False
        with self.assertRaisesRegex(RuntimeError, "worker exited"):
            supervise([worker], event)


    def test_stalled_worker_fails_supervision(self):
        worker = Mock(poll_started=1)
        event = Mock()
        event.wait.return_value = False
        with patch("mambocollector.time.monotonic", return_value=62):
            with self.assertRaisesRegex(RuntimeError, "collection exceeded"):
                supervise([worker], event)

    def test_poll_errors_back_off_and_success_resets_delay(self):
        worker = self.worker(rate="0.5")
        worker.stop_event = Mock()
        worker.stop_event.is_set.side_effect = [False, False, False, False, True]
        worker.poll = Mock(side_effect=[OSError, OSError, None, OSError])
        with self.assertLogs("mambocollector", level="ERROR"):
            worker.run()
        self.assertEqual(
            [call.args[0] for call in worker.stop_event.wait.call_args_list],
            [1, 2, 0.5, 1],
        )


class StatsdTests(unittest.TestCase):
    @patch("mambocollector.socket.socket")
    def test_sends_bytes_and_closes_socket_on_error(self, socket_factory):
        context = socket_factory.return_value
        sock = context.__enter__.return_value
        sender = StatsdSender({"statsd_host": "127.0.0.1", "statsd_port": "8125"})
        sock.sendto.side_effect = OSError("failed")
        with self.assertRaises(OSError):
            sender.send("hits:1|c")
        sock.sendto.assert_called_once_with(b"hits:1|c", ("127.0.0.1", 8125))
        context.__exit__.assert_called_once()
