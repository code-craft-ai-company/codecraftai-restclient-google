# Design

## Overview

`codecraftai-restclient-google` is a pure-Python client for the Google Cloud
APIs. It exists to remove the `google-auth`, `google-api-core` and
`google-cloud-*` dependency chain from the provisioning venue while keeping
the call shapes and response semantics that venue code was written against.

Google has no single control plane, so there is no single client class.
Instead there are four product clients — `ComputeClient`, `StorageClient`,
`DnsClient`, `TpuClient` — sitting on one shared `GoogleTransport`, which in
turn sits on one shared `GoogleTokenProvider`. Everything below the product
clients is JSON over HTTPS with a bearer token, which is why the sharing
works.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  codecraftai-provisioning / venues / google              │
└───┬───────────┬───────────────┬──────────────┬───────────┘
    ▼           ▼               ▼              ▼
┌────────┐ ┌─────────┐  ┌──────────┐  ┌──────────┐
│Compute │ │ Storage │  │   Dns    │  │   Tpu    │
│ Client │ │ Client  │  │  Client  │  │  Client  │
└───┬────┘ └────┬────┘  └────┬─────┘  └────┬─────┘
    └───────────┴────────────┴─────────────┘
                       ▼
            ┌─────────────────────┐
            │  GoogleTransport    │  bearer auth, error
            │  (+ ProtoObject)    │  mapping, decoding
            └──────────┬──────────┘
                       ▼
            ┌─────────────────────┐
            │ GoogleTokenProvider │  RS256 assertion
            │                     │  or metadata server
            └─────────────────────┘
```

---

## Module Layout

```
source/packages/ccai/restclient/google/
├── __init__.py
├── googleobject.py          # ProtoObject and the zero-value rules
├── googleapierror.py        # GoogleApiError and its subclasses
├── googletokenprovider.py   # GoogleTokenProvider
├── googletransport.py       # GoogleTransport
├── computeclient.py         # ComputeClient, ComputeOperation, sub-clients
├── storageclient.py         # StorageClient, Bucket
├── dnsclient.py             # DnsClient, Zone, Changes, ResourceRecordSet
└── tpuclient.py             # TpuClient, TpuOperation
```

---

## Notable Choices

**`ProtoObject` inverts this fleet's absence convention on purpose.** Every
other client here answers an absent field with `None`. This one answers with
a typed zero — `0`, `""`, `False`, `[]`, `{}` — because its consumers were
written against generated protobuf messages and guard on
`existing.id != 0` and `len(existing.self_link) > 0`. Returning `None` would
make `str(None)` the resource id and crash `len()`. Since JSON omission
carries no type information, the non-string types are enumerated in
`INT_FIELDS`, `BOOL_FIELDS`, `REPEATED_FIELDS` and `MAP_FIELDS`; anything
unlisted defaults to the string zero, which is both the common case and the
one whose misuse fails loudly through `len()` rather than silently.
`ProtoObject` subclasses `dict`, so `.get()`, `dict(obj)` and iteration all
still behave, and `as_dict()` hands back the raw wire shape.

**Field lookup is spelling-insensitive rather than camelCase-converting.**
`normalize_name` strips underscores and lowercases both the requested name and
each wire key. A camelCase converter would have to be right about every field;
normalising both sides cannot mismatch `size_gb` against `sizeGb`.

**One transport, four endpoint constants.** `GoogleTransport.request` takes an
absolute URL, and each product client composes its own from its endpoint
constant (`COMPUTE_ENDPOINT`, `STORAGE_ENDPOINT`, `DNS_ENDPOINT`,
`TPU_ENDPOINT`). `ComputeClient` additionally exposes a path-relative
`request()` and a `paginate()` helper, because Compute's sub-clients all build
paths against one endpoint.

**Compute sub-clients are table-driven.** `_ResourceClient` carries three class
attributes — `COLLECTION`, `KEY_PARAM`, `SCOPE` — and derives path composition,
key-parameter extraction and operation scoping from them. Adding a resource
type is a three-line subclass; `NetworksClient`, `SubnetworksClient`,
`FirewallsClient`, `InstancesClient`, `DisksClient`, `ResourcePoliciesClient`
and `ImagesClient` are all exactly that.

**Operation scope is captured at creation, not rediscovered.** A Compute
operation must be polled at the same scope as the resource that produced it.
`build_operation` records the scope and the zone or region name at the moment
the mutation returns, so `ComputeOperation._poll_path` never has to parse the
operation's `selfLink` to work out where to look.

**A DONE operation is not a successful one.** Compute reports failures inside
the operation body with a 200 on the poll, so `result()` calls
`_raise_for_error` after the wait rather than trusting the status alone. A
timeout raises `GoogleOperationTimeout`, a sibling of `GoogleOperationError`
rather than a subclass, because the two mean different things to a caller
deciding whether to clean up: a timeout leaves work possibly still running.

**Storage is active record; Compute is not.** `Bucket` holds a back-reference
to its client and exposes `delete(force=...)`, and `create_bucket` takes a
bucket object positionally. That is the `google-cloud-storage` shape and the
venue's call sites depend on it. `force` empties the bucket first because the
API refuses to delete a non-empty bucket, which would otherwise fail teardown
on any bucket ever written to.

**DNS edits are changes, not writes.** `Changes` stages additions and
deletions and sends nothing until `create()`, so replacing a record set is one
atomic POST. Splitting it would leave the zone briefly without the record.
An empty change is dropped client-side, since the API rejects it.

**Token refresh is early by `EXPIRY_SKEW_SECONDS`.** A token that passes the
expiry check and then expires in flight fails the request it was fetched for,
mid-apply. The skew makes that impossible for any request shorter than five
minutes. RS256 signing is the reason this package depends on `cryptography`
— it is the only asymmetric crypto in these clients apart from the Oracle one.

---

## Relationship to `codecraftai-restclient-base`

The package does not subclass `RestClientBase` and does not take an `aspects`
parameter, though `pyproject.toml` declares `codecraftai-restclient-base`,
`codecraftai-credentials` and `codecraftai-errors` as dependencies. Nothing
under `source/packages` imports any of the three. Credentials enter
`GoogleTokenProvider` as raw strings rather than as a typed credential object.
Both divergences are open items in `tasks.md`; they are recorded here so the
design is not read as claiming a base-class integration that does not exist.

---

## Testing Strategy

Tests live at
`source/testroots/testbase/ccai/tests/restclient/google/test_googleclient.py`
and run under the testbase runner, not pytest:

```
PYTHONPATH="$PWD/source/packages:$PWD/source/testroots/testbase" \
    .venv/bin/testbase testing run --root source/testroots/testbase/ccai \
    --includes="*" --output=./.output
```

The suite is example-based and offline. `FakeSession` records every call and
replays responses queued against a `METHOD substring` key; `FakeResponse`
stands in for `requests.Response`; `StubTokenProvider` keeps transport tests
from touching the token path. Injecting the session at the `GoogleTransport`
and `GoogleTokenProvider` constructors is the only seam needed — no HTTP
library patching.

Coverage concentrates on the contracts that are easy to regress silently:
the `ProtoObject` zero values and spelling-insensitive lookup; that a signed
assertion actually verifies against its public key, which a self-consistent
but wrong signature would otherwise hide until Google rejected it; token
caching and early refresh; 404-versus-other error mapping; per-scope Compute
path composition and operation polling; the DONE-with-error and timeout
branches; page walking for Compute, Storage, DNS and TPU; force-delete
emptying a bucket before removing it; and a record replacement arriving as one
POST.
