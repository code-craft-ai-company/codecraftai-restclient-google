# Implementation Plan — Google Client

## Package Skeleton

- [x] 1. Create `source/packages/ccai/restclient/google/` with the module-per-product layout.
- [x] 2. Add `requests` and `cryptography` as the runtime dependencies in `pyproject.toml`.

## Response Model

- [x] 3. Implement `ProtoObject` as a `dict` subclass answering absent fields with typed protobuf zero values.
- [x] 4. Enumerate the non-string field types in `INT_FIELDS`, `BOOL_FIELDS`, `REPEATED_FIELDS` and `MAP_FIELDS`.
- [x] 5. Implement `normalize_name` so field lookup matches either spelling without a camelCase converter.
- [x] 6. Implement `coerce_value` to recover `int` from the JSON-string encoding of 64-bit ids, and to leave map fields as plain dicts.
- [x] 7. Implement `wrap_value` / `wrap_many` so nested messages and lists stay attribute-addressable, and `as_dict` for the raw wire shape.
- [x] 8. Refuse underscore-prefixed attribute lookups so copy/pickle/inspect machinery sees no phantom attributes.

## Errors

- [x] 9. Implement `GoogleApiError` carrying `status`, `reason` and `body`.
- [x] 10. Implement `NotFound`, keeping the `google.api_core.exceptions` spelling consumer code catches to mean "absent".
- [x] 11. Implement `GoogleAuthError`, `GoogleOperationError` and `GoogleOperationTimeout` as siblings under `GoogleApiError`.

## Authentication

- [x] 12. Implement `GoogleTokenProvider` with a service-account path and a metadata-server path.
- [x] 13. Implement `build_assertion` with an injectable `issued_at` so the JWT is reproducible under test.
- [x] 14. Implement RS256 signing, rejecting unloadable and non-RSA keys, and accepting PEM with literal `\n` sequences.
- [x] 15. Validate credential completeness at construction and raise `GoogleAuthError` naming what is missing.
- [x] 16. Cache the token and refresh `EXPIRY_SKEW_SECONDS` early so it cannot expire in flight.

## Transport

- [x] 17. Implement `GoogleTransport.request` with bearer auth, `None`-parameter dropping and JSON body encoding.
- [x] 18. Map 404 to `NotFound` and other non-2xx to `GoogleApiError`, preferring the `error.message` body field as the reason.
- [x] 19. Return an empty `ProtoObject` for empty or undecodable success bodies; wrap non-object bodies under `items`.
- [x] 20. Accept an injected session as the test seam.

## Compute Engine

- [x] 21. Implement `_ResourceClient` deriving path, key parameter and operation scope from `COLLECTION` / `KEY_PARAM` / `SCOPE`.
- [x] 22. Implement the seven sub-clients and `ComputeClient.sub_clients()` keyed as the venue's session factory keyed them.
- [x] 23. Implement `insert` taking the body from the `*_resource` keyword argument.
- [x] 24. Implement `ComputeClient.paginate` walking `pageToken` / `nextPageToken` over `items`.
- [x] 25. Implement `ComputeOperation` with per-scope poll paths recorded at creation.
- [x] 26. Implement `result()` raising `GoogleOperationError` for a DONE-with-error operation and `GoogleOperationTimeout` on expiry.

## Cloud Storage

- [x] 27. Implement `Bucket` as an active record with `to_body()` and `delete(force=...)`.
- [x] 28. Implement `lookup_bucket` answering `None` on absence and `get_bucket` raising `NotFound`.
- [x] 29. Implement `create_bucket` taking the bucket object positionally and scoping to the client's project.
- [x] 30. Implement `list_buckets` with server-side prefix filtering and page walking.
- [x] 31. Implement force-delete emptying the bucket first, percent-encoding object names with no safe characters.

## Cloud DNS

- [x] 32. Implement `Zone` as a request-free handle, and `ResourceRecordSet` surfacing the wire `type` as `record_type`.
- [x] 33. Implement `Changes` staging additions and deletions into a single atomic POST, dropping an empty change client-side.
- [x] 34. Implement `list_record_sets` walking every page of `rrsets`.

## Cloud TPU

- [x] 35. Implement `get_node`, `create_node`, `delete_node`, `list_nodes` and `get_operation` against full resource paths.
- [x] 36. Implement `TpuOperation` reading terminality from the `done` member and returning the wrapped `response`.

## Tests

- [x] 37. Build `FakeSession`, `FakeResponse` and `StubTokenProvider` as the offline test harness.
- [x] 38. Cover the `ProtoObject` zero-value contract, spelling-insensitive lookup, id coercion and private-lookup refusal.
- [x] 39. Verify a built assertion against its own public key, plus header/claims shape and unpadded base64url.
- [x] 40. Cover token caching, early refresh, the metadata-server path and credential rejection.
- [x] 41. Cover 404-versus-other error mapping on the transport.
- [x] 42. Cover global/regional/zonal Compute paths, operation polling, DONE-with-error, timeout distinctness and page walking.
- [x] 43. Cover bucket lookup-on-absence, creation body, prefix listing and force-delete ordering.
- [x] 44. Cover the atomic DNS replacement, the dropped empty change and the request-free zone handle.
- [x] 45. Cover TPU node paths, operation result and node page walking.

## Open Items

- [ ] 46. Reconcile with `codecraftai-restclient-base`. `pyproject.toml` declares it alongside `codecraftai-credentials` and `codecraftai-errors`, but nothing under `source/packages` imports any of the three. Either build on `RestClientBase` or drop the unused dependencies.
- [ ] 47. Accept a typed credential object. `GoogleTokenProvider` takes `client_email` and `private_key` as raw strings, which the repository coding standard in `AGENTS.md` forbids on the API surface.
- [ ] 48. Add the `aspects` parameter. No method takes one, so retry, backoff, timeout and logging policy is not caller-controlled; `timeout_seconds` at construction and the per-call `timeout` on `result()` are the only levers.
- [ ] 49. No retry on transient HTTP failures. A single 500 or connection reset fails the call outright.
- [ ] 50. Add property-based tests using `ccai.testbase.properties`. All 39 tests are example-based; page-walking totality and URL/field-name composition are the natural candidates.
- [ ] 51. Add a gated live-API smoke test. Nothing currently exercises a real Google endpoint.
- [ ] 52. Remove the unused `wrap_value` import in `computeclient.py`.
