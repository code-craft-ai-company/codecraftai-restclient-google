==============================
codecraftai-restclient-google
==============================

A pure-Python client for the Google Cloud APIs, replacing ``google-auth``,
``google-api-core`` and the ``google-cloud-*`` packages the provisioning venue
used: Compute Engine, Cloud Storage, Cloud DNS and Cloud TPU.

One authenticated transport serves all four, since they are all JSON over HTTPS
with a bearer token.

Design notes
============

**Responses carry protobuf semantics, not JSON semantics.** The generated
clients returned messages whose unset fields read as TYPED ZERO VALUES — ``0``,
``""``, ``False``, ``[]``, ``{}`` — never ``None``, and consumer code depends
on it::

    network_id = str(existing.id) if existing.id != 0 else gcp_name
    link = existing.self_link if len(existing.self_link) > 0 else fallback

Returning ``None`` would make ``str(None)`` the resource id and crash
``len()``.  So ``ProtoObject`` is deliberately the OPPOSITE of the
``None``-for-absent convention the other clients in this fleet use.

Field types cannot be inferred from omitted JSON, so the non-string types are
named explicitly in ``googleobject``.  Anything unnamed defaults to the string
zero value — the most common case, and the one whose misuse fails loudly via
``len()`` rather than silently.

Wire names are matched by normalising both sides (removing underscores,
lowercasing), so ``self_link`` finds ``selfLink`` and ``size_gb`` finds
``sizeGb``.  64-bit ids arrive as JSON strings and are coerced back to int, so
``existing.id != 0`` is never handed ``"0"``.

**Mutations answer with an operation, not the resource.** The venue blocks on
``result()`` before reading the resource back — without that wait the follow-up
``get`` races the create and 404s.  A DONE operation is not necessarily a
successful one: Compute reports failures in the operation body with a 200 on
the poll, so ``result()`` inspects it.  A timeout raises a distinct type from a
failure, because the operation may still be running.

**DNS edits are changes, not writes.** Cloud DNS applies a set of additions and
deletions atomically.  Replacing a record set is one change containing both —
splitting it into two calls would leave the zone briefly without the record.

**Buckets are active record**, unlike Compute resources: the venue calls
``bucket.delete(force=True)`` on listed entries.  ``force`` deletes the
bucket's objects first, because the API refuses to delete a non-empty bucket
and a teardown would otherwise fail on any bucket ever written to.

**Authentication.** A service-account key self-signs an RS256 JWT and exchanges
it for an access token; workload identity asks the metadata server.  The RSA
signing is why this package depends on ``cryptography`` — it is the only
asymmetric crypto in these clients apart from the Oracle one.

``NotFound`` keeps its ``google.api_core.exceptions`` name, because consumer
code catches it to mean "absent".
