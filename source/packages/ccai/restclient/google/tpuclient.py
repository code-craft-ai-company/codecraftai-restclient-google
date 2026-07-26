"""
    .. module:: tpuclient
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: The Cloud TPU v2 client.

    TPU nodes are addressed by their full resource path
    (``projects/{p}/locations/{zone}/nodes/{id}``), which is what the venue
    passes around, so the methods take ``name`` and ``parent`` exactly as the
    generated ``tpu_v2.TpuClient`` did.

    Node creation is long-running and answers with an operation, which the
    venue waits on before reading the node back.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import os
import time

from typing import Any, Dict, List, Optional

from ccai.restclient.google.googleapierror import (
    GoogleOperationError, GoogleOperationTimeout
)
from ccai.restclient.google.googleobject import (
    ProtoObject, wrap_many, wrap_value
)


TPU_ENDPOINT = "https://tpu.googleapis.com/v2"

DEFAULT_POLL_INTERVAL_SECONDS = 5.0

DEFAULT_OPERATION_TIMEOUT_SECONDS = 1800.0


class TpuOperation:
    """
        A handle on a TPU long-running operation.
    """

    def __init__(self, *, client: Any, operation: ProtoObject,
                 poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
                 ) -> None:
        """
            Construct a TpuOperation.

            :param client: The owning :class:`TpuClient`.
            :param operation: The operation resource.
            :param poll_interval: Seconds between status checks.
        """
        self._client = client
        self._operation: ProtoObject = operation
        self._poll_interval = poll_interval
        return

    def done(self) -> bool:
        """
            Report whether the operation has finished.

            :returns: True when the operation reports done.
        """
        rtnval = bool(self._operation.get("done", False))
        return rtnval

    def result(self, timeout: Optional[float] = None) -> Any:
        """
            Wait for the operation and return its response.

            :param timeout: Seconds to wait before giving up.

            :returns: The operation's response payload.

            :raises: :class:`GoogleOperationError` when the operation
                finished with an error; :class:`GoogleOperationTimeout` when
                it has not finished in time.
        """
        budget = timeout
        if budget is None:
            budget = DEFAULT_OPERATION_TIMEOUT_SECONDS

        deadline = time.time() + budget

        while self.done() is False:
            if time.time() >= deadline:
                err_msg_lines = ["Timed out waiting for a TPU operation."]
                err_msg_lines.append("OPERATION: {}".format(
                    self._operation.get("name", "")))
                err_msg_lines.append(
                    "The operation may still be running; this is a timeout, "
                    "not a failure.")
                err_msg = os.linesep.join(err_msg_lines)
                raise GoogleOperationTimeout(err_msg)

            time.sleep(self._poll_interval)
            self._operation = self._client.get_operation(
                name=str(self._operation.get("name", "")))

        error = self._operation.get("error", None)
        if error is not None:
            err_msg_lines = ["The TPU operation finished with an error."]
            err_msg_lines.append("OPERATION: {}".format(
                self._operation.get("name", "")))
            if isinstance(error, dict) is True:
                err_msg_lines.append("CODE: {}".format(error.get("code", "")))
                err_msg_lines.append("MESSAGE: {}".format(
                    error.get("message", "")))
            else:
                err_msg_lines.append("ERROR: {}".format(error))
            err_msg = os.linesep.join(err_msg_lines)
            raise GoogleOperationError(err_msg)

        rtnval = wrap_value(self._operation.get("response", None))
        return rtnval


class TpuClient:
    """
        Client for the Cloud TPU v2 API.
    """

    def __init__(self, *, transport: Any, endpoint: str = TPU_ENDPOINT,
                 poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
                 ) -> None:
        """
            Construct a TpuClient.

            :param transport: The shared :class:`GoogleTransport`.
            :param endpoint: The TPU API endpoint.
            :param poll_interval: Seconds between operation status checks.
        """
        self._transport = transport
        self._endpoint = endpoint.rstrip("/")
        self._poll_interval = poll_interval
        return

    def get_node(self, *, name: str) -> ProtoObject:
        """
            Fetch one TPU node by its full resource path.

            :param name: The full node path.

            :returns: The node.
        """
        rtnval = self._transport.request(
            method="GET", url="{}/{}".format(self._endpoint, name))
        return rtnval

    def create_node(self, *, parent: str, node_id: str,
                    node: Dict[str, Any]) -> TpuOperation:
        """
            Create a TPU node.

            :param parent: The parent path, ``projects/{p}/locations/{zone}``.
            :param node_id: The node id.
            :param node: The node body.

            :returns: A :class:`TpuOperation`.
        """
        payload = self._transport.request(
            method="POST",
            url="{}/{}/nodes".format(self._endpoint, parent),
            params={"nodeId": node_id}, body=node)

        rtnval = TpuOperation(client=self, operation=payload,
                              poll_interval=self._poll_interval)
        return rtnval

    def delete_node(self, *, name: str) -> TpuOperation:
        """
            Delete a TPU node.

            :param name: The full node path.

            :returns: A :class:`TpuOperation`.
        """
        payload = self._transport.request(
            method="DELETE", url="{}/{}".format(self._endpoint, name))

        rtnval = TpuOperation(client=self, operation=payload,
                              poll_interval=self._poll_interval)
        return rtnval

    def list_nodes(self, *, parent: str) -> List[ProtoObject]:
        """
            List the TPU nodes under a parent, across every page.

            :param parent: The parent path.

            :returns: The nodes.
        """
        collected: List[ProtoObject] = []
        params: Dict[str, Any] = {}

        url = "{}/{}/nodes".format(self._endpoint, parent)

        while True:
            payload = self._transport.request(method="GET", url=url,
                                              params=params)

            collected.extend(wrap_many(payload.get("nodes", None)))

            token = payload.get("nextPageToken", None)
            if token is None or len(str(token)) == 0:
                break
            params["pageToken"] = token

        rtnval = collected
        return rtnval

    def get_operation(self, *, name: str) -> ProtoObject:
        """
            Fetch a TPU operation by name.

            :param name: The operation name.

            :returns: The operation.
        """
        rtnval = self._transport.request(
            method="GET", url="{}/{}".format(self._endpoint, name))
        return rtnval
