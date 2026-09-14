"""Stable synchronization failures; never include provider data or exceptions."""


class SyncError(Exception):
    pass


class SyncBusy(SyncError):
    pass


class SyncVersionConflict(SyncError):
    pass


class SyncRunFailed(SyncError):
    pass


class SyncReportUnavailable(SyncError):
    pass
