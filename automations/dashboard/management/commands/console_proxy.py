"""Relay a project server's console from Proxmox to the browser.

    python manage.py console_proxy --port 8010

Proxmox serves a VM's serial console over a websocket that needs Sentinel's
API token, which must never reach a browser. So the browser connects here
instead, with a console pass Sentinel signed a moment earlier for one server
and one administrator (see project_servers.api_project_server_console). This
process checks the pass, opens the console on Proxmox with the token, and then
passes the terminal's bytes both ways untouched.

A pass lasts 60 seconds and works once. Only VMs Sentinel made are reachable.

  CONSOLE_PROXY_PORT        8010
  CONSOLE_ALLOWED_ORIGINS   pages allowed to connect, comma separated
                            (default http://localhost:3000)
"""
import asyncio
import logging
import os
import ssl
from urllib.parse import parse_qs, urlparse

from asgiref.sync import sync_to_async
from django.core import signing
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from dashboard import proxmox
from dashboard.project_servers import CONSOLE_PASS_AGE, CONSOLE_SALT

logger = logging.getLogger(__name__)
_spent = set()   # passes already used; a pass is good for one connection


def _open_console(server_id):
    """Start a console on one of Sentinel's own VMs (see proxmox.open_terminal)."""
    from dashboard.models import ProjectServer
    close_old_connections()
    try:
        return proxmox.open_terminal(ProjectServer.objects.get(id=server_id))
    finally:
        close_old_connections()


def _tls(verify):
    ctx = ssl.create_default_context()
    if not verify:
        # Same rule as the REST calls: PROXMOX_VERIFY_SSL=false while the host
        # has its own self-signed certificate (reached over NetBird).
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def relay(browser):
    query = parse_qs(urlparse(browser.request.path).query)
    try:
        grant = signing.loads((query.get("pass") or [""])[0], salt=CONSOLE_SALT,
                              max_age=CONSOLE_PASS_AGE)
    except signing.BadSignature:
        await browser.close(4001, "The console pass is invalid or has expired.")
        return
    if grant["n"] in _spent:
        await browser.close(4001, "That console pass was already used.")
        return
    _spent.add(grant["n"])

    try:
        term = await sync_to_async(_open_console, thread_sensitive=False)(grant["s"])
    except Exception as e:  # noqa: BLE001 - the reason is shown in the browser
        await browser.close(4002, str(e)[:120])
        return

    vmid = term["vmid"]
    try:
        async with connect(term["url"], additional_headers={"Cookie": term["cookie"]},
                           subprotocols=["binary"], max_size=None, open_timeout=15,
                           ssl=_tls(term["verify"]) if term["url"].startswith("wss://") else None) as pve:
            await pve.send(term["auth_line"])
            first = await pve.recv()
            if (first if isinstance(first, str) else first.decode("utf-8", "replace")).strip() != "OK":
                await browser.close(4003, "Proxmox refused the console.")
                return
            logger.info("Console opened on VM %s for user %s", vmid, grant["u"])

            async def up():
                async for msg in browser:
                    await pve.send(msg)

            async def down():
                async for msg in pve:
                    await browser.send(msg)

            tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
    except Exception as e:  # noqa: BLE001
        logger.warning("Console relay for VM %s ended: %s", vmid, e)
    finally:
        await browser.close()


class Command(BaseCommand):
    help = "Relay project server consoles from Proxmox to the browser."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=int(os.getenv("CONSOLE_PROXY_PORT", "8010")))

    def handle(self, *args, **o):
        origins = [x.strip() for x in os.getenv(
            "CONSOLE_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if x.strip()]

        async def main():
            async with serve(relay, o["host"], o["port"], origins=origins, max_size=None):
                self.stdout.write(f"Console relay listening on ws://{o['host']}:{o['port']} "
                                  f"for {', '.join(origins)}")
                await asyncio.Future()

        asyncio.run(main())
