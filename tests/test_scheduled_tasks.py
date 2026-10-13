import asyncio
from datetime import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


class TestScheduledTasks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cmd_cfg = {
            "command": "morning_brief",
            "description": "美股晨报定时推送",
            "script": "/tmp/mock_script.sh",
            "schedule": {
                "weekday": [0, 1, 2, 3, 4, 5],
                "hour": 7,
                "minute": 0,
            }
        }
        self.cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_bot",
            "bot_name": "guaguahome",
            "custom_commands": [self.cmd_cfg],
            "allowed_chat_ids": [123456],
        })

    @patch("groupconnect.engine.datetime")
    @patch("asyncio.sleep")
    async def test_scheduler_triggers_on_matching_minute(self, mock_sleep, mock_dt):
        """Scheduler triggers task when current time matches hour, minute, and weekday."""
        # Tuesday (weekday=1), 07:00:00.050
        fake_now = datetime(2026, 10, 13, 7, 0, 0, 50000)
        mock_dt.now.return_value = fake_now

        engine = GroupConnectEngine(self.cfg)
        engine.is_running = True
        engine._run_scheduled_task = AsyncMock()

        # Stop loop after first iteration
        async def stop_loop(secs):
            engine.is_running = False

        mock_sleep.side_effect = stop_loop

        await engine._scheduled_tasks_loop()

        engine._run_scheduled_task.assert_called_once_with("morning_brief", self.cmd_cfg)

    @patch("groupconnect.engine.datetime")
    @patch("asyncio.sleep")
    async def test_scheduler_skips_when_minute_does_not_match(self, mock_sleep, mock_dt):
        """Scheduler skips task when minute does not match."""
        # 07:15:00, but schedule is 07:00
        fake_now = datetime(2026, 10, 13, 7, 15, 0, 50000)
        mock_dt.now.return_value = fake_now

        engine = GroupConnectEngine(self.cfg)
        engine.is_running = True
        engine._run_scheduled_task = AsyncMock()

        async def stop_loop(secs):
            engine.is_running = False

        mock_sleep.side_effect = stop_loop

        await engine._scheduled_tasks_loop()

        engine._run_scheduled_task.assert_not_called()

    @patch("groupconnect.engine.datetime")
    @patch("asyncio.sleep")
    async def test_scheduler_skips_when_weekday_does_not_match(self, mock_sleep, mock_dt):
        """Scheduler skips task when weekday is excluded (e.g. Sunday=6)."""
        # Sunday 2026-10-18, 07:00:00
        fake_now = datetime(2026, 10, 18, 7, 0, 0, 50000)
        self.assertEqual(fake_now.weekday(), 6)
        mock_dt.now.return_value = fake_now

        engine = GroupConnectEngine(self.cfg)
        engine.is_running = True
        engine._run_scheduled_task = AsyncMock()

        async def stop_loop(secs):
            engine.is_running = False

        mock_sleep.side_effect = stop_loop

        await engine._scheduled_tasks_loop()

        engine._run_scheduled_task.assert_not_called()

    @patch("groupconnect.engine.datetime")
    @patch("asyncio.sleep")
    async def test_scheduler_defaults_minute_to_zero(self, mock_sleep, mock_dt):
        """When schedule has only 'hour: 7', minute defaults to 0."""
        cmd_cfg_no_min = {
            "command": "hourly_job",
            "script": "/tmp/mock.sh",
            "schedule": {"hour": 7}
        }
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "custom_commands": [cmd_cfg_no_min],
        })

        # Match at 07:00
        fake_now = datetime(2026, 10, 13, 7, 0, 0, 50000)
        mock_dt.now.return_value = fake_now

        engine = GroupConnectEngine(cfg)
        engine.is_running = True
        engine._run_scheduled_task = AsyncMock()

        async def stop_loop(secs):
            engine.is_running = False

        mock_sleep.side_effect = stop_loop

        await engine._scheduled_tasks_loop()
        engine._run_scheduled_task.assert_called_once_with("hourly_job", cmd_cfg_no_min)

    @patch("os.path.isfile", return_value=True)
    @patch("asyncio.create_subprocess_exec")
    async def test_run_scheduled_task_success(self, mock_exec, mock_isfile):
        """_run_scheduled_task executes subprocess and logs success when rc=0."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"OK output", b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        engine = GroupConnectEngine(self.cfg)
        engine._notify_task_failure = AsyncMock()

        await engine._run_scheduled_task("morning_brief", self.cmd_cfg)

        mock_exec.assert_called_once()
        engine._notify_task_failure.assert_not_called()

    @patch("os.path.isfile", return_value=True)
    @patch("asyncio.create_subprocess_exec")
    async def test_run_scheduled_task_failure_alerts(self, mock_exec, mock_isfile):
        """_run_scheduled_task calls _notify_task_failure when script exits non-zero."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Command timed out")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        engine = GroupConnectEngine(self.cfg)
        engine._notify_task_failure = AsyncMock()

        await engine._run_scheduled_task("morning_brief", self.cmd_cfg)

        engine._notify_task_failure.assert_called_once_with("morning_brief", 1, "Command timed out")

    @patch("os.path.isfile", return_value=False)
    async def test_run_scheduled_task_missing_script(self, mock_isfile):
        """_run_scheduled_task alerts when script file does not exist."""
        engine = GroupConnectEngine(self.cfg)
        engine._notify_task_failure = AsyncMock()

        await engine._run_scheduled_task("morning_brief", self.cmd_cfg)

        engine._notify_task_failure.assert_called_once_with("morning_brief", -1, "脚本不存在: /tmp/mock_script.sh")
