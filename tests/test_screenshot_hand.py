"""
Tests for trellis.hands.screenshot — Screenshot Capture + Vision Validation Hand

Tests cover:
    - ValidationResult dataclass
    - capture_screenshot / capture_start_screen with mocked Playwright
    - validate_screenshot with mocked Anthropic client
    - capture_and_validate integration with mocks
    - Discord post_file / post_file_to_channel methods
    - !screenshot command handler
    - Heartbeat screenshot validation scheduling
"""

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trellis.hands.screenshot import (
    VIEWPORTS,
    ValidationResult,
    _sync_vision_call,
    capture_and_validate,
    capture_screenshot,
    capture_start_screen,
    validate_screenshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_vault(tmp_path):
    """Create a minimal vault structure for tests."""
    screenshots_dir = tmp_path / "_ivy" / "screenshots"
    screenshots_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def config(tmp_vault):
    return {"vault_path": tmp_vault}


@pytest.fixture
def fake_png(tmp_vault):
    """Create a tiny PNG file for vision tests."""
    png_path = tmp_vault / "_ivy" / "screenshots" / "test.png"
    # Minimal valid PNG (1x1 white pixel)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    png_path.write_bytes(png_bytes)
    return png_path


# ---------------------------------------------------------------------------
# 1. ValidationResult dataclass
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_creation(self):
        vr = ValidationResult(
            passed=True,
            summary="Looks good",
            details="All elements visible",
            cost_usd=0.005,
        )
        assert vr.passed is True
        assert vr.summary == "Looks good"
        assert vr.cost_usd == 0.005

    def test_serialization(self):
        vr = ValidationResult(passed=False, summary="Bad", details="Broken", cost_usd=0.01)
        d = asdict(vr)
        assert d == {
            "passed": False,
            "summary": "Bad",
            "details": "Broken",
            "cost_usd": 0.01,
        }

    def test_failed_result_fields(self):
        vr = ValidationResult(
            passed=False,
            summary="Layout overflow detected",
            details="Navigation grid extends beyond viewport",
            cost_usd=0.003,
        )
        assert vr.passed is False
        assert "overflow" in vr.summary


# ---------------------------------------------------------------------------
# 2. capture_screenshot / capture_start_screen (mocked Playwright)
# ---------------------------------------------------------------------------

def _mock_playwright_context():
    """Build nested mock objects that mimic async Playwright."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.screenshot = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = AsyncMock()
    mock_pw.chromium = mock_chromium

    # Make it work as async context manager
    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_pw_cm, mock_page, mock_browser


class TestCaptureScreenshot:
    @pytest.mark.asyncio
    async def test_capture_returns_path(self, config):
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("trellis.hands.screenshot.async_playwright", return_value=mock_pw_cm),
            patch("trellis.hands.screenshot._start_temp_server", new_callable=AsyncMock) as mock_start,
            patch("trellis.hands.screenshot._stop_temp_server", new_callable=AsyncMock),
        ):
            mock_start.return_value = MagicMock()
            result = await capture_screenshot(config, page_path="/", phase="day")

        assert isinstance(result, Path)
        assert "screenshot-day-kiosk" in result.name
        assert result.suffix == ".png"

    @pytest.mark.asyncio
    async def test_capture_phase_lock(self, config):
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("trellis.hands.screenshot.async_playwright", return_value=mock_pw_cm),
            patch("trellis.hands.screenshot._start_temp_server", new_callable=AsyncMock) as mock_start,
            patch("trellis.hands.screenshot._stop_temp_server", new_callable=AsyncMock),
        ):
            mock_start.return_value = MagicMock()
            await capture_screenshot(config, page_path="/", phase="evening")

        # Phase lock JS should have been called
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_no_phase_skips_lock(self, config):
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("trellis.hands.screenshot.async_playwright", return_value=mock_pw_cm),
            patch("trellis.hands.screenshot._start_temp_server", new_callable=AsyncMock) as mock_start,
            patch("trellis.hands.screenshot._stop_temp_server", new_callable=AsyncMock),
        ):
            mock_start.return_value = MagicMock()
            await capture_screenshot(config, page_path="/", phase=None)

        mock_page.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_capture_start_screen_defaults(self, config):
        """capture_start_screen delegates to capture_screenshot with / path."""
        with patch(
            "trellis.hands.screenshot.capture_screenshot",
            new_callable=AsyncMock,
        ) as mock_capture:
            mock_capture.return_value = Path("/fake/screenshot.png")
            result = await capture_start_screen(config, phase="dawn")

        mock_capture.assert_called_once_with(
            config=config,
            page_path="/",
            phase="dawn",
            viewport="kiosk",
            port=8421,
        )
        assert result == Path("/fake/screenshot.png")

    @pytest.mark.asyncio
    async def test_capture_custom_viewport(self, config):
        mock_pw_cm, mock_page, mock_browser = _mock_playwright_context()

        with (
            patch("trellis.hands.screenshot.async_playwright", return_value=mock_pw_cm),
            patch("trellis.hands.screenshot._start_temp_server", new_callable=AsyncMock) as mock_start,
            patch("trellis.hands.screenshot._stop_temp_server", new_callable=AsyncMock),
        ):
            mock_start.return_value = MagicMock()
            result = await capture_screenshot(
                config, page_path="/", phase="day", viewport="phone"
            )

        assert "phone" in result.name
        # Verify viewport was passed to new_page
        call_kwargs = mock_browser.new_page.call_args[1]
        assert call_kwargs["viewport"]["width"] == VIEWPORTS["phone"]["width"]


# ---------------------------------------------------------------------------
# 3. validate_screenshot (mocked Anthropic)
# ---------------------------------------------------------------------------

class TestValidateScreenshot:
    def test_sync_vision_call_parses_json(self, fake_png):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps({
                    "passed": True,
                    "summary": "All good",
                    "details": "Everything visible",
                })
            )
        ]
        mock_response.usage = MagicMock(input_tokens=1000, output_tokens=200)

        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=mock_response)

        result = _sync_vision_call(mock_client, fake_png, "Should look nice")

        assert result["passed"] is True
        assert result["summary"] == "All good"
        assert result["cost_usd"] > 0

    def test_sync_vision_call_handles_code_fences(self, fake_png):
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='```json\n{"passed": false, "summary": "Bad", "details": "Broken"}\n```'
            )
        ]
        mock_response.usage = MagicMock(input_tokens=1000, output_tokens=200)

        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=mock_response)

        result = _sync_vision_call(mock_client, fake_png, "test")
        assert result["passed"] is False
        assert result["summary"] == "Bad"

    def test_sync_vision_call_handles_invalid_json(self, fake_png):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is not JSON at all")]
        mock_response.usage = MagicMock(input_tokens=500, output_tokens=100)

        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(return_value=mock_response)

        result = _sync_vision_call(mock_client, fake_png, "test")
        assert result["passed"] is False
        assert "Failed to parse" in result["summary"]

    @pytest.mark.asyncio
    async def test_validate_screenshot_async(self, fake_png):
        mock_result = {
            "passed": True,
            "summary": "Looks great",
            "details": "All elements present",
            "cost_usd": 0.006,
        }

        with patch(
            "trellis.hands.screenshot._sync_vision_call",
            return_value=mock_result,
        ):
            mock_client = MagicMock()
            result = await validate_screenshot(fake_png, "test expectations", mock_client)

        assert isinstance(result, ValidationResult)
        assert result.passed is True
        assert result.cost_usd == 0.006


# ---------------------------------------------------------------------------
# 4. capture_and_validate (integration with mocks)
# ---------------------------------------------------------------------------

class TestCaptureAndValidate:
    @pytest.mark.asyncio
    async def test_returns_path_and_result(self, config, fake_png):
        mock_validation = ValidationResult(
            passed=True, summary="OK", details="Fine", cost_usd=0.005
        )

        with (
            patch(
                "trellis.hands.screenshot.capture_start_screen",
                new_callable=AsyncMock,
                return_value=fake_png,
            ),
            patch(
                "trellis.hands.screenshot.validate_screenshot",
                new_callable=AsyncMock,
                return_value=mock_validation,
            ),
        ):
            path, result = await capture_and_validate(
                config=config,
                phase="day",
                expectations="test",
                anthropic_client=MagicMock(),
            )

        assert path == fake_png
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_passes_phase_and_viewport(self, config, fake_png):
        mock_validation = ValidationResult(
            passed=True, summary="OK", details="", cost_usd=0.0
        )

        with (
            patch(
                "trellis.hands.screenshot.capture_start_screen",
                new_callable=AsyncMock,
                return_value=fake_png,
            ) as mock_capture,
            patch(
                "trellis.hands.screenshot.validate_screenshot",
                new_callable=AsyncMock,
                return_value=mock_validation,
            ),
        ):
            await capture_and_validate(
                config=config,
                phase="evening",
                expectations="test",
                anthropic_client=MagicMock(),
                viewport="phone",
            )

        mock_capture.assert_called_once_with(
            config=config,
            phase="evening",
            viewport="phone",
            port=8421,
        )


# ---------------------------------------------------------------------------
# 5. Discord post_file / post_file_to_channel (mocked discord)
# ---------------------------------------------------------------------------

class TestDiscordFilePosting:
    @pytest.mark.asyncio
    async def test_post_file_to_primary_channel(self, fake_png):
        from trellis.senses.discord_channel import IvyDiscordBot

        with patch.object(IvyDiscordBot, "__init__", lambda self, **kw: None):
            bot = IvyDiscordBot.__new__(IvyDiscordBot)
            bot._primary_channel = AsyncMock()

        await bot.post_file(fake_png, "test message")
        bot._primary_channel.send.assert_called_once()
        call_kwargs = bot._primary_channel.send.call_args[1]
        assert call_kwargs["content"] == "test message"

    @pytest.mark.asyncio
    async def test_post_file_no_primary_channel(self, fake_png):
        from trellis.senses.discord_channel import IvyDiscordBot

        with patch.object(IvyDiscordBot, "__init__", lambda self, **kw: None):
            bot = IvyDiscordBot.__new__(IvyDiscordBot)
            bot._primary_channel = None

        # Should not raise
        await bot.post_file(fake_png, "test")

    @pytest.mark.asyncio
    async def test_post_file_to_channel_by_name(self, fake_png):
        from trellis.senses.discord_channel import IvyDiscordBot

        with patch.object(IvyDiscordBot, "__init__", lambda self, **kw: None):
            bot = IvyDiscordBot.__new__(IvyDiscordBot)
            bot.guild_id = 123

        mock_channel = AsyncMock()
        mock_channel.name = "development"
        mock_perms = MagicMock()
        mock_perms.send_messages = True
        mock_channel.permissions_for = MagicMock(return_value=mock_perms)

        mock_guild = MagicMock()
        mock_guild.text_channels = [mock_channel]
        mock_guild.me = MagicMock()

        bot.get_guild = MagicMock(return_value=mock_guild)

        await bot.post_file_to_channel("development", fake_png, "hello")
        mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_file_to_missing_channel(self, fake_png):
        from trellis.senses.discord_channel import IvyDiscordBot

        with patch.object(IvyDiscordBot, "__init__", lambda self, **kw: None):
            bot = IvyDiscordBot.__new__(IvyDiscordBot)
            bot.guild_id = 123

        mock_guild = MagicMock()
        mock_guild.text_channels = []
        bot.get_guild = MagicMock(return_value=mock_guild)

        # Should not raise
        await bot.post_file_to_channel("nonexistent", fake_png)


# ---------------------------------------------------------------------------
# 6. !screenshot command handler
# ---------------------------------------------------------------------------

class TestScreenshotCommand:
    @pytest.mark.asyncio
    async def test_screenshot_command_calls_capture(self):
        """Verify the !screenshot command triggers capture_and_validate."""
        from trellis.senses.discord_channel import IvyDiscordBot

        fake_path = Path("/tmp/fake.png")
        fake_result = ValidationResult(
            passed=True, summary="All good", details="", cost_usd=0.005
        )

        # Mock the discord.Client.user property at the base class level
        mock_user = MagicMock()
        mock_user.id = 1

        with patch.object(IvyDiscordBot, "__init__", lambda self, **kw: None):
            bot = IvyDiscordBot.__new__(IvyDiscordBot)

        bot.allowed_user_id = 999
        bot.guild_id = 123
        bot.vault_path = Path("/tmp/vault")
        bot.agent_state = None
        bot.anthropic_client = MagicMock()
        bot.conversations = {}
        bot.heartbeat = None
        bot.brain = MagicMock()
        # Store user in internal state so the property returns it
        bot._connection = MagicMock()
        bot._connection.user = mock_user

        mock_msg = AsyncMock()
        mock_msg.author.id = 999
        mock_msg.guild.id = 123
        mock_msg.content = "!screenshot evening"
        mock_msg.channel = AsyncMock()
        mock_msg.channel.name = "general"
        mock_msg.channel.typing = MagicMock(return_value=AsyncMock())

        with (
            patch("trellis.senses.discord_channel.log_entry"),
            patch(
                "trellis.hands.screenshot.capture_and_validate",
                new_callable=AsyncMock,
                return_value=(fake_path, fake_result),
            ) as mock_cv,
            patch(
                "trellis.core.config.load_config",
                return_value={"vault_path": Path("/tmp/vault")},
            ),
        ):
            await bot.on_message(mock_msg)

        # capture_and_validate should have been called with phase="evening"
        mock_cv.assert_called_once()
        call_kwargs = mock_cv.call_args[1]
        assert call_kwargs["phase"] == "evening"


# ---------------------------------------------------------------------------
# 7. Heartbeat screenshot validation scheduling
# ---------------------------------------------------------------------------

class TestHeartbeatScreenshotValidation:
    def test_last_screenshot_validation_initialized(self):
        from trellis.core.heartbeat import HeartbeatScheduler

        hs = HeartbeatScheduler(vault_path=Path("/tmp"))
        assert hs._last_screenshot_validation is None

    def test_config_and_client_stored(self):
        from trellis.core.heartbeat import HeartbeatScheduler

        mock_client = MagicMock()
        mock_config = {"vault_path": Path("/tmp")}
        hs = HeartbeatScheduler(
            vault_path=Path("/tmp"),
            anthropic_client=mock_client,
            config=mock_config,
        )
        assert hs.anthropic_client is mock_client
        assert hs.config is mock_config

    @pytest.mark.asyncio
    async def test_tick_triggers_screenshot_at_830(self):
        """Verify the tick schedules screenshot validation at 8:30 AM."""
        from datetime import datetime
        from unittest.mock import patch as std_patch

        from trellis.core.heartbeat import HeartbeatScheduler

        mock_client = MagicMock()
        mock_config = {"vault_path": Path("/tmp")}
        hs = HeartbeatScheduler(
            vault_path=Path("/tmp"),
            anthropic_client=mock_client,
            config=mock_config,
        )
        # Pretend morning brief already ran
        hs._last_morning = "2026-03-27"
        # Set up other timers to skip
        hs._last_inbox_check = datetime(2026, 3, 27, 8, 29)

        fake_now = datetime(2026, 3, 27, 8, 30)

        with (
            std_patch("trellis.core.heartbeat.datetime") as mock_dt,
            std_patch.object(hs, "_run_task", new_callable=AsyncMock) as mock_run,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await hs._tick()

        # Should have called _run_task with "screenshot_validation"
        task_names = [call.args[0] for call in mock_run.call_args_list]
        assert "screenshot_validation" in task_names

    @pytest.mark.asyncio
    async def test_tick_skips_screenshot_without_client(self):
        """Without anthropic_client, screenshot validation should not run."""
        from datetime import datetime
        from unittest.mock import patch as std_patch

        from trellis.core.heartbeat import HeartbeatScheduler

        hs = HeartbeatScheduler(vault_path=Path("/tmp"))
        hs._last_morning = "2026-03-27"
        hs._last_inbox_check = datetime(2026, 3, 27, 8, 29)

        fake_now = datetime(2026, 3, 27, 8, 30)

        with (
            std_patch("trellis.core.heartbeat.datetime") as mock_dt,
            std_patch.object(hs, "_run_task", new_callable=AsyncMock) as mock_run,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            await hs._tick()

        task_names = [call.args[0] for call in mock_run.call_args_list]
        assert "screenshot_validation" not in task_names

    @pytest.mark.asyncio
    async def test_discord_post_file_callback_stored(self):
        from trellis.core.heartbeat import HeartbeatScheduler

        callback = AsyncMock()
        hs = HeartbeatScheduler(
            vault_path=Path("/tmp"),
            discord_post_file_callback=callback,
        )
        assert hs._discord_post_file is callback


# ---------------------------------------------------------------------------
# 8. Viewports config
# ---------------------------------------------------------------------------

class TestViewports:
    def test_kiosk_dimensions(self):
        assert VIEWPORTS["kiosk"] == {"width": 1920, "height": 1080}

    def test_phone_dimensions(self):
        assert VIEWPORTS["phone"] == {"width": 390, "height": 844}
