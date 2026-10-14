"""QgsTask wrapper: run a function off the UI thread with progress, cancel
and a main-thread callback."""

from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsTask

LOG_TAG = "OS API Data Downloader"


def log(msg, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(str(msg), LOG_TAG, level)


class FunctionTask(QgsTask):
    """``fn(task)`` runs in the worker thread; use task.report(pct, msg) and
    task.isCanceled(). ``on_done(result, error)`` runs on the main thread."""

    def __init__(self, description, fn, on_done, can_cancel=True):
        flags = QgsTask.Flag.CanCancel if can_cancel else QgsTask.Flag(0)
        super().__init__(description, flags)
        self._fn = fn
        self._on_done = on_done
        self.result_value = None
        self.error = None
        self.message = ""

    def report(self, pct, msg=None):
        if msg:
            self.message = msg      # before setProgress, so a progress listener sees the new message
        self.setProgress(max(0.0, min(100.0, float(pct))))

    def run(self):
        try:
            self.result_value = self._fn(self)
            return True
        except Exception as ex:  # surfaced on the main thread in finished()
            self.error = ex
            log(traceback.format_exc(), Qgis.MessageLevel.Critical)
            return False

    def finished(self, ok):
        try:
            self._on_done(self.result_value if ok else None, None if ok else (self.error or RuntimeError("Cancelled")))
        except Exception:
            log(traceback.format_exc(), Qgis.MessageLevel.Critical)


_RUNNING = set()


def start(task):
    """Keeps a Python reference until the task finishes (otherwise it can be garbage collected)."""
    _RUNNING.add(task)
    task.taskCompleted.connect(lambda: _RUNNING.discard(task))
    task.taskTerminated.connect(lambda: _RUNNING.discard(task))
    QgsApplication.taskManager().addTask(task)
    return task
