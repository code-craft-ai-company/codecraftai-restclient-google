"""
    .. module:: storageclient
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: The Cloud Storage JSON API client.

    Buckets are ACTIVE RECORD here, unlike the Compute resources: the venue
    calls ``bucket.delete(force=True)`` on entries it lists, and constructs a
    ``Bucket`` to hand to ``create_bucket``.  That is the shape the
    ``google-cloud-storage`` client had, so it is the shape kept.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


from typing import Any, Dict, List, Optional

from ccai.restclient.google.googleapierror import NotFound


STORAGE_ENDPOINT = "https://storage.googleapis.com/storage/v1"


class Bucket:
    """
        A Cloud Storage bucket.

        Constructed by callers before creation (``Bucket(client=..,
        name=..)``, then ``labels`` and ``versioning_enabled`` assigned) and
        returned by the client for existing buckets.
    """

    def __init__(self, client: Any = None, name: str = "",
                 payload: Optional[Dict[str, Any]] = None) -> None:
        """
            Construct a Bucket.

            :param client: The owning :class:`StorageClient`.
            :param name: The bucket name.
            :param payload: The decoded bucket resource, when it exists.
        """
        body = payload or {}

        self._client = client
        self.name: str = name or str(body.get("name", ""))
        self.labels: Dict[str, str] = dict(body.get("labels", {}) or {})
        self.location: Optional[str] = body.get("location", None)

        versioning = body.get("versioning", {}) or {}
        self.versioning_enabled: bool = bool(versioning.get("enabled", False))
        return

    def to_body(self) -> Dict[str, Any]:
        """
            Render this bucket as a creation body.

            :returns: The request body.
        """
        rtnval: Dict[str, Any] = {"name": self.name}
        if len(self.labels) > 0:
            rtnval["labels"] = dict(self.labels)
        if self.versioning_enabled is True:
            rtnval["versioning"] = {"enabled": True}
        return rtnval

    def delete(self, force: bool = False) -> None:
        """
            Delete this bucket.

            :param force: Delete the bucket's objects first.  The API refuses
                to delete a non-empty bucket, so without this a teardown would
                fail on any bucket that was ever written to.

            :returns: ``None``
        """
        if self._client is None:
            return
        self._client.delete_bucket(self.name, force=force)
        return


class StorageClient:
    """
        Client for the Cloud Storage JSON API.
    """

    def __init__(self, *, transport: Any, project: str,
                 endpoint: str = STORAGE_ENDPOINT) -> None:
        """
            Construct a StorageClient.

            :param transport: The shared :class:`GoogleTransport`.
            :param project: The project buckets are created in and listed
                from.
            :param endpoint: The Storage API endpoint.
        """
        self._transport = transport
        self._project = project
        self._endpoint = endpoint.rstrip("/")
        return

    @property
    def project(self) -> str:
        """
            Return the project this client is scoped to.

            :returns: The project id.
        """
        rtnval = self._project
        return rtnval

    def lookup_bucket(self, bucket_name: str) -> Optional[Bucket]:
        """
            Return a bucket by name, or None when it does not exist.

            Absence is the normal case when deciding whether to create, so it
            is answered with None rather than an error — matching the SDK
            method of the same name.

            :param bucket_name: The bucket name.

            :returns: The bucket, or None.
        """
        try:
            payload = self._transport.request(
                method="GET",
                url="{}/b/{}".format(self._endpoint, bucket_name))
        except NotFound:
            rtnval: Optional[Bucket] = None
            return rtnval

        rtnval = Bucket(client=self, payload=payload.as_dict())
        return rtnval

    def get_bucket(self, bucket_name: str) -> Bucket:
        """
            Fetch a bucket by name.

            :param bucket_name: The bucket name.

            :returns: The bucket.

            :raises: :class:`NotFound` when it does not exist.
        """
        payload = self._transport.request(
            method="GET", url="{}/b/{}".format(self._endpoint, bucket_name))

        rtnval = Bucket(client=self, payload=payload.as_dict())
        return rtnval

    def create_bucket(self, bucket: Any, location: str = "") -> Bucket:
        """
            Create a bucket.

            The bucket is passed as an OBJECT positionally, matching the SDK
            and the venue's call site.

            :param bucket: The bucket to create, carrying name and labels.
            :param location: The location to create it in.

            :returns: The created bucket.
        """
        if isinstance(bucket, Bucket) is True:
            body = bucket.to_body()
        else:
            body = {"name": getattr(bucket, "name", str(bucket))}
            labels = getattr(bucket, "labels", None)
            if labels:
                body["labels"] = dict(labels)
            if bool(getattr(bucket, "versioning_enabled", False)) is True:
                body["versioning"] = {"enabled": True}

        if location is not None and len(location) > 0:
            body["location"] = location

        payload = self._transport.request(
            method="POST", url="{}/b".format(self._endpoint),
            params={"project": self._project}, body=body)

        rtnval = Bucket(client=self, payload=payload.as_dict())
        return rtnval

    def list_buckets(self, prefix: str = "") -> List[Bucket]:
        """
            List the project's buckets, optionally filtered by name prefix.

            :param prefix: The name prefix to match.

            :returns: The matching buckets.
        """
        collected: List[Bucket] = []

        params: Dict[str, Any] = {"project": self._project}
        if prefix is not None and len(prefix) > 0:
            params["prefix"] = prefix

        while True:
            payload = self._transport.request(
                method="GET", url="{}/b".format(self._endpoint),
                params=params)

            for entry in payload.get("items", None) or []:
                collected.append(Bucket(client=self, payload=dict(entry)))

            token = payload.get("nextPageToken", None)
            if token is None or len(str(token)) == 0:
                break
            params["pageToken"] = token

        rtnval = collected
        return rtnval

    def delete_bucket(self, bucket_name: str,
                      force: bool = False) -> None:
        """
            Delete a bucket, optionally emptying it first.

            :param bucket_name: The bucket name.
            :param force: Delete the bucket's objects first.

            :returns: ``None``
        """
        if force is True:
            self._delete_objects(bucket_name=bucket_name)

        self._transport.request(
            method="DELETE",
            url="{}/b/{}".format(self._endpoint, bucket_name))
        return

    def _delete_objects(self, *, bucket_name: str) -> None:
        """
            Delete every object in a bucket.

            :param bucket_name: The bucket name.

            :returns: ``None``
        """
        params: Dict[str, Any] = {}

        while True:
            payload = self._transport.request(
                method="GET",
                url="{}/b/{}/o".format(self._endpoint, bucket_name),
                params=params)

            entries = payload.get("items", None) or []
            for entry in entries:
                name = entry.get("name", None)
                if name is None:
                    continue
                self._transport.request(
                    method="DELETE",
                    url="{}/b/{}/o/{}".format(self._endpoint, bucket_name,
                                              _quote(str(name))))

            token = payload.get("nextPageToken", None)
            if token is None or len(str(token)) == 0:
                break
            params["pageToken"] = token
        return


def _quote(value: str) -> str:
    """
        Percent-encode an object name for a URL path segment.

        Object names routinely contain ``/``, which must be encoded here or it
        would address a different resource.

        :param value: The object name.

        :returns: The encoded name.
    """
    import urllib.parse
    rtnval = urllib.parse.quote(value, safe="")
    return rtnval
