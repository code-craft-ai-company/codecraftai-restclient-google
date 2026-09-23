"""
    .. module:: computeclient
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: The Compute Engine v1 clients.

    The generated ``compute_v1`` package exposed one client class per resource
    type — ``NetworksClient``, ``InstancesClient`` and so on — each with
    ``get`` / ``insert`` / ``delete`` / ``list``.  That shape is kept here,
    because the venue holds a dict of those sub-clients and calls them by
    name.

    Mutations answer with an :class:`ComputeOperation`, not the finished
    resource.  The venue blocks on ``result()`` before reading the resource
    back — without that wait the follow-up ``get`` races the create and 404s.

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
    ProtoObject,
    wrap_many,
)


COMPUTE_ENDPOINT = "https://compute.googleapis.com/compute/v1"

DEFAULT_POLL_INTERVAL_SECONDS = 2.0

DEFAULT_OPERATION_TIMEOUT_SECONDS = 1800.0

# Compute scopes a resource globally, to a region, or to a zone; the operation
# that mutates it is polled at the matching scope.
SCOPE_GLOBAL = "global"
SCOPE_REGION = "region"
SCOPE_ZONE = "zone"


class ComputeOperation:
    """
        A handle on a Compute long-running operation.

        Mirrors the generated client's ``ExtendedOperation`` closely enough
        for consumer code: :meth:`result` blocks until the operation is DONE
        and raises when it finished with an error.
    """

    def __init__(self, *, client: Any, operation: ProtoObject,
                 project: str, scope: str = SCOPE_GLOBAL,
                 scope_name: str = "",
                 poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
                 ) -> None:
        """
            Construct a ComputeOperation.

            :param client: The owning :class:`ComputeClient`.
            :param operation: The operation resource from the initial call.
            :param project: The project the operation belongs to.
            :param scope: One of ``global``, ``region`` or ``zone``.
            :param scope_name: The region or zone name, when scoped.
            :param poll_interval: Seconds between status checks.
        """
        self._client = client
        self._operation: ProtoObject = operation
        self._project = project
        self._scope = scope
        self._scope_name = scope_name
        self._poll_interval = poll_interval
        return

    @property
    def name(self) -> str:
        """
            Return the operation name.

            :returns: The operation name.
        """
        rtnval = self._operation.name
        return rtnval

    def done(self) -> bool:
        """
            Report whether the operation has finished.

            :returns: True when the status is DONE.
        """
        rtnval = str(self._operation.status) == "DONE"
        return rtnval

    def _poll_path(self) -> str:
        """
            Build the path this operation's status is read from.

            :returns: The operation path.
        """
        name = self._operation.name

        if self._scope == SCOPE_ZONE:
            rtnval = "/projects/{}/zones/{}/operations/{}".format(
                self._project, self._scope_name, name)
            return rtnval

        if self._scope == SCOPE_REGION:
            rtnval = "/projects/{}/regions/{}/operations/{}".format(
                self._project, self._scope_name, name)
            return rtnval

        rtnval = "/projects/{}/global/operations/{}".format(
            self._project, name)
        return rtnval

    def result(self, timeout: Optional[float] = None) -> ProtoObject:
        """
            Wait for the operation and return it.

            :param timeout: Seconds to wait before giving up.

            :returns: The finished operation.

            :raises: :class:`GoogleOperationError` when the operation reports
                an error; :class:`GoogleOperationTimeout` when it has not
                finished in time.
        """
        budget = timeout
        if budget is None:
            budget = DEFAULT_OPERATION_TIMEOUT_SECONDS

        deadline = time.time() + budget

        while self.done() is False:
            if time.time() >= deadline:
                err_msg_lines = [
                    "Timed out waiting for a Compute operation."
                ]
                err_msg_lines.append("OPERATION: {}".format(
                    self._operation.name))
                err_msg_lines.append("LAST STATUS: {}".format(
                    self._operation.status))
                err_msg_lines.append(
                    "The operation may still be running; this is a timeout, "
                    "not a failure.")
                err_msg = os.linesep.join(err_msg_lines)
                raise GoogleOperationTimeout(err_msg)

            time.sleep(self._poll_interval)
            self._operation = self._client.request(method="GET",
                                                   path=self._poll_path())

        self._raise_for_error()

        rtnval = self._operation
        return rtnval

    def _raise_for_error(self) -> None:
        """
            Raise when the finished operation carries an error.

            A DONE operation is not necessarily a successful one — Compute
            reports failures in the operation body, with a 200 on the poll.

            :returns: ``None``
        """
        error = self._operation.get("error", None)
        if error is None:
            return

        errors = []
        if isinstance(error, dict) is True:
            for entry in error.get("errors", []) or []:
                if isinstance(entry, dict) is True:
                    errors.append("{}: {}".format(entry.get("code", ""),
                                                  entry.get("message", "")))
                else:
                    errors.append(str(entry))

        if len(errors) == 0:
            errors.append(str(error))

        err_msg_lines = ["The Compute operation finished with an error."]
        err_msg_lines.append("OPERATION: {}".format(self._operation.name))
        err_msg_lines.append("ERRORS: {}".format("; ".join(errors)))
        err_msg = os.linesep.join(err_msg_lines)
        raise GoogleOperationError(err_msg)


class _ResourceClient:
    """
        One Compute resource type's client.

        :cvar COLLECTION: The URL segment for the collection.
        :cvar KEY_PARAM: The keyword callers name the resource by.
        :cvar SCOPE: Whether the type is global, regional or zonal.
    """

    COLLECTION: str = ""
    KEY_PARAM: str = ""
    SCOPE: str = SCOPE_GLOBAL

    def __init__(self, *, client: Any) -> None:
        """
            Construct a resource client.

            :param client: The owning :class:`ComputeClient`.
        """
        self._client = client
        return

    def _scope_segment(self, *, kwargs: Dict[str, Any]) -> Any:
        """
            Build the scope path segment and the scope name.

            :param kwargs: The call arguments, carrying zone or region.

            :returns: A ``(segment, scope_name)`` pair.
        """
        if self.SCOPE == SCOPE_ZONE:
            name = kwargs.get("zone", "")
            rtnval = ("/zones/{}".format(name), name)
            return rtnval

        if self.SCOPE == SCOPE_REGION:
            name = kwargs.get("region", "")
            rtnval = ("/regions/{}".format(name), name)
            return rtnval

        rtnval = ("/global", "")
        return rtnval

    def _collection_path(self, **kwargs: Any) -> str:
        """
            Build the collection path.

            :param kwargs: The call arguments.

            :returns: The collection path.
        """
        project = kwargs.get("project", "")
        segment, _ = self._scope_segment(kwargs=kwargs)
        rtnval = "/projects/{}{}/{}".format(project, segment,
                                            self.COLLECTION)
        return rtnval

    def get(self, **kwargs: Any) -> ProtoObject:
        """
            Fetch one resource.

            :param kwargs: The call arguments, including the key param.

            :returns: The resource.
        """
        name = kwargs.get(self.KEY_PARAM, "")
        rtnval = self._client.request(
            method="GET",
            path="{}/{}".format(self._collection_path(**kwargs), name))
        return rtnval

    def list(self, **kwargs: Any) -> List[ProtoObject]:
        """
            List the collection, across every page.

            :param kwargs: The call arguments.

            :returns: The resources.
        """
        rtnval = self._client.paginate(path=self._collection_path(**kwargs))
        return rtnval

    def insert(self, **kwargs: Any) -> ComputeOperation:
        """
            Create a resource.

            The body arrives under a keyword ending in ``_resource``, which is
            how the generated clients named it.

            :param kwargs: The call arguments, including the body.

            :returns: A :class:`ComputeOperation`.
        """
        body: Optional[Dict[str, Any]] = None
        for key, value in kwargs.items():
            if key.endswith("_resource") is True:
                body = value

        payload = self._client.request(
            method="POST", path=self._collection_path(**kwargs), body=body)

        _, scope_name = self._scope_segment(kwargs=kwargs)
        rtnval = self._client.build_operation(
            operation=payload, project=kwargs.get("project", ""),
            scope=self.SCOPE, scope_name=scope_name)
        return rtnval

    def delete(self, **kwargs: Any) -> ComputeOperation:
        """
            Delete a resource.

            :param kwargs: The call arguments, including the key param.

            :returns: A :class:`ComputeOperation`.
        """
        name = kwargs.get(self.KEY_PARAM, "")
        payload = self._client.request(
            method="DELETE",
            path="{}/{}".format(self._collection_path(**kwargs), name))

        _, scope_name = self._scope_segment(kwargs=kwargs)
        rtnval = self._client.build_operation(
            operation=payload, project=kwargs.get("project", ""),
            scope=self.SCOPE, scope_name=scope_name)
        return rtnval


class NetworksClient(_ResourceClient):
    """The networks collection."""
    COLLECTION = "networks"
    KEY_PARAM = "network"
    SCOPE = SCOPE_GLOBAL


class SubnetworksClient(_ResourceClient):
    """The subnetworks collection."""
    COLLECTION = "subnetworks"
    KEY_PARAM = "subnetwork"
    SCOPE = SCOPE_REGION


class FirewallsClient(_ResourceClient):
    """The firewalls collection."""
    COLLECTION = "firewalls"
    KEY_PARAM = "firewall"
    SCOPE = SCOPE_GLOBAL


class InstancesClient(_ResourceClient):
    """The instances collection."""
    COLLECTION = "instances"
    KEY_PARAM = "instance"
    SCOPE = SCOPE_ZONE


class DisksClient(_ResourceClient):
    """The disks collection."""
    COLLECTION = "disks"
    KEY_PARAM = "disk"
    SCOPE = SCOPE_ZONE


class ResourcePoliciesClient(_ResourceClient):
    """The resource policies collection."""
    COLLECTION = "resourcePolicies"
    KEY_PARAM = "resource_policy"
    SCOPE = SCOPE_REGION


class ImagesClient(_ResourceClient):
    """The images collection."""
    COLLECTION = "images"
    KEY_PARAM = "image"
    SCOPE = SCOPE_GLOBAL


class ComputeClient:
    """
        Transport for the Compute Engine v1 API.

        The per-type sub-clients are reached through :meth:`sub_clients`,
        which returns the dict shape the venue's session factory built.
    """

    def __init__(self, *, transport: Any,
                 endpoint: str = COMPUTE_ENDPOINT,
                 poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
                 ) -> None:
        """
            Construct a ComputeClient.

            :param transport: The shared :class:`GoogleTransport`.
            :param endpoint: The Compute API endpoint.
            :param poll_interval: Seconds between operation status checks.
        """
        self._transport = transport
        self._endpoint = endpoint.rstrip("/")
        self._poll_interval = poll_interval
        return

    def request(self, *, method: str, path: str,
                params: Optional[Dict[str, Any]] = None,
                body: Optional[Dict[str, Any]] = None) -> ProtoObject:
        """
            Perform one Compute request.

            :param method: The HTTP method.
            :param path: The API path.
            :param params: Optional query parameters.
            :param body: Optional JSON request body.

            :returns: The decoded resource.
        """
        rtnval = self._transport.request(
            method=method, url="{}{}".format(self._endpoint, path),
            params=params, body=body)
        return rtnval

    def paginate(self, *, path: str,
                 params: Optional[Dict[str, Any]] = None
                 ) -> List[ProtoObject]:
        """
            Walk every page of a Compute collection.

            Compute pages with ``pageToken`` / ``nextPageToken`` and nests
            entries under ``items``.  A truncated listing under-reports owned
            resources, which on a teardown path means leaked infrastructure.

            :param path: The collection path.
            :param params: Optional query parameters.

            :returns: The concatenated entries.
        """
        collected: List[ProtoObject] = []

        page_params: Dict[str, Any] = {}
        if params is not None:
            page_params.update(params)

        while True:
            payload = self.request(method="GET", path=path,
                                   params=page_params)

            collected.extend(wrap_many(payload.get("items", None)))

            token = payload.get("nextPageToken", None)
            if token is None or len(str(token)) == 0:
                break
            page_params["pageToken"] = token

        rtnval = collected
        return rtnval

    def build_operation(self, *, operation: ProtoObject, project: str,
                        scope: str, scope_name: str) -> ComputeOperation:
        """
            Wrap an operation resource in a poller.

            :param operation: The operation resource.
            :param project: The project.
            :param scope: The operation scope.
            :param scope_name: The region or zone name.

            :returns: A :class:`ComputeOperation`.
        """
        rtnval = ComputeOperation(client=self, operation=operation,
                                  project=project, scope=scope,
                                  scope_name=scope_name,
                                  poll_interval=self._poll_interval)
        return rtnval

    def sub_clients(self) -> Dict[str, Any]:
        """
            Build the per-type sub-clients.

            :returns: A dict keyed the way the venue's session factory keyed
                it.
        """
        rtnval = {
            "networks": NetworksClient(client=self),
            "subnetworks": SubnetworksClient(client=self),
            "firewalls": FirewallsClient(client=self),
            "instances": InstancesClient(client=self),
            "disks": DisksClient(client=self),
            "resource_policies": ResourcePoliciesClient(client=self),
            "images": ImagesClient(client=self),
        }
        return rtnval
