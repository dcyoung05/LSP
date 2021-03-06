from .typing import Dict, Optional, List, Generator, Tuple
from .types import debounced
from contextlib import contextmanager
import sublime
import sublime_plugin


# about 80 chars per line implies maintaining a buffer of about 40kb per window
SERVER_PANEL_MAX_LINES = 500

# If nothing else shows up after 80ms, actually print the messages to the panel
SERVER_PANEL_DEBOUNCE_TIME_MS = 80

OUTPUT_PANEL_SETTINGS = {
    "auto_indent": False,
    "draw_indent_guides": False,
    "draw_white_space": "None",
    "fold_buttons": True,
    "gutter": True,
    "is_widget": True,
    "line_numbers": False,
    "lsp_active": True,
    "margin": 3,
    "match_brackets": False,
    "rulers": [],
    "scroll_past_end": False,
    "tab_size": 4,
    "translate_tabs_to_spaces": False,
    "word_wrap": False
}


class PanelName:
    Diagnostics = "diagnostics"
    References = "references"
    LanguageServers = "language servers"


@contextmanager
def mutable(view: sublime.View) -> Generator:
    view.set_read_only(False)
    yield
    view.set_read_only(True)


def create_output_panel(window: sublime.Window, name: str) -> Optional[sublime.View]:
    panel = window.create_output_panel(name)
    settings = panel.settings()
    for key, value in OUTPUT_PANEL_SETTINGS.items():
        settings.set(key, value)
    return panel


def destroy_output_panels(window: sublime.Window) -> None:
    for field in filter(lambda a: not a.startswith('__'), PanelName.__dict__.keys()):
        panel_name = getattr(PanelName, field)
        panel = window.find_output_panel(panel_name)
        if panel and panel.is_valid():
            panel.settings().set("syntax", "Packages/Text/Plain text.tmLanguage")
            window.destroy_output_panel(panel_name)


def create_panel(window: sublime.Window, name: str, result_file_regex: str, result_line_regex: str,
                 syntax: str) -> Optional[sublime.View]:
    panel = create_output_panel(window, name)
    if not panel:
        return None
    if result_file_regex:
        panel.settings().set("result_file_regex", result_file_regex)
    if result_line_regex:
        panel.settings().set("result_line_regex", result_line_regex)
    panel.assign_syntax(syntax)
    # Call create_output_panel a second time after assigning the above
    # settings, so that it'll be picked up as a result buffer
    # see: Packages/Default/exec.py#L228-L230
    panel = window.create_output_panel(name)
    # All our panels are read-only
    panel.set_read_only(True)
    return panel


def ensure_panel(window: sublime.Window, name: str, result_file_regex: str, result_line_regex: str,
                 syntax: str) -> Optional[sublime.View]:
    return window.find_output_panel(name) or create_panel(window, name, result_file_regex, result_line_regex, syntax)


class LspClearPanelCommand(sublime_plugin.TextCommand):
    """
    A clear_panel command to clear the error panel.
    """

    def run(self, edit: sublime.Edit) -> None:
        with mutable(self.view):
            self.view.erase(edit, sublime.Region(0, self.view.size()))


class LspUpdatePanelCommand(sublime_plugin.TextCommand):
    """
    A update_panel command to update the error panel with new text.
    """

    def run(self, edit: sublime.Edit, characters: Optional[str] = "") -> None:
        # Clear folds
        self.view.unfold(sublime.Region(0, self.view.size()))

        with mutable(self.view):
            self.view.replace(edit, sublime.Region(0, self.view.size()), characters or "")

        # Clear the selection
        selection = self.view.sel()
        selection.clear()


def ensure_server_panel(window: sublime.Window) -> Optional[sublime.View]:
    return ensure_panel(window, PanelName.LanguageServers, "", "", "Packages/LSP/Syntaxes/ServerLog.sublime-syntax")


def update_server_panel(window: sublime.Window, prefix: str, message: str) -> None:
    if not window.is_valid():
        return
    window_id = window.id()
    panel = ensure_server_panel(window)
    if not panel:
        return
    LspUpdateServerPanelCommand.to_be_processed.setdefault(window_id, []).append((prefix, message))
    previous_length = len(LspUpdateServerPanelCommand.to_be_processed[window_id])

    def condition() -> bool:
        if not panel:
            return False
        if not panel.is_valid():
            return False
        to_process = LspUpdateServerPanelCommand.to_be_processed.get(window_id)
        if to_process is None:
            return False
        current_length = len(to_process)
        if current_length >= 10:
            # Do not let the queue grow large.
            return True
        # If the queue remains stable, flush the messages.
        return current_length == previous_length

    debounced(
        lambda: panel.run_command("lsp_update_server_panel", {"window_id": window_id}) if panel else None,
        SERVER_PANEL_DEBOUNCE_TIME_MS,
        condition
    )


class LspUpdateServerPanelCommand(sublime_plugin.TextCommand):

    to_be_processed = {}  # type: Dict[int, List[Tuple[str, str]]]

    def run(self, edit: sublime.Edit, window_id: int) -> None:
        to_process = self.to_be_processed.pop(window_id)
        with mutable(self.view):
            for prefix, message in to_process:
                message = message.replace("\r\n", "\n")  # normalize Windows eol
                self.view.insert(edit, self.view.size(), "{}: {}\n".format(prefix, message))
                total_lines, _ = self.view.rowcol(self.view.size())
                point = 0  # Starting from point 0 in the panel ...
                regions = []  # type: List[sublime.Region]
            for _ in range(0, max(0, total_lines - SERVER_PANEL_MAX_LINES)):
                # ... collect all regions that span an entire line ...
                region = self.view.full_line(point)
                regions.append(region)
                point = region.b
            for region in reversed(regions):
                # ... and erase them in reverse order
                self.view.erase(edit, region)
