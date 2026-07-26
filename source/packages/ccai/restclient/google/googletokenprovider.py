"""
    .. module:: googletokenprovider
    :platform: Darwin, Linux, Unix, Windows
    :synopsis: Access-token acquisition for the Google Cloud APIs.

    Two credential kinds are supported:

    * a service-account key, which self-signs a JWT asserting who it is and
      what scopes it wants, then exchanges that assertion for an access token
      at Google's OAuth2 endpoint;
    * workload identity, which asks the instance metadata service for a token
      the platform issues to the machine itself.

    The JWT is signed RS256, which is the one place in this fleet's clients
    that needs real asymmetric cryptography — hence the ``cryptography``
    dependency here and nowhere else in the REST clients except the Oracle
    one.

    Tokens are cached until shortly before they expire.  The early refresh
    matters: a token that passes the expiry check and then expires in flight
    fails the request it was fetched for, mid-apply.

    .. moduleauthor:: Myron Walker <myron.walker@gmail.com>
"""

__author__ = "Myron Walker"
__copyright__ = "Copyright 2026, Code Craft AI LLC"
__credits__ = []


import base64
import json
import os
import time

from typing import Any, Dict, List, Optional

import requests

from ccai.restclient.google.googleapierror import GoogleAuthError


GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# The metadata server is a link-local address that only answers requests
# carrying the Metadata-Flavor header.
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# A self-signed assertion is short-lived by design; Google caps it at an hour.
ASSERTION_LIFETIME_SECONDS = 3600

DEFAULT_TIMEOUT_SECONDS = 30.0

EXPIRY_SKEW_SECONDS = 300.0


def base64url(data: bytes) -> str:
    """
        Base64url-encode without padding, as JWT requires.

        :param data: The bytes to encode.

        :returns: The encoded string.
    """
    rtnval = base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
    return rtnval


class GoogleTokenProvider:
    """
        Acquires and caches Google Cloud access tokens.
    """

    def __init__(self, *, client_email: Optional[str] = None,
                 private_key: Optional[str] = None,
                 private_key_id: Optional[str] = None,
                 token_uri: str = GOOGLE_TOKEN_URI,
                 scopes: Optional[List[str]] = None,
                 use_metadata_server: bool = False,
                 metadata_url: str = METADATA_TOKEN_URL,
                 session: Optional[Any] = None,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        """
            Construct a GoogleTokenProvider.

            :param client_email: The service account's address, which becomes
                the assertion's issuer.
            :param private_key: The service account's PEM private key.
            :param private_key_id: The key id, carried in the JWT header so
                Google can select the right public key.
            :param token_uri: The OAuth2 token endpoint, which is also the
                assertion's audience.
            :param scopes: The scopes to request.
            :param use_metadata_server: Ask the metadata server instead of
                signing an assertion.
            :param metadata_url: The metadata token URL.
            :param session: Optional pre-built ``requests.Session`` — the test
                seam.
            :param timeout_seconds: The per-request timeout.

            :raises: :class:`GoogleAuthError` when the supplied material
                cannot identify a caller.
        """
        self._client_email = client_email
        self._private_key = private_key
        self._private_key_id = private_key_id
        self._token_uri = token_uri
        self._use_metadata_server = use_metadata_server
        self._metadata_url = metadata_url
        self._timeout_seconds = timeout_seconds

        if scopes is not None and len(scopes) > 0:
            self._scopes = list(scopes)
        else:
            self._scopes = [CLOUD_PLATFORM_SCOPE]

        self._token: Optional[str] = None
        self._expires_at: float = 0.0

        if use_metadata_server is False:
            missing = []
            if client_email is None or len(client_email) == 0:
                missing.append("client_email")
            if private_key is None or len(private_key) == 0:
                missing.append("private_key")
            if len(missing) > 0:
                err_msg_lines = [
                    "A service-account token needs the full key material."
                ]
                err_msg_lines.append("MISSING: {}".format(", ".join(missing)))
                err_msg_lines.append(
                    "Pass use_metadata_server=True to use workload identity "
                    "instead.")
                err_msg = os.linesep.join(err_msg_lines)
                raise GoogleAuthError(err_msg)

        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
        return

    @property
    def client_email(self) -> Optional[str]:
        """
            Return the service account address.

            :returns: The address, or None under workload identity.
        """
        rtnval = self._client_email
        return rtnval

    @property
    def scopes(self) -> List[str]:
        """
            Return the requested scopes.

            :returns: The scopes.
        """
        rtnval = list(self._scopes)
        return rtnval

    def build_assertion(self, *, issued_at: int) -> str:
        """
            Build and sign the JWT assertion.

            :param issued_at: The issue time, as a UNIX timestamp.  Passed in
                rather than read here so the assertion is reproducible in
                tests.

            :returns: The signed JWT.

            :raises: :class:`GoogleAuthError` when the key cannot be loaded.
        """
        header: Dict[str, Any] = {"alg": "RS256", "typ": "JWT"}
        if self._private_key_id is not None:
            header["kid"] = self._private_key_id

        claims: Dict[str, Any] = {
            "iss": self._client_email,
            "scope": " ".join(self._scopes),
            "aud": self._token_uri,
            "iat": issued_at,
            "exp": issued_at + ASSERTION_LIFETIME_SECONDS,
        }

        segments = [
            base64url(json.dumps(header, separators=(",", ":")).encode(
                "utf-8")),
            base64url(json.dumps(claims, separators=(",", ":")).encode(
                "utf-8")),
        ]
        signing_input = ".".join(segments).encode("ascii")

        signature = self._sign(payload=signing_input)

        rtnval = "{}.{}".format(".".join(segments), base64url(signature))
        return rtnval

    def _sign(self, *, payload: bytes) -> bytes:
        """
            Sign the assertion with the service account's RSA key.

            :param payload: The signing input.

            :returns: The raw signature.

            :raises: :class:`GoogleAuthError` when the key cannot be loaded
                or is not an RSA key.
        """
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        key_text = self._private_key
        if key_text is None:
            err_msg = "No private key is available to sign the assertion."
            raise GoogleAuthError(err_msg)

        # Service-account JSON stores the PEM with literal \n sequences when
        # it has been round-tripped through an environment variable.
        material = key_text.replace("\\n", "\n").encode("utf-8")

        try:
            private_key = serialization.load_pem_private_key(material,
                                                             password=None)
        except Exception as xcpt:
            err_msg_lines = [
                "The service-account private key could not be loaded."
            ]
            err_msg_lines.append("CAUSE: {}".format(xcpt))
            err_msg = os.linesep.join(err_msg_lines)
            raise GoogleAuthError(err_msg) from None

        if isinstance(private_key, rsa.RSAPrivateKey) is False:
            err_msg_lines = [
                "The service-account key must be an RSA key; Google signs "
                "assertions RS256."
            ]
            err_msg_lines.append("ACTUAL: {}".format(
                type(private_key).__name__))
            err_msg = os.linesep.join(err_msg_lines)
            raise GoogleAuthError(err_msg)

        rtnval = private_key.sign(payload, padding.PKCS1v15(),
                                  hashes.SHA256())
        return rtnval

    def token(self, *, now: Optional[float] = None) -> str:
        """
            Return a valid access token, fetching one when needed.

            :param now: Optional current time, for tests.

            :returns: The bearer token.
        """
        moment = now
        if moment is None:
            moment = time.time()

        if self._token is not None and moment < self._expires_at:
            rtnval = self._token
            return rtnval

        if self._use_metadata_server is True:
            payload = self._fetch_metadata_token()
        else:
            payload = self._fetch_assertion_token(issued_at=int(moment))

        token = payload.get("access_token", None)
        if token is None or len(str(token)) == 0:
            err_msg = "The token response carried no access_token."
            raise GoogleAuthError(err_msg)

        expires_in = payload.get("expires_in", 3600)
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 3600.0

        usable = lifetime - EXPIRY_SKEW_SECONDS
        if usable <= 0:
            usable = lifetime / 2.0

        self._token = str(token)
        self._expires_at = moment + usable

        rtnval = self._token
        return rtnval

    def _fetch_assertion_token(self, *, issued_at: int) -> Dict[str, Any]:
        """
            Exchange a signed assertion for an access token.

            :param issued_at: The assertion issue time.

            :returns: The decoded token response.
        """
        assertion = self.build_assertion(issued_at=issued_at)

        form = {"grant_type": JWT_BEARER_GRANT, "assertion": assertion}

        response = self._session.request(
            "POST", self._token_uri, data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self._timeout_seconds)

        rtnval = self._decode(response=response, what="service account")
        return rtnval

    def _fetch_metadata_token(self) -> Dict[str, Any]:
        """
            Ask the metadata server for an access token.

            :returns: The decoded token response.
        """
        response = self._session.request(
            "GET", self._metadata_url,
            headers={"Metadata-Flavor": "Google"},
            timeout=self._timeout_seconds)

        rtnval = self._decode(response=response, what="workload identity")
        return rtnval

    def _decode(self, *, response: Any, what: str) -> Dict[str, Any]:
        """
            Validate and decode a token response.

            :param response: The HTTP response.
            :param what: Which credential kind was used, for the message.

            :returns: The decoded body.

            :raises: :class:`GoogleAuthError` on failure.
        """
        status = getattr(response, "status_code", 0)
        text = getattr(response, "text", "")

        if status < 200 or status >= 300:
            description = text
            try:
                decoded = response.json()
                if isinstance(decoded, dict) is True:
                    described = decoded.get("error_description", None)
                    if described is None:
                        described = decoded.get("error", None)
                    if described is not None:
                        description = str(described)
            except Exception:
                description = text

            err_msg_lines = [
                "Could not obtain a Google access token ({}).".format(what)
            ]
            err_msg_lines.append("STATUS: {}".format(status))
            err_msg_lines.append("DETAIL: {}".format(description))
            err_msg = os.linesep.join(err_msg_lines)
            raise GoogleAuthError(err_msg, status=status, body=text)

        try:
            decoded = response.json()
        except Exception:
            err_msg = "The Google token response was not JSON."
            raise GoogleAuthError(err_msg, status=status,
                                  body=text) from None

        if isinstance(decoded, dict) is False:
            err_msg = "The Google token response was not an object."
            raise GoogleAuthError(err_msg, status=status, body=text)

        rtnval = decoded
        return rtnval
