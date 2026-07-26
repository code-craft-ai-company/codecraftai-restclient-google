"""
    .. module:: googleobject
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: :class:`ProtoObject` — Google Cloud JSON presented with the
               protobuf semantics the ``google-cloud-*`` clients had.

    The Compute REST API returns camelCase JSON and OMITS unset fields, while
    the generated protobuf clients returned messages whose unset fields read
    as TYPED ZERO VALUES — ``0``, ``""``, ``False``, ``[]``, ``{}`` — never
    ``None``.  Consumer code depends on that distinction:

    .. code:: python

        network_id = str(existing.id) if existing.id != 0 else gcp_name
        link = existing.self_link if len(existing.self_link) > 0 else fallback

    Returning ``None`` for an absent field would make ``str(None)`` the
    resource id and crash ``len()``.  So this module is deliberately the
    OPPOSITE of the ``None``-for-absent convention the other clients in this
    fleet use — it matches what its consumers already rely on.

    Field types cannot be inferred from omitted JSON, so the non-string types
    are named explicitly below.  That list is small because it only has to
    cover the fields consumers actually read; anything unnamed defaults to the
    string zero value, which is the most common case and the one whose misuse
    fails loudly (via ``len``) rather than silently.

    Wire names are matched by normalising both sides — removing underscores
    and lowercasing — so ``self_link`` finds ``selfLink`` and ``size_gb``
    finds ``sizeGb`` without a camelCase converter that would mangle them.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


from typing import Any, Dict, List


# Fields the API models as integers.  The REST encoding delivers 64-bit ids as
# JSON STRINGS, so these are also coerced back to int on the way out — a
# consumer comparing `existing.id != 0` must not be handed "0".
INT_FIELDS = (
    "id", "size_gb", "disk_size_gb", "boot_disk_size_gb", "ttl",
    "port", "priority", "count", "node_count",
)

BOOL_FIELDS = (
    "auto_create_subnetworks", "can_ip_forward", "preemptible",
    "versioning_enabled", "deletion_protection", "auto_delete",
)

# Repeated fields default to an empty list.
REPEATED_FIELDS = (
    "network_interfaces", "network_endpoints", "items", "rrdatas",
    "disks", "service_accounts", "target_tags", "source_ranges",
    "guest_accelerators", "allowed", "access_configs",
)

# Map fields default to an empty dict and are iterated as dicts.
MAP_FIELDS = ("labels", "annotations")


def normalize_name(name: str) -> str:
    """
        Reduce a field name to a spelling-insensitive form.

        :param name: The field name.

        :returns: The normalised name.
    """
    rtnval = name.replace("_", "").lower()
    return rtnval


_INT_NORMALIZED = tuple(normalize_name(entry) for entry in INT_FIELDS)
_BOOL_NORMALIZED = tuple(normalize_name(entry) for entry in BOOL_FIELDS)
_REPEATED_NORMALIZED = tuple(
    normalize_name(entry) for entry in REPEATED_FIELDS)
_MAP_NORMALIZED = tuple(normalize_name(entry) for entry in MAP_FIELDS)


def zero_value_for(name: str) -> Any:
    """
        Return the protobuf zero value for a field name.

        :param name: The field name, in either spelling.

        :returns: ``0``, ``False``, ``[]``, ``{}`` or ``""``.
    """
    wanted = normalize_name(name)

    if wanted in _INT_NORMALIZED:
        rtnval: Any = 0
        return rtnval
    if wanted in _BOOL_NORMALIZED:
        rtnval = False
        return rtnval
    if wanted in _REPEATED_NORMALIZED:
        rtnval = []
        return rtnval
    if wanted in _MAP_NORMALIZED:
        rtnval = {}
        return rtnval

    rtnval = ""
    return rtnval


def coerce_value(name: str, value: Any) -> Any:
    """
        Coerce a decoded JSON value to the type its field is modelled as.

        :param name: The field name.
        :param value: The decoded value.

        :returns: The coerced value.
    """
    wanted = normalize_name(name)

    if wanted in _INT_NORMALIZED:
        try:
            rtnval: Any = int(value)
        except (TypeError, ValueError):
            rtnval = 0
        return rtnval

    if wanted in _MAP_NORMALIZED:
        # Map fields stay plain dicts; protobuf maps are iterated as dicts and
        # wrapping them would break `for key in resource.labels`.
        if isinstance(value, dict) is True:
            rtnval = value
            return rtnval
        rtnval = {}
        return rtnval

    rtnval = wrap_value(value)
    return rtnval


def wrap_value(value: Any) -> Any:
    """
        Wrap a decoded JSON value so nested messages stay attribute
        addressable.

        :param value: The decoded value.

        :returns: A :class:`ProtoObject` for dicts, a list of wrapped values
            for lists, or the value unchanged.
    """
    if isinstance(value, ProtoObject) is True:
        rtnval = value
        return rtnval
    if isinstance(value, dict) is True:
        rtnval = ProtoObject(value)
        return rtnval
    if isinstance(value, list) is True:
        rtnval = [wrap_value(item) for item in value]
        return rtnval
    rtnval = value
    return rtnval


class ProtoObject(dict):
    """
        A ``dict`` of Google Cloud JSON presented as a protobuf message.

        Attribute lookup accepts either spelling and answers an unset field
        with its typed zero value rather than ``None``.
    """

    def __getattr__(self, name: str) -> Any:
        """
            Resolve a field by attribute access.

            :param name: The field name, in either spelling.

            :returns: The field value, or its typed zero value when unset.
        """
        if name.startswith("_") is True:
            # Never resolve private/dunder lookups as API fields; that would
            # make copy/pickle/inspect machinery see phantom attributes.
            raise AttributeError(name)

        if dict.__contains__(self, name) is True:
            rtnval = coerce_value(name, dict.__getitem__(self, name))
            return rtnval

        wanted = normalize_name(name)
        for key in dict.keys(self):
            if normalize_name(key) == wanted:
                rtnval = coerce_value(name, dict.__getitem__(self, key))
                return rtnval

        rtnval = zero_value_for(name)
        return rtnval

    def __setattr__(self, name: str, value: Any) -> None:
        """
            Set a field by attribute assignment.

            :param name: The field name.
            :param value: The value to store.

            :returns: ``None``
        """
        if name.startswith("_") is True:
            object.__setattr__(self, name, value)
            return
        self[name] = value
        return

    def as_dict(self) -> Dict[str, Any]:
        """
            Return the underlying plain dictionary.

            :returns: The wire-shaped dictionary.
        """
        rtnval = {key: dict.__getitem__(self, key)
                  for key in dict.keys(self)}
        return rtnval


def wrap_many(entries: Any) -> List[ProtoObject]:
    """
        Wrap a list of decoded resources.

        :param entries: The decoded entries, or None.

        :returns: The wrapped entries, empty when there were none.
    """
    if entries is None:
        rtnval: List[ProtoObject] = []
        return rtnval

    rtnval = [wrap_value(entry) for entry in entries]
    return rtnval
