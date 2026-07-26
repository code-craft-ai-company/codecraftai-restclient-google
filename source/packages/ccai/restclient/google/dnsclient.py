"""
    .. module:: dnsclient
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: The Cloud DNS client.

    Cloud DNS does not accept a record edit directly — it accepts a CHANGE,
    which is a set of additions and deletions applied atomically.  The
    ``google-cloud-dns`` client modelled that as ``zone.changes()``, on which
    you stage ``add_record_set`` / ``delete_record_set`` and then ``create()``.
    That shape is kept, because it is both what the venue calls and an honest
    reflection of how the API works: replacing a record set is a delete and an
    add in ONE change, and splitting it into two calls would leave the zone
    briefly without the record.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


from typing import Any, Dict, List, Optional


DNS_ENDPOINT = "https://dns.googleapis.com/dns/v1"


class ResourceRecordSet:
    """
        One DNS record set.
    """

    def __init__(self, *, name: str, record_type: str, ttl: int,
                 rrdatas: List[str], zone: Any = None) -> None:
        """
            Construct a ResourceRecordSet.

            :param name: The fully-qualified record name.
            :param record_type: The record type, e.g. ``A``.
            :param ttl: The time to live in seconds.
            :param rrdatas: The record values.
            :param zone: The owning zone.
        """
        self.name: str = name
        self.record_type: str = record_type
        self.ttl: int = ttl
        self.rrdatas: List[str] = list(rrdatas)
        self.zone = zone
        return

    def to_body(self) -> Dict[str, Any]:
        """
            Render this record set for the API.

            :returns: The wire body.
        """
        rtnval = {"name": self.name, "type": self.record_type,
                  "ttl": self.ttl, "rrdatas": list(self.rrdatas)}
        return rtnval


class Changes:
    """
        A staged set of DNS additions and deletions.

        Nothing reaches the API until :meth:`create` is called, so a
        replacement is one atomic change rather than a delete followed by an
        add.
    """

    def __init__(self, *, zone: Any) -> None:
        """
            Construct a Changes.

            :param zone: The zone the change applies to.
        """
        self._zone = zone
        self._additions: List[ResourceRecordSet] = []
        self._deletions: List[ResourceRecordSet] = []
        return

    @property
    def additions(self) -> List[ResourceRecordSet]:
        """
            Return the staged additions.

            :returns: The record sets to add.
        """
        rtnval = list(self._additions)
        return rtnval

    @property
    def deletions(self) -> List[ResourceRecordSet]:
        """
            Return the staged deletions.

            :returns: The record sets to delete.
        """
        rtnval = list(self._deletions)
        return rtnval

    def add_record_set(self, record_set: ResourceRecordSet) -> None:
        """
            Stage a record set for addition.

            :param record_set: The record set to add.

            :returns: ``None``
        """
        self._additions.append(record_set)
        return

    def delete_record_set(self, record_set: ResourceRecordSet) -> None:
        """
            Stage a record set for deletion.

            :param record_set: The record set to delete.

            :returns: ``None``
        """
        self._deletions.append(record_set)
        return

    def create(self) -> Any:
        """
            Apply the staged change.

            An empty change is not sent; the API rejects it, and a caller that
            found nothing to replace has nothing to do.

            :returns: The created change resource, or None when nothing was
                staged.
        """
        if len(self._additions) == 0 and len(self._deletions) == 0:
            rtnval: Any = None
            return rtnval

        body: Dict[str, Any] = {
            "additions": [entry.to_body() for entry in self._additions],
            "deletions": [entry.to_body() for entry in self._deletions],
        }

        rtnval = self._zone.submit_change(body=body)
        return rtnval


class Zone:
    """
        One Cloud DNS managed zone.
    """

    def __init__(self, *, client: Any, name: str) -> None:
        """
            Construct a Zone.

            :param client: The owning :class:`DnsClient`.
            :param name: The managed-zone name.
        """
        self._client = client
        self.name: str = name
        return

    def resource_record_set(self, name: str, record_type: str, ttl: int,
                            rrdatas: List[str]) -> ResourceRecordSet:
        """
            Build a record set bound to this zone.

            Positional, matching the SDK and the venue's call site.

            :param name: The record name.
            :param record_type: The record type.
            :param ttl: The time to live in seconds.
            :param rrdatas: The record values.

            :returns: The record set.
        """
        rtnval = ResourceRecordSet(name=name, record_type=record_type,
                                   ttl=ttl, rrdatas=rrdatas, zone=self)
        return rtnval

    def changes(self) -> Changes:
        """
            Start a new change for this zone.

            :returns: An empty :class:`Changes`.
        """
        rtnval = Changes(zone=self)
        return rtnval

    def list_resource_record_sets(self) -> List[ResourceRecordSet]:
        """
            List every record set in this zone.

            :returns: The record sets.
        """
        rtnval = self._client.list_record_sets(zone_name=self.name,
                                               zone=self)
        return rtnval

    def submit_change(self, *, body: Dict[str, Any]) -> Any:
        """
            Post a change to this zone.

            :param body: The change body.

            :returns: The created change resource.
        """
        rtnval = self._client.create_change(zone_name=self.name, body=body)
        return rtnval


class DnsClient:
    """
        Client for the Cloud DNS API.
    """

    def __init__(self, *, transport: Any, project: str,
                 endpoint: str = DNS_ENDPOINT) -> None:
        """
            Construct a DnsClient.

            :param transport: The shared :class:`GoogleTransport`.
            :param project: The project the zones belong to.
            :param endpoint: The DNS API endpoint.
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

    def zone(self, name: str, dns_name: Optional[str] = None) -> Zone:
        """
            Return a handle on a managed zone.

            No request is made; the SDK's ``zone()`` is a constructor, and the
            venue immediately uses it to build record sets.

            :param name: The managed-zone name.
            :param dns_name: Accepted for signature compatibility.

            :returns: The zone handle.
        """
        rtnval = Zone(client=self, name=name)
        return rtnval

    def list_record_sets(self, *, zone_name: str,
                         zone: Any = None) -> List[ResourceRecordSet]:
        """
            List a zone's record sets, across every page.

            :param zone_name: The managed-zone name.
            :param zone: The owning zone handle.

            :returns: The record sets.
        """
        collected: List[ResourceRecordSet] = []
        params: Dict[str, Any] = {}

        url = "{}/projects/{}/managedZones/{}/rrsets".format(
            self._endpoint, self._project, zone_name)

        while True:
            payload = self._transport.request(method="GET", url=url,
                                              params=params)

            for entry in payload.get("rrsets", None) or []:
                collected.append(ResourceRecordSet(
                    name=str(entry.get("name", "")),
                    record_type=str(entry.get("type", "")),
                    ttl=int(entry.get("ttl", 0) or 0),
                    rrdatas=list(entry.get("rrdatas", []) or []),
                    zone=zone))

            token = payload.get("nextPageToken", None)
            if token is None or len(str(token)) == 0:
                break
            params["pageToken"] = token

        rtnval = collected
        return rtnval

    def create_change(self, *, zone_name: str,
                      body: Dict[str, Any]) -> Any:
        """
            Post a change to a zone.

            :param zone_name: The managed-zone name.
            :param body: The change body.

            :returns: The created change resource.
        """
        url = "{}/projects/{}/managedZones/{}/changes".format(
            self._endpoint, self._project, zone_name)

        rtnval = self._transport.request(method="POST", url=url, body=body)
        return rtnval
