"""
    .. module:: test_googleclient
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: Tests for the Google Cloud clients.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import base64
import json

from typing import Any, Dict, List, Optional

from ccai import testbase

from ccai.restclient.google.computeclient import ComputeClient
from ccai.restclient.google.dnsclient import DnsClient
from ccai.restclient.google.googleapierror import (
    GoogleApiError, GoogleAuthError, GoogleOperationError,
    GoogleOperationTimeout, NotFound
)
from ccai.restclient.google.googleobject import (
    ProtoObject, normalize_name, zero_value_for
)
from ccai.restclient.google.googletokenprovider import (
    GoogleTokenProvider, base64url
)
from ccai.restclient.google.googletransport import GoogleTransport
from ccai.restclient.google.storageclient import Bucket, StorageClient
from ccai.restclient.google.tpuclient import TpuClient


PROJECT = "proj-a"


class FakeResponse:
    """
        Minimal stand-in for a ``requests.Response``.
    """

    def __init__(self, *, status_code: int = 200,
                 payload: Optional[Any] = None, text: Optional[str] = None,
                 reason: str = "OK") -> None:
        self.status_code = status_code
        self.reason = reason
        if text is not None:
            self.text = text
        elif payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = ""
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    """
        Records requests and replays queued responses.
    """

    def __init__(self) -> None:
        self.headers: Dict[str, str] = {}
        self.calls: List[Dict[str, Any]] = []
        self.responses: Dict[str, List[FakeResponse]] = {}
        self.default_response = FakeResponse(payload={})

    def queue(self, *, method: str, match: str,
              response: FakeResponse) -> None:
        key = "{} {}".format(method.upper(), match)
        self.responses.setdefault(key, []).append(response)
        return

    def request(self, method: str, url: str, params=None, data=None,
                headers=None, timeout=None) -> FakeResponse:
        body = None
        if data is not None:
            if isinstance(data, dict) is True:
                body = data
            else:
                body = json.loads(data)

        self.calls.append({"method": method, "url": url,
                           "params": params or {}, "body": body,
                           "headers": headers or {}})

        for key, queued in self.responses.items():
            wanted_method, _, wanted = key.partition(" ")
            if method.upper() == wanted_method and wanted in url:
                if len(queued) > 0:
                    rtnval = queued.pop(0)
                    return rtnval

        rtnval = self.default_response
        return rtnval


class StubTokenProvider:
    """
        A token provider that never performs I/O.
    """

    def token(self, **kwargs: Any) -> str:
        return "stub-token"


def _transport(session=None):
    if session is None:
        session = FakeSession()
    built = GoogleTransport(token_provider=StubTokenProvider(),
                            session=session)
    return built, session


# ----------------------------------------------------------------------
# ProtoObject — the zero-value contract
# ----------------------------------------------------------------------

def test_absent_int_field_is_zero_not_none():
    obj = ProtoObject({"name": "net-a"})

    # `str(existing.id) if existing.id != 0 else fallback` must take the
    # fallback branch; None would make str(None) the resource id.
    assert obj.id == 0
    return


def test_absent_string_field_is_empty_not_none():
    obj = ProtoObject({"name": "net-a"})

    # `len(existing.self_link) > 0` must not crash.
    assert obj.self_link == ""
    assert len(obj.self_link) == 0
    return


def test_absent_bool_repeated_and_map_fields_have_typed_zeros():
    obj = ProtoObject({"name": "net-a"})

    assert obj.auto_create_subnetworks is False
    assert obj.network_interfaces == []
    assert obj.labels == {}
    return


def test_wire_names_are_matched_across_spellings():
    obj = ProtoObject({"selfLink": "https://x/net-a", "sizeGb": "100",
                       "ipCidrRange": "10.0.0.0/24"})

    assert obj.self_link == "https://x/net-a"
    assert obj.size_gb == 100
    assert obj.ip_cidr_range == "10.0.0.0/24"
    return


def test_ids_are_coerced_from_the_json_string_encoding():
    obj = ProtoObject({"id": "1234567890"})

    # 64-bit ids arrive as JSON strings; a consumer comparing against 0 must
    # not be handed "1234567890" as a str.
    assert obj.id == 1234567890
    assert isinstance(obj.id, int) is True
    return


def test_labels_stay_a_plain_dict():
    obj = ProtoObject({"labels": {"owner": "ccai", "run": "abc"}})

    # protobuf maps are iterated as dicts; wrapping them breaks `for key in`.
    assert isinstance(obj.labels, dict) is True
    assert sorted(obj.labels) == ["owner", "run"]
    return


def test_nested_messages_stay_attribute_addressable():
    obj = ProtoObject({"networkInterfaces": [
        {"networkIP": "10.0.0.5", "accessConfigs": [{"natIP": "1.2.3.4"}]}]})

    first = obj.network_interfaces[0]
    assert first.network_ip == "10.0.0.5"
    assert first.access_configs[0].nat_ip == "1.2.3.4"
    return


def test_private_lookups_are_refused():
    obj = ProtoObject({"name": "x"})

    with testbase.raises(AttributeError):
        getattr(obj, "_ipython_canary")
    return


def test_zero_value_helper_classifies_by_name():
    assert zero_value_for("id") == 0
    assert zero_value_for("auto_create_subnetworks") is False
    assert zero_value_for("network_interfaces") == []
    assert zero_value_for("labels") == {}
    assert zero_value_for("anything_else") == ""
    return


def test_normalize_name_is_spelling_insensitive():
    assert normalize_name("self_link") == normalize_name("selfLink")
    assert normalize_name("size_gb") == normalize_name("sizeGb")
    return


# ----------------------------------------------------------------------
# token provider
# ----------------------------------------------------------------------

def _generate_key():
    """
        Generate an RSA key pair for signature tests.

        :returns: A ``(pem, public_key)`` pair.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537,
                                           key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()).decode("ascii")
    return pem, private_key.public_key()


def test_assertion_signature_verifies_against_the_public_key():
    """
        The JWT must actually verify — this is the one place doing real
        asymmetric crypto, so a self-consistent-but-wrong signature would be
        invisible until Google rejected it.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    pem, public_key = _generate_key()
    provider = GoogleTokenProvider(client_email="svc@example.iam",
                                   private_key=pem,
                                   private_key_id="key-1",
                                   session=FakeSession())

    assertion = provider.build_assertion(issued_at=1700000000)

    header_b64, claims_b64, signature_b64 = assertion.split(".")
    signing_input = "{}.{}".format(header_b64, claims_b64).encode("ascii")

    padding_len = "=" * (-len(signature_b64) % 4)
    signature = base64.urlsafe_b64decode(signature_b64 + padding_len)

    # Raises InvalidSignature if the signing input or algorithm is wrong.
    public_key.verify(signature, signing_input, padding.PKCS1v15(),
                      hashes.SHA256())
    return


def test_assertion_header_and_claims_are_well_formed():
    pem, _ = _generate_key()
    provider = GoogleTokenProvider(client_email="svc@example.iam",
                                   private_key=pem, private_key_id="key-1",
                                   session=FakeSession())

    assertion = provider.build_assertion(issued_at=1700000000)
    header_b64, claims_b64, _ = assertion.split(".")

    def _decode(segment):
        return json.loads(base64.urlsafe_b64decode(
            segment + "=" * (-len(segment) % 4)))

    header = _decode(header_b64)
    claims = _decode(claims_b64)

    assert header["alg"] == "RS256"
    assert header["kid"] == "key-1"
    assert claims["iss"] == "svc@example.iam"
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["iat"] == 1700000000
    assert claims["exp"] == 1700000000 + 3600
    assert "cloud-platform" in claims["scope"]
    return


def test_base64url_is_unpadded():
    assert base64url(b"a") == "YQ"
    assert "=" not in base64url(b"abcd")
    return


def test_token_exchange_posts_the_jwt_bearer_grant():
    pem, _ = _generate_key()
    session = FakeSession()
    session.queue(method="POST", match="oauth2.googleapis.com",
                  response=FakeResponse(payload={"access_token": "tok-1",
                                                 "expires_in": 3600}))
    provider = GoogleTokenProvider(client_email="svc@example.iam",
                                   private_key=pem, session=session)

    assert provider.token(now=1700000000.0) == "tok-1"
    body = session.calls[0]["body"]
    assert body["grant_type"] == \
        "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert len(body["assertion"].split(".")) == 3
    return


def test_token_is_cached_then_refreshed_early():
    pem, _ = _generate_key()
    session = FakeSession()
    for token in ("tok-1", "tok-2"):
        session.queue(method="POST", match="oauth2.googleapis.com",
                      response=FakeResponse(payload={"access_token": token,
                                                     "expires_in": 3600}))
    provider = GoogleTokenProvider(client_email="svc@example.iam",
                                   private_key=pem, session=session)

    provider.token(now=1000.0)
    provider.token(now=1500.0)
    assert len(session.calls) == 1

    # 3600s lifetime less the 300s skew expires the cache at 4300.
    assert provider.token(now=4400.0) == "tok-2"
    return


def test_metadata_server_is_used_for_workload_identity():
    session = FakeSession()
    session.queue(method="GET", match="metadata.google.internal",
                  response=FakeResponse(payload={"access_token": "md-tok",
                                                 "expires_in": 3600}))
    provider = GoogleTokenProvider(use_metadata_server=True, session=session)

    assert provider.token(now=0.0) == "md-tok"
    assert session.calls[0]["headers"]["Metadata-Flavor"] == "Google"
    return


def test_incomplete_service_account_is_refused():
    with testbase.raises(GoogleAuthError):
        GoogleTokenProvider(client_email="svc@example.iam",
                            session=FakeSession())
    return


def test_unusable_private_key_is_reported():
    provider = GoogleTokenProvider(client_email="svc@example.iam",
                                   private_key="-----BEGIN PRIVATE KEY-----\n"
                                               "not a key\n"
                                               "-----END PRIVATE KEY-----\n",
                                   session=FakeSession())

    with testbase.raises(GoogleAuthError):
        provider.build_assertion(issued_at=1700000000)
    return


# ----------------------------------------------------------------------
# transport
# ----------------------------------------------------------------------

def test_transport_sends_the_bearer_token():
    transport, session = _transport()

    transport.request(method="GET", url="https://compute.googleapis.com/x")

    assert session.calls[0]["headers"]["Authorization"] == "Bearer stub-token"
    return


def test_404_raises_not_found():
    transport, session = _transport()
    session.queue(method="GET", match="/x",
                  response=FakeResponse(
                      status_code=404, reason="Not Found",
                      payload={"error": {"code": 404,
                                         "message": "not found"}}))

    with testbase.raises(NotFound) as caught:
        transport.request(method="GET", url="https://host/x")

    # Consumer code catches this name to mean "absent".
    assert caught.value.reason == "not found"
    return


def test_other_failures_raise_the_general_error():
    transport, session = _transport()
    session.queue(method="GET", match="/x",
                  response=FakeResponse(
                      status_code=403, reason="Forbidden",
                      payload={"error": {"message": "denied"}}))

    with testbase.raises(GoogleApiError) as caught:
        transport.request(method="GET", url="https://host/x")

    assert isinstance(caught.value, NotFound) is False
    return


# ----------------------------------------------------------------------
# compute
# ----------------------------------------------------------------------

def _compute(session=None):
    transport, session = _transport(session)
    client = ComputeClient(transport=transport, poll_interval=0.0)
    return client, client.sub_clients(), session


def test_global_regional_and_zonal_paths():
    client, subs, session = _compute()

    subs["networks"].get(project=PROJECT, network="net-a")
    subs["subnetworks"].get(project=PROJECT, region="us-east1",
                            subnetwork="sub-a")
    subs["instances"].get(project=PROJECT, zone="us-east1-b",
                          instance="vm-a")

    assert session.calls[0]["url"].endswith(
        "/projects/proj-a/global/networks/net-a")
    assert session.calls[1]["url"].endswith(
        "/projects/proj-a/regions/us-east1/subnetworks/sub-a")
    assert session.calls[2]["url"].endswith(
        "/projects/proj-a/zones/us-east1-b/instances/vm-a")
    return


def test_insert_returns_an_operation_not_the_resource():
    session = FakeSession()
    session.queue(method="POST", match="/networks",
                  response=FakeResponse(payload={"name": "operation-1",
                                                 "status": "DONE"}))
    client, subs, session = _compute(session)

    operation = subs["networks"].insert(project=PROJECT,
                                        network_resource={"name": "net-a"})

    # The venue waits on this before reading the resource back; without the
    # wait the follow-up get races the create and 404s.
    assert operation.done() is True
    assert operation.result(5).name == "operation-1"
    return


def test_operation_polls_until_done():
    session = FakeSession()
    session.queue(method="POST", match="/networks",
                  response=FakeResponse(payload={"name": "operation-2",
                                                 "status": "RUNNING"}))
    session.queue(method="GET", match="/global/operations/operation-2",
                  response=FakeResponse(payload={"name": "operation-2",
                                                 "status": "RUNNING"}))
    session.queue(method="GET", match="/global/operations/operation-2",
                  response=FakeResponse(payload={"name": "operation-2",
                                                 "status": "DONE"}))
    client, subs, session = _compute(session)

    operation = subs["networks"].insert(project=PROJECT,
                                        network_resource={"name": "net-a"})
    operation.result(60)

    assert session.calls[-1]["url"].endswith(
        "/projects/proj-a/global/operations/operation-2")
    return


def test_done_operation_carrying_an_error_raises():
    session = FakeSession()
    session.queue(method="POST", match="/instances",
                  response=FakeResponse(payload={
                      "name": "operation-3", "status": "DONE",
                      "error": {"errors": [{"code": "QUOTA_EXCEEDED",
                                            "message": "no capacity"}]}}))
    client, subs, session = _compute(session)

    operation = subs["instances"].insert(
        project=PROJECT, zone="us-east1-b",
        instance_resource={"name": "vm-a"})

    # A DONE operation is not necessarily a successful one — Compute reports
    # failures in the body with a 200 on the poll.
    with testbase.raises(GoogleOperationError) as caught:
        operation.result(5)

    assert "QUOTA_EXCEEDED" in str(caught.value)
    return


def test_operation_timeout_is_distinct_from_failure():
    session = FakeSession()
    session.queue(method="POST", match="/networks",
                  response=FakeResponse(payload={"name": "operation-4",
                                                 "status": "RUNNING"}))
    for _ in range(6):
        session.queue(method="GET", match="/operations/operation-4",
                      response=FakeResponse(payload={"name": "operation-4",
                                                     "status": "RUNNING"}))
    client, subs, session = _compute(session)

    operation = subs["networks"].insert(project=PROJECT,
                                        network_resource={"name": "net-a"})

    with testbase.raises(GoogleOperationTimeout) as caught:
        operation.result(0)

    assert isinstance(caught.value, GoogleOperationError) is False
    return


def test_zonal_operations_poll_at_their_zone():
    session = FakeSession()
    session.queue(method="POST", match="/instances",
                  response=FakeResponse(payload={"name": "operation-5",
                                                 "status": "RUNNING"}))
    session.queue(method="GET", match="/zones/us-east1-b/operations",
                  response=FakeResponse(payload={"name": "operation-5",
                                                 "status": "DONE"}))
    client, subs, session = _compute(session)

    operation = subs["instances"].insert(
        project=PROJECT, zone="us-east1-b",
        instance_resource={"name": "vm-a"})
    operation.result(60)

    assert session.calls[-1]["url"].endswith(
        "/projects/proj-a/zones/us-east1-b/operations/operation-5")
    return


def test_list_walks_every_page():
    session = FakeSession()
    session.queue(method="GET", match="/networks",
                  response=FakeResponse(payload={
                      "items": [{"name": "a"}], "nextPageToken": "t1"}))
    session.queue(method="GET", match="/networks",
                  response=FakeResponse(payload={"items": [{"name": "b"}]}))
    client, subs, session = _compute(session)

    found = subs["networks"].list(project=PROJECT)

    # A truncated listing under-reports owned resources, which on a teardown
    # path means leaked infrastructure.
    assert [entry.name for entry in found] == ["a", "b"]
    assert session.calls[1]["params"]["pageToken"] == "t1"
    return


# ----------------------------------------------------------------------
# storage
# ----------------------------------------------------------------------

def _storage(session=None):
    transport, session = _transport(session)
    client = StorageClient(transport=transport, project=PROJECT)
    return client, session


def test_lookup_bucket_answers_none_when_absent():
    session = FakeSession()
    session.queue(method="GET", match="/b/missing",
                  response=FakeResponse(status_code=404, reason="Not Found",
                                        payload={"error": {"message": "no"}}))
    client, session = _storage(session)

    # Absence is the normal case when deciding whether to create.
    assert client.lookup_bucket("missing") is None
    return


def test_create_bucket_takes_the_bucket_object():
    session = FakeSession()
    session.queue(method="POST", match="/b",
                  response=FakeResponse(payload={"name": "bkt-a",
                                                 "location": "US-EAST1",
                                                 "labels": {"owner": "ccai"}}))
    client, session = _storage(session)

    bucket = Bucket(client=client, name="bkt-a")
    bucket.labels = {"owner": "ccai"}
    bucket.versioning_enabled = True

    created = client.create_bucket(bucket, location="us-east1")

    body = session.calls[0]["body"]
    assert body["name"] == "bkt-a"
    assert body["labels"] == {"owner": "ccai"}
    assert body["versioning"] == {"enabled": True}
    assert body["location"] == "us-east1"
    assert session.calls[0]["params"]["project"] == PROJECT
    assert created.location == "US-EAST1"
    return


def test_list_buckets_filters_by_prefix():
    session = FakeSession()
    session.queue(method="GET", match="/b",
                  response=FakeResponse(payload={
                      "items": [{"name": "ccai-abc-one"}]}))
    client, session = _storage(session)

    found = client.list_buckets(prefix="ccai-abc-")

    assert [entry.name for entry in found] == ["ccai-abc-one"]
    assert session.calls[0]["params"]["prefix"] == "ccai-abc-"
    return


def test_bucket_delete_force_empties_the_bucket_first():
    session = FakeSession()
    session.queue(method="GET", match="/b/bkt-a/o",
                  response=FakeResponse(payload={
                      "items": [{"name": "dir/obj-1"}]}))
    client, session = _storage(session)

    bucket = Bucket(client=client, name="bkt-a")
    bucket.delete(force=True)

    methods = [(call["method"], call["url"]) for call in session.calls]
    # The API refuses to delete a non-empty bucket, so a teardown without this
    # would fail on any bucket that was ever written to.
    assert methods[1][0] == "DELETE"
    assert methods[1][1].endswith("/b/bkt-a/o/dir%2Fobj-1")
    assert methods[2][0] == "DELETE"
    assert methods[2][1].endswith("/b/bkt-a")
    return


def test_bucket_delete_without_force_does_not_list_objects():
    client, session = _storage()

    Bucket(client=client, name="bkt-a").delete()

    assert len(session.calls) == 1
    assert session.calls[0]["method"] == "DELETE"
    return


# ----------------------------------------------------------------------
# dns
# ----------------------------------------------------------------------

def _dns(session=None):
    transport, session = _transport(session)
    client = DnsClient(transport=transport, project=PROJECT)
    return client, session


def test_replacing_a_record_is_one_atomic_change():
    session = FakeSession()
    session.queue(method="GET", match="/rrsets",
                  response=FakeResponse(payload={"rrsets": [
                      {"name": "srv-a.example.com.", "type": "A",
                       "ttl": 300, "rrdatas": ["1.1.1.1"]}]}))
    client, session = _dns(session)

    zone = client.zone("example-zone")
    new_record = zone.resource_record_set("srv-a.example.com.", "A", 300,
                                          ["2.2.2.2"])
    changes = zone.changes()
    for record in zone.list_resource_record_sets():
        if record.name == "srv-a.example.com." and record.record_type == "A":
            changes.delete_record_set(record)
    changes.add_record_set(new_record)
    changes.create()

    posts = [call for call in session.calls if call["method"] == "POST"]
    # One POST carrying both halves: splitting it would leave the zone
    # briefly without the record.
    assert len(posts) == 1
    body = posts[0]["body"]
    assert body["additions"][0]["rrdatas"] == ["2.2.2.2"]
    assert body["deletions"][0]["rrdatas"] == ["1.1.1.1"]
    return


def test_empty_change_is_not_sent():
    client, session = _dns()

    result = client.zone("example-zone").changes().create()

    # The API rejects an empty change, and a caller that found nothing to
    # replace has nothing to do.
    assert result is None
    assert len(session.calls) == 0
    return


def test_zone_handle_makes_no_request():
    client, session = _dns()

    client.zone("example-zone")

    assert len(session.calls) == 0
    return


def test_record_sets_carry_type_as_record_type():
    session = FakeSession()
    session.queue(method="GET", match="/rrsets",
                  response=FakeResponse(payload={"rrsets": [
                      {"name": "a.example.com.", "type": "CNAME",
                       "ttl": 60, "rrdatas": ["b.example.com."]}]}))
    client, session = _dns(session)

    records = client.zone("z").list_resource_record_sets()

    # The wire field is `type`; consumers read `record_type`.
    assert records[0].record_type == "CNAME"
    assert records[0].ttl == 60
    return


# ----------------------------------------------------------------------
# tpu
# ----------------------------------------------------------------------

def test_tpu_node_paths_and_operation():
    session = FakeSession()
    session.queue(method="POST", match="/nodes",
                  response=FakeResponse(payload={"name": "op-1",
                                                 "done": True,
                                                 "response": {"name": "n1"}}))
    transport, session = _transport(session)
    client = TpuClient(transport=transport, poll_interval=0.0)

    operation = client.create_node(
        parent="projects/proj-a/locations/us-east1-b", node_id="tpu-a",
        node={"acceleratorType": "v5p-8"})
    result = operation.result(5)

    assert session.calls[0]["params"]["nodeId"] == "tpu-a"
    assert session.calls[0]["url"].endswith(
        "/projects/proj-a/locations/us-east1-b/nodes")
    assert result.name == "n1"
    return


def test_tpu_list_nodes_walks_pages():
    session = FakeSession()
    session.queue(method="GET", match="/nodes",
                  response=FakeResponse(payload={
                      "nodes": [{"name": "n1"}], "nextPageToken": "t"}))
    session.queue(method="GET", match="/nodes",
                  response=FakeResponse(payload={"nodes": [{"name": "n2"}]}))
    transport, session = _transport(session)
    client = TpuClient(transport=transport, poll_interval=0.0)

    found = client.list_nodes(parent="projects/proj-a/locations/us-east1-b")

    assert [entry.name for entry in found] == ["n1", "n2"]
    return
