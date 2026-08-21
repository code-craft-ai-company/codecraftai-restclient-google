# Requirements

## Introduction

The `google-client` feature provides a pure-Python client for the Google Cloud
APIs, replacing the `google-auth`, `google-api-core` and `google-cloud-*`
packages the provisioning venue previously depended on. Google publishes a
separate API per product rather than one control plane, so the package is
organised the same way: `ComputeClient` (networks, subnetworks, firewalls,
instances, disks, resource policies, images), `StorageClient` (buckets and
objects), `DnsClient` (managed zones and record sets), and `TpuClient` (Cloud
TPU v2 nodes).

All four are JSON over HTTPS with a bearer token, so a single
`GoogleTransport` and a single `GoogleTokenProvider` serve them. The package
lives at `source/packages/ccai/restclient/google` and its runtime
dependencies are `requests` and `cryptography` — it does not import
`RestClientBase`, and it does not accept a typed credential object. Both are
recorded as open items in `tasks.md`.

The distinguishing constraint is the response model. Consumer code was
written against generated protobuf clients, whose unset fields read as typed
zero values, so `ProtoObject` deliberately answers an absent field with `0`,
`""`, `False`, `[]` or `{}` — never `None`.

---

## Requirements

### Requirement 1: Present Responses With Protobuf Zero-Value Semantics

**User Story:** As a venue that was written against `google-cloud-*` generated
clients, I want an unset field to read as its typed zero value so that
existing `existing.id != 0` and `len(existing.self_link) > 0` guards keep
working unchanged.

#### Acceptance Criteria

1. WHEN a field named in `INT_FIELDS` is absent THE SYSTEM SHALL return `0`;
   for `BOOL_FIELDS`, `False`; for `REPEATED_FIELDS`, `[]`; for `MAP_FIELDS`,
   `{}`; for every other name, `""`.
2. WHEN a field is read under either spelling THE SYSTEM SHALL resolve it by
   normalising both sides through `normalize_name` — removing underscores and
   lowercasing — so `self_link` finds `selfLink` and `size_gb` finds `sizeGb`.
3. WHEN an integer field arrives as a JSON string, as 64-bit ids do, THE
   SYSTEM SHALL coerce it back to `int`; an uncoercible value SHALL become
   `0` rather than raising.
4. WHEN a nested object or list is read THE SYSTEM SHALL wrap it so nested
   messages stay attribute-addressable, EXCEPT for `MAP_FIELDS`, which SHALL
   remain plain dicts so `for key in resource.labels` keeps working.
5. WHEN an attribute name begins with `_` THE SYSTEM SHALL raise
   `AttributeError` rather than resolve it as an API field, so copy, pickle
   and inspection machinery does not observe phantom attributes.

### Requirement 2: Acquire Access Tokens From Either Credential Kind

**User Story:** As an operator, I want the client to authenticate from either
a service-account key or workload identity so that the same code runs on a
workstation and on a GCE instance.

#### Acceptance Criteria

1. WHEN constructed with `client_email` and `private_key` THE SYSTEM SHALL
   build an RS256-signed JWT asserting the issuer, requested scopes, and
   `token_uri` as audience, with a lifetime of `ASSERTION_LIFETIME_SECONDS`,
   and SHALL exchange it at the token endpoint under the
   `urn:ietf:params:oauth:grant-type:jwt-bearer` grant.
2. WHEN constructed with `use_metadata_server=True` THE SYSTEM SHALL GET the
   metadata token URL carrying the `Metadata-Flavor: Google` header instead of
   signing an assertion.
3. WHEN neither `use_metadata_server` nor complete service-account material is
   supplied THE SYSTEM SHALL raise `GoogleAuthError` naming the missing
   fields, at construction time, before any request is issued.
4. WHEN the private key cannot be loaded, or is not an RSA key, THE SYSTEM
   SHALL raise `GoogleAuthError` identifying the cause. PEM material carrying
   literal `\n` sequences SHALL be accepted, because service-account JSON
   round-tripped through an environment variable stores it that way.
5. WHEN no scopes are supplied THE SYSTEM SHALL request
   `https://www.googleapis.com/auth/cloud-platform`.
6. THE SYSTEM SHALL cache the token and SHALL refresh it
   `EXPIRY_SKEW_SECONDS` before its stated expiry, so a token that passes the
   expiry check cannot expire in flight.
7. WHEN the token response is missing `access_token`, is not JSON, or is not
   an object THE SYSTEM SHALL raise `GoogleAuthError` carrying the status and
   the body.

### Requirement 3: Perform Authenticated JSON Requests

**User Story:** As a client author, I want one transport shared by all four
product clients so that authentication, error mapping and body decoding are
written once.

#### Acceptance Criteria

1. THE SYSTEM SHALL send `Authorization: Bearer <token>` and
   `Accept: application/json` on every request, and SHALL add
   `Content-Type: application/json` only when a body is present.
2. THE SYSTEM SHALL drop query parameters whose value is `None` rather than
   send them.
3. WHEN the response status is 404 THE SYSTEM SHALL raise `NotFound`; for any
   other non-2xx status THE SYSTEM SHALL raise `GoogleApiError`. Both SHALL
   carry `status`, `reason` and `body`, and the message SHALL name the method,
   URL, status and reason.
4. WHEN a failure body carries `{"error": {"message": ...}}` THE SYSTEM SHALL
   use that message as the reason in preference to the HTTP reason phrase.
5. WHEN a success response has an empty or undecodable body THE SYSTEM SHALL
   return an empty `ProtoObject` rather than raise.
6. WHEN a success body decodes to something other than an object THE SYSTEM
   SHALL return it wrapped as `ProtoObject({"items": ...})`.
7. THE SYSTEM SHALL accept an injected session object, which is the seam the
   tests use, and SHALL otherwise build its own `requests.Session`.

### Requirement 4: Cover the Compute Engine v1 Surface

**User Story:** As a provisioner, I want per-resource-type Compute sub-clients
keyed the way the venue's session factory keyed them so that the venue's dict
of sub-clients continues to resolve.

#### Acceptance Criteria

1. THE SYSTEM SHALL expose `sub_clients()` returning clients under the keys
   `networks`, `subnetworks`, `firewalls`, `instances`, `disks`,
   `resource_policies` and `images`.
2. EACH sub-client SHALL expose `get`, `list`, `insert` and `delete` taking
   keyword arguments, naming the resource by the type's key parameter
   (`network`, `subnetwork`, `firewall`, `instance`, `disk`,
   `resource_policy`, `image`).
3. THE SYSTEM SHALL compose the collection path at the type's scope:
   `/projects/{p}/global/...` for global types, `/projects/{p}/regions/{r}/...`
   for regional types, and `/projects/{p}/zones/{z}/...` for zonal types.
4. WHEN `insert` is called THE SYSTEM SHALL take the request body from the
   keyword argument whose name ends in `_resource`, matching how the generated
   clients named it.
5. WHEN `list` is called THE SYSTEM SHALL walk every page via
   `pageToken`/`nextPageToken`, accumulating `items`, and SHALL return the
   concatenated result — a truncated listing under-reports owned resources,
   which on a teardown path means leaked infrastructure.

### Requirement 5: Wait On Long-Running Operations

**User Story:** As a provisioner, I want a mutation to answer with an
operation handle I can block on so that the follow-up read does not race the
create and 404.

#### Acceptance Criteria

1. WHEN `insert` or `delete` completes THE SYSTEM SHALL return a
   `ComputeOperation` rather than the finished resource.
2. WHEN `result(timeout)` is called THE SYSTEM SHALL poll the operation at the
   scope that produced it — global, regional or zonal — until its status is
   `DONE`.
3. WHEN a `DONE` operation carries an `error` member THE SYSTEM SHALL raise
   `GoogleOperationError` listing the reported error codes and messages,
   because Compute reports failures in the operation body with a 200 on the
   poll.
4. WHEN the operation has not finished inside the timeout THE SYSTEM SHALL
   raise `GoogleOperationTimeout`, which SHALL NOT be a `GoogleOperationError`
   — the caller stopped waiting, Google did not stop working.
5. THE SYSTEM SHALL apply `DEFAULT_OPERATION_TIMEOUT_SECONDS` when no timeout
   is given.
6. `TpuOperation` SHALL provide the same `done()`/`result(timeout)` contract,
   reading terminality from the operation's `done` member and returning its
   wrapped `response` payload.

### Requirement 6: Manage Cloud Storage Buckets As Active Records

**User Story:** As a teardown path, I want to list buckets and delete each one
including its contents so that a bucket that was ever written to does not
block the teardown.

#### Acceptance Criteria

1. THE SYSTEM SHALL model a bucket as an object carrying `name`, `labels`,
   `location` and `versioning_enabled`, constructible by the caller before
   creation and returned by the client for existing buckets.
2. WHEN `lookup_bucket(name)` is called for an absent bucket THE SYSTEM SHALL
   return `None` rather than raise, because absence is the normal case when
   deciding whether to create. `get_bucket(name)` SHALL raise `NotFound`.
3. WHEN `create_bucket(bucket, location)` is called THE SYSTEM SHALL accept
   the bucket positionally as an object, SHALL send `labels` and
   `versioning` only when set, and SHALL pass the client's project as a query
   parameter.
4. WHEN `list_buckets(prefix)` is called THE SYSTEM SHALL filter server-side
   by prefix and SHALL walk every page.
5. WHEN a bucket is deleted with `force=True` THE SYSTEM SHALL delete every
   object in the bucket first, walking every page of the object listing,
   because the API refuses to delete a non-empty bucket.
6. THE SYSTEM SHALL percent-encode object names with no safe characters, since
   object names routinely contain `/` which would otherwise address a
   different resource.

### Requirement 7: Apply Cloud DNS Edits As Atomic Changes

**User Story:** As a provisioner replacing a record, I want the delete and the
add applied in one change so that the zone is never briefly without the
record.

#### Acceptance Criteria

1. THE SYSTEM SHALL expose a zone handle whose construction performs no
   request, and on which record sets are built and changes are staged.
2. THE SYSTEM SHALL stage additions and deletions on a change object and SHALL
   send nothing until `create()` is called, at which point both halves SHALL
   go in a single POST.
3. WHEN `create()` is called with nothing staged THE SYSTEM SHALL return
   `None` without issuing a request, because the API rejects an empty change.
4. WHEN record sets are listed THE SYSTEM SHALL walk every page of `rrsets`
   and SHALL surface the wire field `type` as `record_type`.

### Requirement 8: Cover the Cloud TPU v2 Surface

**User Story:** As a provisioner placing accelerator workloads, I want TPU
nodes addressed by their full resource path so that the paths the venue passes
around are used unchanged.

#### Acceptance Criteria

1. THE SYSTEM SHALL expose `get_node(name)`, `delete_node(name)` and
   `get_operation(name)` taking a full resource path such as
   `projects/{p}/locations/{zone}/nodes/{id}`.
2. THE SYSTEM SHALL expose `create_node(parent, node_id, node)` posting to
   `{parent}/nodes` with `nodeId` as a query parameter, and returning a
   `TpuOperation`.
3. THE SYSTEM SHALL expose `list_nodes(parent)` walking every page and
   accumulating the `nodes` member.

### Requirement 9: Preserve the Absence-Signalling Exception Name

**User Story:** As a venue with a `resource_or_none` helper, I want the
absence exception to keep the name it catches so that the helper keeps
working.

#### Acceptance Criteria

1. THE SYSTEM SHALL name the 404 exception `NotFound`, matching
   `google.api_core.exceptions.NotFound`.
2. THE SYSTEM SHALL derive `NotFound`, `GoogleAuthError`,
   `GoogleOperationError` and `GoogleOperationTimeout` from `GoogleApiError`,
   so a caller may catch the base to mean "any Google failure".
