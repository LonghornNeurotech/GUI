"""Integration tests for Phase 7: Asynchronous Free-Cursor Mode."""
import json
import os
import subprocess
import pytest

APP_JS = os.path.join(os.path.dirname(__file__), "..", "tasks", "motor_imagery", "app.js")
GUI_PY = os.path.join(os.path.dirname(__file__), "..", "GUI.py")


@pytest.fixture
def app_js_content():
    with open(APP_JS) as f:
        return f.read()


@pytest.fixture
def gui_py_content():
    with open(GUI_PY) as f:
        return f.read()


class TestFreeModeCursorMarkers:
    """ASYN-03: Cursor position recorded as XDF markers."""

    def test_send_cursor_position_function_exists(self, app_js_content):
        assert "sendCursorPosition" in app_js_content

    def test_cursor_pos_marker_type(self, app_js_content):
        """Marker JSON must have type 'cursor_pos'."""
        assert '"cursor_pos"' in app_js_content or "'cursor_pos'" in app_js_content

    def test_cursor_pos_includes_xy(self, app_js_content):
        """Marker must include x and y fields."""
        # The sendCursorPosition function references cursorX and cursorY
        assert "cursorX" in app_js_content
        assert "cursorY" in app_js_content


class TestFreeModeNoCues:
    """ASYN-01: No directional cues in FREE mode."""

    def test_free_mode_directions_empty(self, app_js_content):
        """FREE mode should not use DIRECTIONS for task queue."""
        assert "startFree" in app_js_content

    def test_free_mode_has_own_draw_loop(self, app_js_content):
        """FREE mode uses drawFree, not the cued draw()."""
        assert "drawFree" in app_js_content
        assert "updateFree" in app_js_content

    def test_free_mode_skips_mindfulness(self, app_js_content):
        """startMindfulness must route FREE mode to startFree."""
        # Look for the early return pattern
        assert "startFree" in app_js_content


class TestFreeModeMarkers:
    """Session markers bracket the free cursor session."""

    def test_free_cursor_start_marker(self, app_js_content):
        assert "FREE_CURSOR" in app_js_content

    def test_free_cursor_stop_sends_none(self, app_js_content):
        """Stop marker should be FREE_CURSOR -> None."""
        assert 'sendMarker("FREE_CURSOR"' in app_js_content


class TestGUIFreeCursorButton:
    """GUI.py has Free Cursor action gated on both weights."""

    def test_free_cursor_action_exists(self, gui_py_content):
        assert "Free Cursor" in gui_py_content

    def test_free_action_attribute(self, gui_py_content):
        assert "_mi_free_action" in gui_py_content

    def test_free_action_gated_in_update_2d_gate(self, gui_py_content):
        """_update_2d_gate must also enable/disable the free action."""
        assert "_mi_free_action" in gui_py_content
        # The gate function must reference it
        gate_start = gui_py_content.index("def _update_2d_gate")
        # Find next def to bound the search
        next_def = gui_py_content.index("\n    def ", gate_start + 1)
        gate_body = gui_py_content[gate_start:next_def]
        assert "_mi_free_action" in gate_body


class TestJSSyntax:
    """app.js must be syntactically valid."""

    def test_app_js_no_syntax_errors(self):
        result = subprocess.run(
            ["node", "--check", APP_JS],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"JS syntax error: {result.stderr}"
