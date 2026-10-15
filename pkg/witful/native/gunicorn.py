"""
Configure the owned production WSGI runtime from the same closed native settings contract.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Flask

from witful.native.api.admission import Admission
from witful.native.config import load

if TYPE_CHECKING:
    from collections.abc import Callable

# This module is loaded only by the explicit native controller serve command.
settings = load(Path(os.environ["WITFUL_NATIVE_CONFIG"]))
bind = f"{settings.runtime.host}:{settings.runtime.port}"
workers = settings.runtime.workers
# Ordinary admission cannot consume recovery slots or the additional operational thread.
threads = settings.runtime.threads + settings.runtime.recovery_admission + 1
worker_class = "gthread"
worker_connections = settings.runtime.worker_connections
backlog = settings.runtime.backlog
timeout = settings.runtime.timeout
graceful_timeout = settings.runtime.graceful_timeout
keepalive = settings.runtime.keepalive
preload_app = False
certfile = settings.tls.certificate
keyfile = settings.tls.key
ca_certs = settings.tls.ca
cert_reqs = ssl.CERT_REQUIRED
accesslog = None
errorlog = "-"
loglevel = "warning"
capture_output = False
forwarded_allow_ips = ""
worker_tmp_dir = settings.runtime.working_directory


def ssl_context(configuration: object, default_ssl_context_factory: Callable[[], ssl.SSLContext]) -> ssl.SSLContext:
    """
    Require TLS 1.3 and a verified client certificate on every connection, including operational probes.

    Args:
        configuration (object): Gunicorn-owned configuration supplied by its hook interface.
        default_ssl_context_factory (Callable[[], ssl.SSLContext]): Maintained certificate-loading implementation.

    Returns:
        ssl.SSLContext: Strict server-side mutual TLS context.
    """
    context = default_ssl_context_factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def worker_exit(server: object, worker: object) -> None:
    """
    Close application admission when the maintained runtime finishes draining a worker.

    Args:
        server (object): Runtime master supplied by Gunicorn.
        worker (object): Runtime worker; application loading may have failed before its WSGI attribute exists.

    Returns:
        None: Repeated lifecycle notifications remain safe.
    """
    # Boot failure also invokes this hook; preserve the original failure without assuming application initialization succeeded.
    application = getattr(worker, "wsgi", None)
    if isinstance(application, Flask):
        admission: object = application.extensions.get("witful.runtime")
        if isinstance(admission, Admission):
            admission.stop()
