"""Small Qt-based single-instance guard for the desktop application."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

DEFAULT_SERVER_NAME = "tellme-sensei-single-instance"


class SingleInstanceGuard(QObject):
    """Own a local server endpoint for the lifetime of one application."""

    def __init__(
        self,
        server_name: str = DEFAULT_SERVER_NAME,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.server_name = server_name
        self.server = QLocalServer(self)
        self._acquired = False
        self.server.newConnection.connect(self._accept_ping)

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Claim the endpoint, returning false when another instance is alive."""

        if self._acquired:
            return True
        if self._is_running_instance():
            logger.info("another TellMeSensei instance is already running")
            return False

        # A failed connection can mean that a previous process left a stale
        # endpoint behind. Remove it only after the live-instance probe.
        QLocalServer.removeServer(self.server_name)
        if self.server.listen(self.server_name):
            self._acquired = True
            logger.info("single-instance endpoint acquired")
            return True

        # Another process may have won the listen race after our first probe.
        if self._is_running_instance():
            logger.info("another TellMeSensei instance won the startup race")
            return False

        logger.warning("unable to acquire single-instance endpoint: %s", self.server.errorString())
        return False

    def release(self) -> None:
        """Release the endpoint so a later process can start normally."""

        if not self._acquired:
            return
        self.server.close()
        QLocalServer.removeServer(self.server_name)
        self._acquired = False
        logger.info("single-instance endpoint released")

    def _is_running_instance(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self.server_name)
        connected = probe.waitForConnected(100)
        probe.disconnectFromServer()
        probe.deleteLater()
        return connected

    def _accept_ping(self) -> None:
        """Accept and immediately close a liveness ping from another process."""

        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is not None:
                socket.disconnectFromServer()
                socket.deleteLater()
