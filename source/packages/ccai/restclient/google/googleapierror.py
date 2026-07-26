"""
    .. module:: googleapierror
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: Errors raised for non-success Google Cloud responses.

    :class:`NotFound` keeps the name ``google.api_core.exceptions`` used,
    because consumer code catches that name to mean "absent" — the venue's
    ``resource_or_none`` helper turns it into ``None`` rather than letting it
    propagate.  Keeping the spelling lets that handler keep working.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


from typing import Optional


class GoogleApiError(Exception):
    """
        Raised when a Google Cloud API returns a non-success status.

        :ivar status: The HTTP status code.
        :ivar reason: The message from the API's error body.
        :ivar body: The raw response body text.
    """

    def __init__(self, message: str, *, status: int = 0,
                 reason: str = "", body: Optional[str] = None) -> None:
        """
            Construct a GoogleApiError.

            :param message: The human-readable error message.
            :param status: The HTTP status code.
            :param reason: The extracted reason.
            :param body: The raw response body.
        """
        super().__init__(message)
        self.status: int = status
        self.reason: str = reason
        self.body: Optional[str] = body
        return


class NotFound(GoogleApiError):
    """
        Raised when a Google Cloud API answers 404.

        Named to match ``google.api_core.exceptions.NotFound``, which consumer
        code catches to mean "absent".
    """


class GoogleAuthError(GoogleApiError):
    """
        Raised when an access token cannot be obtained.
    """


class GoogleOperationError(GoogleApiError):
    """
        Raised when a long-running operation finishes with an error.

        The call that started it succeeded, so this is distinct from a failed
        request: the work was accepted and then failed.
    """


class GoogleOperationTimeout(GoogleApiError):
    """
        Raised when an operation does not reach DONE inside the timeout.

        Distinct from :class:`GoogleOperationError` because the operation may
        still be running — the caller stopped waiting, Google did not stop
        working.
    """
