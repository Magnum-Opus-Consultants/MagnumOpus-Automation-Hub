"""Project servers: a Linux VM per project on the office Proxmox host.

Sentinel talks to Proxmox through its API with a token (see
scripts/proxmox_setup.sh, which creates the token and the Ubuntu template).
A server is a full clone of that cloud-init template, given its own CPU,
memory, disk, user and SSH keys, then started.

The host also runs the client Nextclouds, so this module is deliberately
narrow: it creates VMs from one template, and every later action goes through
a ProjectServer row and checks the VM still carries Sentinel's name and tag
before touching it. Nothing here can act on a machine Sentinel did not make.

Configuration, all from the environment:
  PROXMOX_URL            https://100.108.29.54:8006   (over NetBird)
  PROXMOX_TOKEN_ID       sentinel@pve!provisioning
  PROXMOX_TOKEN_SECRET   the secret printed when the token was made
  PROXMOX_VERIFY_SSL     false while the host has its self-signed certificate
  PROXMOX_NODE           optional - the only node is used when blank
  PROXMOX_TEMPLATE_VMID  9000
  PROXMOX_STORAGE        RiadZ2_pool
  PROXMOX_POOL           sentinel - the resource pool the token is limited to
  PROXMOX_VMID_START     200 - new VMs are numbered from here
  PROXMOX_SSH_KEYS       public keys put on every server, one per line or ';'
  PROXMOX_VM_USER        moc
  PROXMOX_CONSOLE_USER, PROXMOX_CONSOLE_PASSWORD
                         the same pool-limited user's login, for consoles only:
                         Proxmox's console service will not take a token
  PROXMOX_IP_POOL        optional fixed range, e.g. 10.0.0.150-10.0.0.199;
                         blank means the office router hands out the address
  PROXMOX_GATEWAY, PROXMOX_CIDR, PROXMOX_DNS   only with PROXMOX_IP_POOL
"""
import ipaddress
import logging
import os
import re
import secrets
import string
import threading
import time
from urllib.parse import quote

import requests
from django.db import close_old_connections

logger = logging.getLogger(__name__)

# The one size asked for: every project server is the same.
SIZE = {'cores': 2, 'memory_mb': 4096, 'disk_gb': 100}
OS_LABEL = 'Ubuntu 26.04 LTS'
TAG = 'sentinel'
# Headroom left on the host after a new server, so a burst of projects cannot
# starve the Nextclouds of memory.
MEMORY_HEADROOM_MB = 4096


class ProxmoxError(Exception):
    """Something Proxmox refused or did not answer. The message is for people."""


def _env(key, default=''):
    return (os.getenv(key) or default).strip()


def config():
    return {
        'url': _env('PROXMOX_URL').rstrip('/'),
        'token_id': _env('PROXMOX_TOKEN_ID'),
        'token_secret': _env('PROXMOX_TOKEN_SECRET'),
        'verify': _env('PROXMOX_VERIFY_SSL', 'true').lower() not in ('0', 'false', 'no'),
        'node': _env('PROXMOX_NODE'),
        'template': int(_env('PROXMOX_TEMPLATE_VMID', '9000') or 9000),
        'storage': _env('PROXMOX_STORAGE', 'RiadZ2_pool'),
        'pool': _env('PROXMOX_POOL', 'sentinel'),
        'vmid_start': int(_env('PROXMOX_VMID_START', '200') or 200),
        'ssh_keys': _env('PROXMOX_SSH_KEYS'),
        'user': _env('PROXMOX_VM_USER', 'moc'),
        'ip_pool': _env('PROXMOX_IP_POOL'),
        'gateway': _env('PROXMOX_GATEWAY'),
        'cidr': int(_env('PROXMOX_CIDR', '24') or 24),
        'dns': _env('PROXMOX_DNS'),
        'console_user': _env('PROXMOX_CONSOLE_USER'),
        'console_password': _env('PROXMOX_CONSOLE_PASSWORD'),
    }


def is_configured():
    c = config()
    return bool(c['url'] and c['token_id'] and c['token_secret'])


# ── small pure helpers (tested in tests.py) ─────────────────────────────────

def hostname_for(project_name, taken=()):
    """A DNS-safe hostname from a project name: "Coffee Shop" -> coffee-shop."""
    base = re.sub(r'[^a-z0-9]+', '-', project_name.lower()).strip('-')[:55] or 'project'
    name, n = base, 2
    while name in taken:
        name = f'{base}-{n}'
        n += 1
    return name


def ssh_keys_param(keys):
    """Proxmox wants `sshkeys` URL-encoded inside the form value, not just once."""
    lines = [k.strip() for k in re.split(r'[;\n]+', keys or '') if k.strip()]
    return quote('\n'.join(lines), safe='')


def next_free_ip(pool, used):
    """The first address in "a.b.c.d-a.b.c.e" not in `used`, or None."""
    if not pool or '-' not in pool:
        return None
    lo, hi = (ipaddress.ip_address(p.strip()) for p in pool.split('-', 1))
    ip = lo
    while ip <= hi:
        if str(ip) not in used:
            return str(ip)
        ip += 1
    return None


def check_public_keys(text):
    """'' if every line is an OpenSSH public key, else what is wrong, for people."""
    from cryptography.hazmat.primitives.serialization import load_ssh_public_key
    for line in [k.strip() for k in re.split(r'[;\n]+', text or '') if k.strip()]:
        if 'PRIVATE KEY' in line:
            return 'That is a private key. Paste the public key (the .pub file) instead.'
        try:
            load_ssh_public_key(line.encode())
        except (ValueError, TypeError):
            return ("That is not a valid SSH public key. It should be one line starting "
                    "with ssh-ed25519 or ssh-rsa, like the contents of id_ed25519.pub.")
    return ''


def new_password(length=20):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ── the API ─────────────────────────────────────────────────────────────────

class Client:
    def __init__(self, cfg=None, session=None):
        self.cfg = cfg or config()
        self.session = session or requests.Session()
        self._node = self.cfg['node'] or None

    def call(self, method, path, **data):
        url = f"{self.cfg['url']}/api2/json{path}"
        headers = {'Authorization':
                   f"PVEAPIToken={self.cfg['token_id']}={self.cfg['token_secret']}"}
        try:
            r = self.session.request(
                method, url, headers=headers, verify=self.cfg['verify'], timeout=30,
                # Proxmox reads GET and DELETE parameters from the query string.
                params=data if method in ('GET', 'DELETE') else None,
                data=data if method in ('POST', 'PUT') else None)
        except requests.RequestException as e:
            raise ProxmoxError(f'Could not reach Proxmox at {self.cfg["url"]}: {e}') from e
        if r.status_code >= 400:
            try:
                body = r.json()
                detail = body.get('errors') or body.get('message') or r.reason
            except ValueError:
                detail = r.text[:200] or r.reason
            raise ProxmoxError(f'Proxmox said {r.status_code}: {detail}')
        try:
            return r.json().get('data')
        except ValueError:
            return None

    def node(self):
        if not self._node:
            nodes = self.call('GET', '/nodes') or []
            if not nodes:
                raise ProxmoxError('Proxmox reports no nodes.')
            self._node = nodes[0]['node']
        return self._node

    def wait(self, upid, timeout=900):
        """Block until a Proxmox task finishes; raise if it did not succeed."""
        if not (isinstance(upid, str) and upid.startswith('UPID')):
            return
        deadline = time.monotonic() + timeout
        path = f'/nodes/{self.node()}/tasks/{quote(upid, safe="")}/status'
        while time.monotonic() < deadline:
            st = self.call('GET', path) or {}
            if st.get('status') == 'stopped':
                if st.get('exitstatus') != 'OK':
                    raise ProxmoxError(f'Proxmox task failed: {st.get("exitstatus")}')
                return
            time.sleep(2)
        raise ProxmoxError('Proxmox took too long to finish the task.')

    def vm_ids(self):
        return {int(v['vmid']) for v in (self.call('GET', '/cluster/resources', type='vm') or [])}

    def vm_config(self, vmid):
        return self.call('GET', f'/nodes/{self.node()}/qemu/{vmid}/config') or {}

    def vm_status(self, vmid):
        return self.call('GET', f'/nodes/{self.node()}/qemu/{vmid}/status/current') or {}

    def guest_ipv4(self, vmid):
        """The VM's address from its guest agent, or '' if it cannot say yet."""
        try:
            data = self.call('GET', f'/nodes/{self.node()}/qemu/{vmid}/agent/network-get-interfaces')
        except ProxmoxError:
            return ''
        for iface in (data or {}).get('result', []):
            if iface.get('name') == 'lo':
                continue
            for a in iface.get('ip-addresses', []):
                if a.get('ip-address-type') == 'ipv4' and not a['ip-address'].startswith('127.'):
                    return a['ip-address']
        return ''


# ── creating, running and removing ──────────────────────────────────────────

def check_capacity(client):
    """Refuse up front rather than half-build a VM the host cannot hold."""
    cfg = client.cfg
    node = client.node()
    status = client.call('GET', f'/nodes/{node}/status') or {}
    mem = status.get('memory') or {}
    free_mb = (mem.get('total', 0) - mem.get('used', 0)) // (1024 * 1024)
    if free_mb < SIZE['memory_mb'] + MEMORY_HEADROOM_MB:
        raise ProxmoxError(
            f'The host has {free_mb // 1024} GB of memory free; a server needs '
            f'{SIZE["memory_mb"] // 1024} GB plus headroom for the machines already on it.')
    store = client.call('GET', f'/nodes/{node}/storage/{cfg["storage"]}/status') or {}
    avail_gb = store.get('avail', 0) // (1024 ** 3)
    if avail_gb < SIZE['disk_gb']:
        raise ProxmoxError(
            f'Storage {cfg["storage"]} has {avail_gb} GB free; a server needs {SIZE["disk_gb"]} GB.')
    if cfg['template'] not in client.vm_ids():
        raise ProxmoxError(
            f'There is no template VM {cfg["template"]} on Proxmox yet. '
            'Run scripts/proxmox_setup.sh on the host first.')


def pick_vmid(client, reserved=()):
    """The first free VM number from PROXMOX_VMID_START up.

    Asked of /cluster/nextid rather than worked out from the VM list: the
    token only sees its own pool, so the list would miss the Nextclouds.
    """
    reserved = set(reserved)
    vmid = client.cfg['vmid_start']
    for _ in range(500):
        if vmid not in reserved:
            try:
                return int(client.call('GET', '/cluster/nextid', vmid=vmid))
            except ProxmoxError as e:
                if 'already' not in str(e).lower() and 'exist' not in str(e).lower():
                    raise
        vmid += 1
    raise ProxmoxError('Could not find a free VM number.')


def provision(server_id, password, extra_keys=''):
    """Build the VM for a ProjectServer row. Runs in a background thread."""
    from .models import ProjectServer
    close_old_connections()
    server = ProjectServer.objects.get(id=server_id)

    def mark(**fields):
        for k, v in fields.items():
            setattr(server, k, v)
        server.save(update_fields=list(fields) + ['updated_at'])

    try:
        client = Client()
        cfg = client.cfg
        node = client.node()
        vmid = server.vmid

        mark(status='provisioning', step=f'Copying the {OS_LABEL} template')
        client.wait(client.call(
            'POST', f'/nodes/{node}/qemu/{cfg["template"]}/clone',
            newid=vmid, name=server.name, full=1, storage=cfg['storage'],
            **({'pool': cfg['pool']} if cfg['pool'] else {}),
            description=f'Sentinel server for project "{server.project_name}"'))

        # Marked as Sentinel's first, on its own: if a later step fails, the
        # half-made VM is still recognisably ours and can be deleted from here.
        client.call('POST', f'/nodes/{node}/qemu/{vmid}/config', tags=TAG)

        mark(step='Setting CPU, memory and login')
        settings = {
            'cores': server.cores, 'memory': server.memory_mb,
            'ciuser': server.username, 'cipassword': password,
            'tags': TAG, 'agent': 'enabled=1', 'onboot': 1,
            'ipconfig0': (f'ip={server.ip}/{cfg["cidr"]},gw={cfg["gateway"]}'
                          if server.ip else 'ip=dhcp'),
        }
        keys = '\n'.join(k for k in (cfg['ssh_keys'], extra_keys) if k)
        if keys.strip():
            settings['sshkeys'] = ssh_keys_param(keys)
        if server.ip and cfg['dns']:
            settings['nameserver'] = cfg['dns']
        client.call('POST', f'/nodes/{node}/qemu/{vmid}/config', **settings)

        mark(step=f'Growing the disk to {server.disk_gb} GB')
        client.wait(client.call('PUT', f'/nodes/{node}/qemu/{vmid}/resize',
                                disk='scsi0', size=f'{server.disk_gb}G'))

        mark(step='Starting it')
        client.wait(client.call('POST', f'/nodes/{node}/qemu/{vmid}/status/start'))

        if not server.ip:
            # First boot installs the guest agent, which is what reports the
            # address the router gave it. A few minutes on a fresh image.
            mark(step='Waiting for its address')
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                ip = client.guest_ipv4(vmid)
                if ip:
                    server.ip = ip
                    break
                time.sleep(10)
        mark(status='running', step='', ip=server.ip, error='')
        if server.ip:
            from .models import ProjectCredential
            ProjectCredential.objects.filter(server=server).update(
                location=f'ssh {server.username}@{server.ip}')
    except Exception as e:  # noqa: BLE001 - every failure is shown on the row
        logger.exception('Provisioning server %s failed', server_id)
        mark(status='failed', step='', error=str(e)[:2000])
    finally:
        close_old_connections()


def _own_vm(client, server):
    """True only if the VM is still the one Sentinel made for this row."""
    if not server.vmid:
        return False
    try:
        conf = client.vm_config(server.vmid)
    except ProxmoxError:
        return False
    tags = set(re.split(r'[;, ]+', conf.get('tags', '')))
    # The description is set by the clone itself, so it also covers a VM whose
    # setup failed before its tag could be added.
    made_here = (conf.get('description') or '').startswith('Sentinel server for project')
    return conf.get('name') == server.name and (TAG in tags or made_here)


def refresh(server):
    """Bring a row back in line with what Proxmox says about its VM."""
    client = Client()
    if not _own_vm(client, server):
        if server.status not in ('provisioning', 'queued'):
            server.status, server.step = 'failed', ''
            server.error = 'The VM is no longer on Proxmox, or is no longer one Sentinel made.'
            server.save(update_fields=['status', 'step', 'error', 'updated_at'])
        return server
    st = client.vm_status(server.vmid)
    if server.status not in ('provisioning', 'deleting'):
        server.status = 'running' if st.get('status') == 'running' else 'stopped'
    if not server.ip and st.get('status') == 'running':
        server.ip = client.guest_ipv4(server.vmid)
    server.save(update_fields=['status', 'ip', 'updated_at'])
    return server


# What a server may be changed to. Memory in MB, disk in GB.
CORE_CHOICES = (1, 2, 4, 6, 8, 12, 16)
MEMORY_CHOICES = tuple(gb * 1024 for gb in (1, 2, 4, 6, 8, 12, 16, 24, 32))
MAX_DISK_GB = 2000


def resize(server, cores, memory_mb, disk_gb):
    """Change a server's CPU, memory and disk. Returns True if a restart applies it.

    CPU and memory are stored as pending changes and take effect when Proxmox
    next stops and starts the VM (its reboot does both). The disk can only
    grow; Ubuntu expands its filesystem into the new space on the next boot.
    """
    if cores not in CORE_CHOICES or memory_mb not in MEMORY_CHOICES:
        raise ProxmoxError('Pick one of the offered CPU and memory sizes.')
    if disk_gb < server.disk_gb:
        raise ProxmoxError(f'A disk can grow but not shrink; it is {server.disk_gb} GB now.')
    if disk_gb > MAX_DISK_GB:
        raise ProxmoxError(f'The disk can be at most {MAX_DISK_GB} GB.')
    client = Client()
    if not _own_vm(client, server):
        raise ProxmoxError('That VM is not one Sentinel made, so it was left alone.')
    node = client.node()

    extra_mb = memory_mb - server.memory_mb
    if extra_mb > 0:
        mem = (client.call('GET', f'/nodes/{node}/status') or {}).get('memory') or {}
        free_mb = (mem.get('total', 0) - mem.get('used', 0)) // (1024 * 1024)
        if free_mb < extra_mb + MEMORY_HEADROOM_MB:
            raise ProxmoxError(f'The host has {free_mb // 1024} GB of memory free - not enough '
                               f'for {extra_mb // 1024} GB more plus headroom for the other machines.')
    extra_gb = disk_gb - server.disk_gb
    if extra_gb > 0:
        store = client.call('GET', f"/nodes/{node}/storage/{client.cfg['storage']}/status") or {}
        if store.get('avail', 0) // (1024 ** 3) < extra_gb:
            raise ProxmoxError(f"Storage {client.cfg['storage']} does not have {extra_gb} GB free.")

    changes = {}
    if cores != server.cores:
        changes['cores'] = cores
    if memory_mb != server.memory_mb:
        changes['memory'] = memory_mb
    if changes:
        client.wait(client.call('POST', f'/nodes/{node}/qemu/{server.vmid}/config', **changes))
    if extra_gb > 0:
        client.wait(client.call('PUT', f'/nodes/{node}/qemu/{server.vmid}/resize',
                                disk='scsi0', size=f'{disk_gb}G'))
    running = client.vm_status(server.vmid).get('status') == 'running'
    return running and bool(changes or extra_gb > 0)


def power(server, action):
    """start, shutdown or reboot - on Sentinel's own VMs only."""
    client = Client()
    if not _own_vm(client, server):
        raise ProxmoxError('That VM is not one Sentinel made, so it was left alone.')
    path = {'start': 'start', 'stop': 'shutdown', 'reboot': 'reboot'}[action]
    client.wait(client.call('POST', f'/nodes/{client.node()}/qemu/{server.vmid}/status/{path}'),
                timeout=300)
    return refresh(server)


def destroy(server_id):
    """Stop and delete the VM, disks included. Runs in a background thread."""
    from .models import ProjectServer
    close_old_connections()
    server = ProjectServer.objects.get(id=server_id)
    try:
        client = Client()
        node = client.node()
        if server.vmid and _own_vm(client, server):
            if client.vm_status(server.vmid).get('status') == 'running':
                server.step = 'Stopping it'
                server.save(update_fields=['step', 'updated_at'])
                client.wait(client.call('POST', f'/nodes/{node}/qemu/{server.vmid}/status/stop'))
            server.step = 'Deleting the VM and its disks'
            server.save(update_fields=['step', 'updated_at'])
            client.wait(client.call('DELETE', f'/nodes/{node}/qemu/{server.vmid}',
                                    purge=1, **{'destroy-unreferenced-disks': 1}))
        server.status, server.step = 'deleted', ''
        server.save(update_fields=['status', 'step', 'updated_at'])
        # A login for a machine that no longer exists is only a liability.
        from .models import ProjectCredential
        ProjectCredential.objects.filter(server=server).delete()
    except Exception as e:  # noqa: BLE001
        logger.exception('Deleting server %s failed', server_id)
        server.status, server.step, server.error = 'failed', '', f'Could not delete: {e}'[:2000]
        server.save(update_fields=['status', 'step', 'error', 'updated_at'])
    finally:
        close_old_connections()


def open_terminal(server):
    """Start a serial console on one of Sentinel's VMs.

    Returns what the console relay needs to attach: the websocket URL, the
    login cookie to send with it, and the line that authenticates the console.
    The ownership check uses the token; the console itself needs a login
    ticket, which is why PROXMOX_CONSOLE_PASSWORD exists.
    """
    client = Client()
    cfg = client.cfg
    if not (cfg['console_user'] and cfg['console_password']):
        raise ProxmoxError('Consoles need PROXMOX_CONSOLE_USER and PROXMOX_CONSOLE_PASSWORD '
                           '(run manage.py proxmox_setup).')
    if not _own_vm(client, server):
        raise ProxmoxError('That VM is not one Sentinel made.')
    node = client.node()
    s = requests.Session()
    try:
        r = s.post(f"{cfg['url']}/api2/json/access/ticket", verify=cfg['verify'], timeout=20,
                   data={'username': cfg['console_user'], 'password': cfg['console_password']})
        r.raise_for_status()
        login = r.json()['data']
        r = s.post(f"{cfg['url']}/api2/json/nodes/{node}/qemu/{server.vmid}/termproxy",
                   verify=cfg['verify'], timeout=20, data={'serial': 'serial0'},
                   cookies={'PVEAuthCookie': login['ticket']},
                   headers={'CSRFPreventionToken': login['CSRFPreventionToken']})
        r.raise_for_status()
        term = r.json()['data']
    except (requests.RequestException, KeyError, ValueError) as e:
        raise ProxmoxError(f'Proxmox would not open the console: {e}') from e
    base = cfg['url'].replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)
    return {
        'url': (f"{base}/api2/json/nodes/{node}/qemu/{server.vmid}/vncwebsocket"
                f"?port={term['port']}&vncticket={quote(term['ticket'], safe='')}"),
        'cookie': f"PVEAuthCookie={login['ticket']}",
        'auth_line': f"{term['user']}:{term['ticket']}\n",
        'verify': cfg['verify'],
        'vmid': server.vmid,
    }


def in_background(fn, *args):
    threading.Thread(target=fn, args=args, name=f'proxmox-{fn.__name__}', daemon=True).start()
