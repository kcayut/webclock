#!/usr/bin/env python3
"""Small JSON client for HA/agents/automation; credentials only come from the environment."""
import argparse
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

LIMIT = 2_000_000
ERRORS = {"authentication_required", "permission_denied", "not_found", "revision_conflict",
          "idempotency_conflict", "request_incomplete", "invalid_request", "storage_failure",
          "control_not_ready", "calendar_not_ready", "tls_required", "rate_limited", "capacity_reached", "source_id_conflict"}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or any(char.isspace() for char in value)):
        raise ValueError("invalid_server_url")
    parsed.port
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def build_request(args, environ, stream):
    token = environ.get("WEBCLOCK_WRITE_TOKEN", "")
    if not re.fullmatch(r"[\x21-\x7e]{1,512}", token):
        raise ValueError("missing_or_invalid_write_token")
    path = "/api/v1/control/" + args.resource
    read_only = args.resource in ("identity", "calendar-events")
    if read_only:
        if args.action != "list" or args.id or args.target_kind or args.target_id:
            raise ValueError("invalid_request")
        sources = getattr(args, "source_id", None)
        if args.resource == "calendar-events":
            if not sources or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in sources):
                raise ValueError("invalid_request")
            path += "?" + urlencode([("source_id", value) for value in sources])
        elif sources:
            raise ValueError("invalid_request")
    elif getattr(args, "source_id", None):
        raise ValueError("invalid_request")
    if not read_only and args.action in ("get", "update", "delete", "target", "assign"):
        if not args.id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.id):
            raise ValueError("invalid_id")
        path += "/" + args.id
    elif args.id:
        raise ValueError("unexpected_id")
    if args.action in ("target", "assign"):
        if (args.target_kind not in ("group", "device") or not args.target_id
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.target_id)):
            raise ValueError("invalid_target")
        path += "/targets/" + args.target_kind + "/" + args.target_id
    elif args.target_kind or args.target_id:
        raise ValueError("unexpected_target")
    method = {"list": "GET", "get": "GET", "target": "GET", "create": "POST",
              "update": "PATCH", "delete": "DELETE", "assign": "PUT"}[args.action]
    body = None
    if method != "GET":
        raw = stream.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError("request_too_large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid_request")
        field = "schedule" if args.resource == "schedules" else "event"
        allowed = {"create": {"request_id", field}, "update": {"revision", field},
                   "delete": {"revision"}, "assign": {"revision", "assigned"}}[args.action]
        if set(payload) != allowed:
            raise ValueError("invalid_request_fields")
        if method == "POST" and (not isinstance(payload["request_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", payload["request_id"])):
            raise ValueError("invalid_request")
        if method in ("PATCH", "DELETE", "PUT") and not re.fullmatch(r"[a-f0-9]{64}", str(payload["revision"])):
            raise ValueError("invalid_revision")
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
    return Request(origin(environ.get("WEBCLOCK_SERVER_URL", "")) + path, data=body, method=method,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                 "Content-Type": "application/json", "X-WebClock-Client": "native-v1"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource", choices=("schedules", "events", "identity", "calendar-events"))
    parser.add_argument("action", choices=("list", "get", "create", "update", "delete", "target", "assign"))
    parser.add_argument("id", nargs="?")
    parser.add_argument("--target-kind", choices=("group", "device"))
    parser.add_argument("--target-id")
    parser.add_argument("--source-id", action="append", help="Authorized calendar source ID; repeat for more than one")
    args = parser.parse_args(argv)
    status = 0
    try:
        request = build_request(args, os.environ, sys.stdin)
        try:
            response = build_opener(NoRedirects(), ProxyHandler({})).open(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT or response.headers.get_content_type() != "application/json":
                raise ValueError("invalid_response")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("invalid_response")
        if status not in (200, 201):
            code = data.get("code")
            raise ValueError(code if isinstance(code, str) and code in ERRORS else "request_failed")
        print(json.dumps(data, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, UnicodeError) as error:
        code = str(error)
        safe = ERRORS | {"invalid_response", "request_failed", "missing_or_invalid_write_token",
            "invalid_id", "unexpected_id", "invalid_target", "unexpected_target", "request_too_large",
            "invalid_request_fields", "invalid_revision", "invalid_server_url"}
        code = code if code in safe else "invalid_request"
    except (URLError, TimeoutError, OSError):
        code = "cannot_connect"
    print(json.dumps({"error": code, "status": status}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
