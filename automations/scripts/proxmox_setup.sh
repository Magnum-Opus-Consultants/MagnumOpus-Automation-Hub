#!/usr/bin/env bash
# One-time setup on the Proxmox host for Sentinel project servers.
#
# Paste it into the Proxmox web UI: Datacenter > (the node) > Shell.
# It is safe to run more than once - every step checks before it changes
# anything, and nothing existing is modified or removed.
#
# It adds:
#   1. A small storage area, "sentinel-snippets", holding one first-boot file
#      that installs the QEMU guest agent - how Sentinel reads a new server's
#      address - and allows password logins over SSH.
#   2. VM 9000, an Ubuntu 26.04 LTS cloud-init template on RiadZ2_pool.
#   3. A resource pool "sentinel" holding the template and every project server.
#   4. A user sentinel@pve with an API token that can manage VMs in that pool
#      only, use the storage and network, and read the host's free memory.
#      It cannot touch the Nextclouds or any VM outside the pool.
#
# The token's secret is printed once at the very end. Put it in Sentinel's
# .env together with the other lines printed there.
set -euo pipefail

TEMPLATE_ID=9000
STORAGE=RiadZ2_pool
BRIDGE=vmbr0
POOL=sentinel
IMAGE_URL=https://cloud-images.ubuntu.com/releases/26.04/release/ubuntu-26.04-server-cloudimg-amd64.img
IMAGE=/var/lib/vz/template/iso/ubuntu-26.04-server-cloudimg-amd64.img
SNIPPETS_DIR=/var/lib/vz/sentinel-snippets
NETBIRD_URL=https://100.108.29.54:8006

echo "== 1. First-boot snippet"
if ! pvesm status --storage sentinel-snippets >/dev/null 2>&1; then
  mkdir -p "$SNIPPETS_DIR/snippets"
  pvesm add dir sentinel-snippets --path "$SNIPPETS_DIR" --content snippets
fi
cat > "$SNIPPETS_DIR/snippets/sentinel-vendor.yaml" <<'YAML'
#cloud-config
# Applied on first boot of every Sentinel project server.
package_update: true
packages:
  - qemu-guest-agent
runcmd:
  - systemctl enable --now qemu-guest-agent
ssh_pwauth: true
YAML

echo "== 2. Ubuntu 26.04 template (VM $TEMPLATE_ID)"
if qm status "$TEMPLATE_ID" >/dev/null 2>&1; then
  echo "VM $TEMPLATE_ID already exists - leaving it as it is."
else
  mkdir -p "$(dirname "$IMAGE")"
  [ -f "$IMAGE" ] || wget -q --show-progress -O "$IMAGE" "$IMAGE_URL"
  qm create "$TEMPLATE_ID" --name ubuntu-2604-template --ostype l26 \
    --memory 4096 --cores 2 --cpu host \
    --net0 "virtio,bridge=$BRIDGE" --scsihw virtio-scsi-single \
    --agent enabled=1 --serial0 socket --vga serial0
  qm set "$TEMPLATE_ID" --scsi0 "$STORAGE:0,import-from=$IMAGE,discard=on"
  qm set "$TEMPLATE_ID" --ide2 "$STORAGE:cloudinit" --boot order=scsi0
  qm set "$TEMPLATE_ID" --ipconfig0 ip=dhcp \
    --cicustom "vendor=sentinel-snippets:snippets/sentinel-vendor.yaml"
  qm template "$TEMPLATE_ID"
fi

echo "== 3. Resource pool '$POOL'"
pvesh get "/pools/$POOL" >/dev/null 2>&1 || pveum pool add "$POOL" --comment "Sentinel project servers"
pveum pool modify "$POOL" --vms "$TEMPLATE_ID" >/dev/null 2>&1 || true

echo "== 4. API user and token"
pveum user list --output-format json | grep -q '"userid":"sentinel@pve"' \
  || pveum user add sentinel@pve --comment "Sentinel project servers"
pveum acl modify "/pool/$POOL" --users sentinel@pve --roles PVEVMAdmin
pveum acl modify "/storage/$STORAGE" --users sentinel@pve --roles PVEDatastoreUser
pveum acl modify /storage/sentinel-snippets --users sentinel@pve --roles PVEDatastoreUser
pveum acl modify /sdn/zones/localnetwork --users sentinel@pve --roles PVESDNUser
pveum acl modify /nodes --users sentinel@pve --roles PVEAuditor

if pveum user token list sentinel@pve --output-format json | grep -q '"tokenid":"provisioning"'; then
  echo
  echo "The token sentinel@pve!provisioning already exists, so no new secret was made."
  echo "To make a new one: pveum user token remove sentinel@pve provisioning, then run this again."
  exit 0
fi
SECRET=$(pveum user token add sentinel@pve provisioning --privsep 0 \
           --comment "Sentinel" --output-format json | sed -n 's/.*"value":"\([^"]*\)".*/\1/p')

cat <<EOF

== Done. Add these lines to Sentinel's .env, then restart Sentinel.
== The secret is shown only this once.

PROXMOX_URL=$NETBIRD_URL
PROXMOX_TOKEN_ID=sentinel@pve!provisioning
PROXMOX_TOKEN_SECRET=$SECRET
PROXMOX_VERIFY_SSL=false
PROXMOX_TEMPLATE_VMID=$TEMPLATE_ID
PROXMOX_STORAGE=$STORAGE
PROXMOX_POOL=$POOL
EOF
