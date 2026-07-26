"""
    .. module:: googletransport
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: :class:`GoogleTransport` — the shared authenticated transport.

    Every Google Cloud API this package speaks is JSON over HTTPS with a
    bearer token, so one transport serves Compute, Storage, DNS and TPU.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import json
import os

from typing import Any, Dict, Optional

import requests

from ccai.restclient.google.googleapierror import GoogleApiError, NotFound
from ccai.restclient.google.googleobject import ProtoObject, wrap_value


DEFAULT_TIMEOUT_SECONDS = 60.0


class GoogleTransport:
    """
        Authenticated JSON transport for the Google Cloud APIs.
    """

    def __init__(self, *, token_provider: Any,
                 session: Optional[Any] = None,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        """
            Construct a GoogleTransport.

            :param token_provider: Supplies bearer tokens.
            :param session: Optional pre-built ``requests.Session`` — the test
                seam.
            :param timeout_seconds: The default per-request timeout.
        """
        self._token_provider = token_provider
        self._timeout_seconds = timeout_seconds

        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
        return

    def request(self, *, method: str, url: str,
                params: Optional[Dict[str, Any]] = None,
                body: Optional[Dict[str, Any]] = None,
                timeout_seconds: Optional[float] = None) -> ProtoObject:
        """
            Perform one authenticated request.

            :param method: The HTTP method.
            :param url: The absolute URL.
            :param params: Optional query parameters; ``None`` values are
                dropped.
            :param body: Optional JSON request body.
            :param timeout_seconds: Optional per-request timeout override.

            :returns: The decoded response, empty when there is no body.

            :raises: :class:`NotFound` on 404, otherwise
                :class:`GoogleApiError` on a non-success status.
        """
        query: Dict[str, Any] = {}
        if params is not None:
            for key, value in params.items():
                if value is not None:
                    query[key] = value

        headers: Dict[str, str] = {
            "Authorization": "Bearer {}".format(self._token_provider.token()),
            "Accept": "application/json",
        }

        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers["Content-Type"] = "application/json"

        timeout = timeout_seconds
        if timeout is None:
            timeout = self._timeout_seconds

        response = self._session.request(method, url, params=query,
                                         data=payload, headers=headers,
                                         timeout=timeout)

        status = getattr(response, "status_code", 0)

        if status < 200 or status >= 300:
            text = getattr(response, "text", "")
            reason = self._extract_reason(response=response,
                                          fallback=getattr(response,
                                                           "reason", ""))
            err_msg_lines = ["The Google Cloud API request failed."]
            err_msg_lines.append("METHOD: {}".format(method))
            err_msg_lines.append("URL: {}".format(url))
            err_msg_lines.append("STATUS: {}".format(status))
            err_msg_lines.append("REASON: {}".format(reason))
            err_msg = os.linesep.join(err_msg_lines)

            if status == 404:
                raise NotFound(err_msg, status=status, reason=reason,
                               body=text)

            raise GoogleApiError(err_msg, status=status, reason=reason,
                                 body=text)

        text = getattr(response, "text", "")
        if text is None or len(text.strip()) == 0:
            rtnval = ProtoObject()
            return rtnval

        try:
            decoded = response.json()
        except Exception:
            rtnval = ProtoObject()
            return rtnval

        wrapped = wrap_value(decoded)
        if isinstance(wrapped, ProtoObject) is True:
            rtnval = wrapped
            return rtnval

        rtnval = ProtoObject({"items": wrapped})
        return rtnval

    def _extract_reason(self, *, response: Any, fallback: str) -> str:
        """
            Pull the message out of a Google error body.

            Failures arrive as ``{"error": {"code": ..., "message": ...}}``,
            which is far more useful than the HTTP phrase.

            :param response: The failed response.
            :param fallback: The reason to use when the body is unhelpful.

            :returns: The extracted reason.
        """
        try:
            decoded = response.json()
        except Exception:
            rtnval = fallback
            return rtnval

        if isinstance(decoded, dict) is False:
            rtnval = fallback
            return rtnval

        error = decoded.get("error", None)
        if isinstance(error, dict) is True:
            rtnval = str(error.get("message", fallback))
            return rtnval
        if error is not None:
            rtnval = str(error)
            return rtnval

        rtnval = fallback
        return rtnval
