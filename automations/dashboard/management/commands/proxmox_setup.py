"""Set up the Proxmox host for project servers, entirely through its API.

    PROXMOX_ADMIN_USER=Ethan@pve PROXMOX_ADMIN_PASSWORD=... \\
        python manage.py proxmox_setup --write-env ../.env

Run once by an administrator. It logs in with an admin account (prompted for
if not in the environment, never stored) and adds, skipping anything already
there:

  1. The Ubuntu 26.04 LTS cloud image on `local` storage, checked against
     Ubuntu's published SHA-256.
  2. Template VM 9000 on RiadZ2_pool. It is booted once from a small seed disc
     that installs the QEMU guest agent (how Sentinel reads a server's
     address) and allows password logins over SSH; then cloud-init is reset so
     every clone starts fresh, and the VM becomes a template.
  3. A resource pool "sentinel" holding the template and every project server.
  4. A user sentinel@pve with a token that can manage VMs in that pool only,
     use the storage and network, and read the host's free memory. It cannot
     touch the VMs outside the pool.
  5. A password for that same user, used only to open server consoles:
     Proxmox's console service accepts a login ticket but not a token. The
     user's rights are the pool-only ones above, so it grants nothing more.

The token secret and console password go into the --write-env file and are
not printed. Run again later, it keeps the existing token and only renews
the console password.
Nothing existing on the host is modified or removed.
"""
import getpass
import io
import os
import secrets
import time
from pathlib import Path

import requests
import urllib3
from django.core.management.base import BaseCommand, CommandError

RELEASE = "https://cloud-images.ubuntu.com/releases/resolute/release"
IMAGE = "ubuntu-26.04-server-cloudimg-amd64.img"
IMPORT_NAME = "ubuntu-26.04-server-cloudimg-amd64.qcow2"
SEED_NAME = "sentinel-template-seed.iso"
TOKEN_USER, TOKEN_NAME = "sentinel@pve", "provisioning"

SEED_USER_DATA = """#cloud-config
# One boot only, to prepare the Sentinel template.
users: []
package_update: true
packages:
  - qemu-guest-agent
runcmd:
  - systemctl enable --now qemu-guest-agent
"""

# Run inside the template through the guest agent before it is frozen.
PREPARE = r"""
set -e
# The agent answers before first boot is over; let cloud-init finish first.
cloud-init status --wait >/dev/null || true
rm -f /etc/ssh/sshd_config.d/60-cloudimg-settings.conf
apt-get clean
cloud-init clean --logs --machine-id || { cloud-init clean --logs; truncate -s 0 /etc/machine-id; }
echo prepared
"""


class Api:
    def __init__(self, url, user, password, out):
        urllib3.disable_warnings()
        self.base = f"{url.rstrip('/')}/api2/json"
        self.out = out
        self.s = requests.Session()
        self.s.verify = False
        r = self.s.post(f"{self.base}/access/ticket",
                        data={"username": user, "password": password}, timeout=30)
        if not r.ok or not (r.json() or {}).get("data"):
            raise CommandError(f"Login as {user} failed ({r.status_code}).")
        d = r.json()["data"]
        self.s.cookies.set("PVEAuthCookie", d["ticket"])
        self.s.headers["CSRFPreventionToken"] = d["CSRFPreventionToken"]

    def call(self, method, endpoint, files=None, **data):
        # `endpoint`, not `path`: the ACL call sends a parameter named path.
        r = self.s.request(method, f"{self.base}{endpoint}", timeout=600, files=files,
                           params=data if method in ("GET", "DELETE") else None,
                           data=data if method in ("POST", "PUT") else None)
        if not r.ok:
            raise CommandError(f"{method} {endpoint} -> {r.status_code}: {r.text[:400]}")
        return (r.json() or {}).get("data")

    def call_json(self, method, path, body):
        r = self.s.request(method, f"{self.base}{path}", json=body, timeout=600)
        if not r.ok:
            raise CommandError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
        return (r.json() or {}).get("data")

    def wait(self, node, upid, what, timeout=3600):
        if not (isinstance(upid, str) and upid.startswith("UPID")):
            return
        from urllib.parse import quote
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.call("GET", f"/nodes/{node}/tasks/{quote(upid, safe='')}/status")
            if st.get("status") == "stopped":
                if st.get("exitstatus") != "OK":
                    raise CommandError(f"{what} failed: {st.get('exitstatus')}")
                return
            time.sleep(3)
        raise CommandError(f"{what} did not finish in time.")


def seed_iso():
    """A NoCloud seed disc: an ISO labelled "cidata" with user-data and meta-data."""
    import pycdlib
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")
    files = {"user-data": SEED_USER_DATA,
             "meta-data": "instance-id: sentinel-template-prep\nlocal-hostname: ubuntu-2604-template\n"}
    for name, text in files.items():
        data = text.encode()
        iso.add_fp(io.BytesIO(data), len(data), "/" + name.replace("-", "").upper() + ".;1",
                   rr_name=name, joliet_path="/" + name)
    out = io.BytesIO()
    iso.write_fp(out)
    iso.close()
    return out.getvalue()


def write_env(path, values):
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    keys = set(values)
    kept = [ln for ln in lines if ln.split("=", 1)[0].strip() not in keys]
    if kept and kept[-1].strip():
        kept.append("")
    kept.append("# Proxmox project servers (written by manage.py proxmox_setup)")
    kept += [f"{k}={v}" for k, v in values.items()]
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")


class Command(BaseCommand):
    help = "Prepare the Proxmox host for Sentinel project servers (template, pool, token)."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=os.getenv("PROXMOX_URL") or "https://100.108.29.54:8006")
        parser.add_argument("--template", type=int, default=9000)
        parser.add_argument("--storage", default="RiadZ2_pool")
        parser.add_argument("--bridge", default="vmbr0")
        parser.add_argument("--pool", default="sentinel")
        parser.add_argument("--write-env", help="Put the PROXMOX_* settings, token included, in this file.")

    def step(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"== {text}"))

    def handle(self, *args, **o):
        user = os.getenv("PROXMOX_ADMIN_USER") or input("Proxmox admin user (e.g. Ethan@pve): ")
        password = os.getenv("PROXMOX_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        api = Api(o["url"], user, password, self.stdout)
        node = api.call("GET", "/nodes")[0]["node"]
        tpl, storage, pool = o["template"], o["storage"], o["pool"]
        vmids = {int(v["vmid"]) for v in api.call("GET", "/cluster/resources", type="vm")}

        self.step(f"Pool '{pool}'")
        if pool not in [p["poolid"] for p in api.call("GET", "/pools")]:
            api.call("POST", "/pools", poolid=pool, comment="Sentinel project servers")
            self.stdout.write("created")
        else:
            self.stdout.write("already there")

        if tpl in vmids and api.call("GET", f"/nodes/{node}/qemu/{tpl}/config").get("template"):
            self.step(f"Template VM {tpl} already exists - leaving it as it is")
        else:
            # A VM 9000 that is not yet a template is one this command started
            # and did not finish; pick it up where it stopped.
            self.build_template(api, node, tpl, storage, o["bridge"], pool,
                                resume=tpl in vmids)

        self.step(f"API user {TOKEN_USER}")
        users = [u["userid"] for u in api.call("GET", "/access/users")]
        if TOKEN_USER not in users:
            api.call("POST", "/access/users", userid=TOKEN_USER, comment="Sentinel project servers")
        for path, role in ((f"/pool/{pool}", "PVEVMAdmin"),
                           (f"/storage/{storage}", "PVEDatastoreUser"),
                           ("/sdn/zones/localnetwork", "PVESDNUser"),
                           ("/nodes", "PVEAuditor")):
            api.call("PUT", "/access/acl", path=path, roles=role, users=TOKEN_USER)
        settings = {
            "PROXMOX_URL": o["url"],
            "PROXMOX_VERIFY_SSL": "false",
            "PROXMOX_NODE": node,
            "PROXMOX_TEMPLATE_VMID": str(tpl),
            "PROXMOX_STORAGE": storage,
            "PROXMOX_POOL": pool,
        }
        tokens = [t["tokenid"] for t in (api.call("GET", f"/access/users/{TOKEN_USER}/token") or [])]
        if TOKEN_NAME in tokens:
            # The secret cannot be read back, so the one already in .env stays.
            self.stdout.write(f"token {TOKEN_USER}!{TOKEN_NAME} already exists - keeping it")
        else:
            made = api.call("POST", f"/access/users/{TOKEN_USER}/token/{TOKEN_NAME}",
                            privsep=0, comment="Sentinel")
            settings["PROXMOX_TOKEN_ID"] = f"{TOKEN_USER}!{TOKEN_NAME}"
            settings["PROXMOX_TOKEN_SECRET"] = made["value"]

        self.step("Console password")
        console_pw = secrets.token_urlsafe(32)
        api.call("PUT", "/access/password", userid=TOKEN_USER, password=console_pw,
                 **{"confirmation-password": password})
        settings["PROXMOX_CONSOLE_USER"] = TOKEN_USER
        settings["PROXMOX_CONSOLE_PASSWORD"] = console_pw

        if o["write_env"]:
            write_env(o["write_env"], settings)
            self.stdout.write(self.style.SUCCESS(f"Settings written to {o['write_env']}."))
        else:
            self.stdout.write(self.style.WARNING("Add these to Sentinel's .env (shown once):"))
            for k, v in settings.items():
                self.stdout.write(f"{k}={v}")

    def build_template(self, api, node, tpl, storage, bridge, pool, resume=False):
        if resume:
            conf = api.call("GET", f"/nodes/{node}/qemu/{tpl}/config")
            if conf.get("name") != "ubuntu-2604-template":
                raise CommandError(f"VM {tpl} exists and is not Sentinel's template - choose another --template.")
            self.step(f"Resuming the unfinished template VM {tpl}")
            seed = f"local:iso/{SEED_NAME}"
            if api.call("GET", f"/nodes/{node}/qemu/{tpl}/status/current").get("status") != "running":
                api.wait(node, api.call("POST", f"/nodes/{node}/qemu/{tpl}/status/start"), "Start")
            return self.finish_template(api, node, tpl, storage, seed)

        self.step("Ubuntu 26.04 cloud image")
        have = [c["volid"] for c in api.call("GET", f"/nodes/{node}/storage/local/content", content="import")]
        volid = f"local:import/{IMPORT_NAME}"
        if volid in have:
            self.stdout.write("already downloaded")
        else:
            sums = requests.get(f"{RELEASE}/SHA256SUMS", timeout=30).text
            digest = next(ln.split()[0] for ln in sums.splitlines()
                          if ln.strip().endswith("*" + IMAGE))
            self.stdout.write(f"downloading {IMAGE} (sha256 {digest[:12]}…)")
            api.wait(node, api.call("POST", f"/nodes/{node}/storage/local/download-url",
                                    url=f"{RELEASE}/{IMAGE}", content="import",
                                    filename=IMPORT_NAME, checksum=digest,
                                    **{"checksum-algorithm": "sha256", "verify-certificates": 1}),
                     "Image download")

        self.step("Seed disc")
        isos = [c["volid"] for c in api.call("GET", f"/nodes/{node}/storage/local/content", content="iso")]
        seed = f"local:iso/{SEED_NAME}"
        if seed not in isos:
            api.wait(node, api.call("POST", f"/nodes/{node}/storage/local/upload",
                                    files={"filename": (SEED_NAME, seed_iso(), "application/octet-stream")},
                                    content="iso"), "Seed upload")

        self.step(f"Template VM {tpl}: create and first boot")
        api.wait(node, api.call(
            "POST", f"/nodes/{node}/qemu", vmid=tpl, name="ubuntu-2604-template", pool=pool,
            ostype="l26", memory=4096, cores=2, cpu="host",
            net0=f"virtio,bridge={bridge}", scsihw="virtio-scsi-single",
            agent="enabled=1", serial0="socket", vga="serial0",
            scsi0=f"{storage}:0,import-from={volid},discard=on",
            ide2=f"{seed},media=cdrom", boot="order=scsi0"), "Template create")
        api.wait(node, api.call("POST", f"/nodes/{node}/qemu/{tpl}/status/start"), "Start")
        self.finish_template(api, node, tpl, storage, seed)

    def finish_template(self, api, node, tpl, storage, seed):
        self.stdout.write("waiting for the guest agent to install (a few minutes)…")
        deadline = time.monotonic() + 1200
        while True:
            try:
                api.call("POST", f"/nodes/{node}/qemu/{tpl}/agent/ping")
                break
            except CommandError:
                if time.monotonic() > deadline:
                    raise CommandError("The guest agent never came up. Check the VM's console - "
                                       "it needs internet access to install packages.")
                time.sleep(10)

        self.step("Preparing it to be copied")
        pid = api.call_json("POST", f"/nodes/{node}/qemu/{tpl}/agent/exec",
                            {"command": ["bash", "-c", PREPARE]})["pid"]
        for _ in range(450):
            st = api.call("GET", f"/nodes/{node}/qemu/{tpl}/agent/exec-status", pid=pid)
            if st.get("exited"):
                if st.get("exitcode") != 0:
                    raise CommandError(f"Preparing the template failed: {st.get('err-data') or st.get('out-data')}")
                break
            time.sleep(2)

        self.step("Shutting down and freezing as a template")
        api.wait(node, api.call("POST", f"/nodes/{node}/qemu/{tpl}/status/shutdown", timeout=180), "Shutdown")
        api.call("POST", f"/nodes/{node}/qemu/{tpl}/config",
                 ide2=f"{storage}:cloudinit", ipconfig0="ip=dhcp")
        try:
            api.call("DELETE", f"/nodes/{node}/storage/local/content/{seed}")
        except CommandError:
            pass  # already gone
        api.wait(node, api.call("POST", f"/nodes/{node}/qemu/{tpl}/template"), "Template")
        self.stdout.write(self.style.SUCCESS(f"Template VM {tpl} ready."))
