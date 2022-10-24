from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Union, Mapping
import asyncio

from qtpy.QtWidgets import QAction
from qtpy.QtCore import Slot, QThread, Signal, QObject
from pydm.application import PyDMApplication
from pydm.display import load_file
from pydm.utilities.stylesheet import apply_stylesheet

from .main_window import FireflyMainWindow
from .engine_runner import EngineRunner, FireflyRunEngine

generator = type((x for x in []))

__all__ = ["ui_dir", "FireflyApplication"]


ui_dir = Path(__file__).parent


class FireflyApplication(PyDMApplication):
    xafs_scan_window = None

    # Actions defined here
    run_plan = Signal(generator)
    pause_run_engine: QAction()
    setup_run_engine = Signal(FireflyRunEngine)

    def __init__(self, ui_file=None, use_main_window=False, *args, **kwargs):
        # Instantiate the the parent class
        # (*ui_file* and *use_main_window* let us render the window here instead)
        super().__init__(ui_file = None, use_main_window=use_main_window, *args, **kwargs)
        self.windows = {}
        self.show_status_window()
        # self.connect_menu_signals(window=self.windows['beamline_status'])        
        # self.windows['beamline_status'].actionShow_Xafs_Scan.triggered.emit()

    def prepare_run_engine(self, run_engine=None):
        thread = QThread()
        runner = EngineRunner(thread=thread)
        # runner.moveToThread(thread)
        # Prepare actions for controlling the run engine
        print("prepare_run_engine: ", asyncio.get_event_loop())
        self.pause_run_engine = QAction(self)
        # Connect actions to signals for controlling the run engine
        self.pause_run_engine.triggered.connect(runner.request_pause)
        self.run_plan.connect(runner.run_plan)
        self.setup_run_engine.connect(runner.setup_run_engine)
        run_engine = FireflyRunEngine()
        self.setup_run_engine.emit(run_engine)
        # Start the thread
        print("prepare_run_engine (pre_start): ", asyncio.get_event_loop())        
        thread.start()
        
        print("prepare_run_engine (post_start):", asyncio.get_event_loop())
        # Save references to the thread and runner
        self._engine_runner_thread = thread
        self._engine_runner = runner

    # def pause_run_engine(self, defer=False):
    #     self.run_engine_pause_requested.emit(defer)

    def connect_menu_signals(self, window):
        """Connects application-level signals to the associated slots.

        These signals should generally be applicable to multiple
        windows. If the signal and/or slot is specific to a given
        window, then it should be in that widnow's class definition
        and setup code.

        """
        window.actionShow_Log_Viewer.triggered.connect(self.show_log_viewer_window)
        window.actionShow_Xafs_Scan.triggered.connect(self.show_xafs_scan_window)
        window.actionShow_Voltmeters.triggered.connect(self.show_voltmeters_window)
        window.actionShow_Sample_Viewer.triggered.connect(self.show_sample_viewer_window)

    def show_window(self, WindowClass, ui_file, name=None, macros={}):
        # Come up with the default key for saving in the windows dictionary
        if name is None:
            name = f"{WindowClass.__name__}_{ui_file.name}"
        # Check if the window has already been created
        if (w := self.windows.get(name)) is None:
            # Window is not yet created, so create one
            w = self.create_window(WindowClass, ui_dir / ui_file, macros=macros)
            self.windows[name] = w
        else:
            # Window already exists so just bring it to the front
            w.show()
            w.activateWindow()
        return w

    def create_window(self, WindowClass, ui_file, macros={}):
        # Create and save this window
        main_window = WindowClass(hide_nav_bar=self.hide_nav_bar,
                                  hide_menu_bar=self.hide_menu_bar,
                                  hide_status_bar=self.hide_status_bar)
        # Make it look pretty
        apply_stylesheet(self.stylesheet_path, widget=main_window)
        main_window.update_tools_menu()
        # Load the UI file for this window
        display = main_window.open(ui_file, macros=macros)
        self.connect_menu_signals(window=main_window)
        # Show the display
        if self.fullscreen:
            main_window.enter_fullscreen()
        else:
            main_window.show()
        return main_window

    def show_status_window(self, stylesheet_path=None):
        """Instantiate a new main window for this application."""
        self.show_window(FireflyMainWindow, ui_dir / "status.ui", name="beamline_status")

    make_main_window = show_status_window

    @Slot()
    def show_log_viewer_window(self):
        self.show_window(FireflyMainWindow, ui_dir / "log_viewer.ui", name="log_viewer")

    @Slot()
    def show_xafs_scan_window(self):
        self.show_window(FireflyMainWindow, ui_dir / "xafs_scan.ui", name="xafs_scan")

    @Slot()
    def show_voltmeters_window(self):
        self.show_window(FireflyMainWindow, ui_dir / "voltmeters.ui", name="voltmeters")

    @Slot()
    def show_sample_viewer_window(self):
        self.show_window(FireflyMainWindow, ui_dir / "sample_viewer.ui", name="sample_viewer")
