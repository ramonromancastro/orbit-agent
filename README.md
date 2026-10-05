# Orbit Enterprise Agent
**Orbit Enterpise Agent** (`orbit-agent`) is a lightweight, low-footprint Linux client agent engineered to communicate with **Orbit Enterprise Server**. It runs locally on managed endpoints to collect hardware/OS telemetry, inspect security updates and errata (RPM/DEB), schedule unattended patching tasks, and monitor pending system reboots without requiring inbound network ports or persistent SSH keys.

## 📋 Table of Contents

- [Key Features](#-key-features)
- [System Requirements](#-system-requirements)
- [Architecture & FHS Standards](#-architecture--fhs-standards)
- [Installation Procedure](#-installation-procedure)
  - [Option A: Quick Bootstrap Installer (Recommended)](#option-a-quick-bootstrap-installer-recommended)
  - [Option B: Manual Git Clone](#option-b-manual-git-clone)
- [Configuration Reference](#-configuration-reference)
  - [Environment Variables (`/etc/sysconfig/orbit-agent`)](#environment-variables-etcsysconfigorbit-agent)
- [Service Management](#-service-management)
- [Security Model](#-security-model)
- [License](#-license)
- [Acknowledgments & Development Note](#-acknowledgments--development-note)

## ✨ Key Features

* **Zero Inbound Ports (Outbound Only):** Polling-based architecture querying Orbit Enterprise Server via HTTPS/REST. Firewalls on target nodes do not require open ingress ports.
* **Multi-Distribution Package Manager Support:** Native integration with `dnf`, `yum`, and `apt-get` for security errata classification, changelog tracking, and dry-run testing.
* **Pending Reboot Detection:** Identifies unapplied updates by inspecting active processes mapped to deleted kernel/library descriptors (`needs-restarting -r` on RPM, `/var/run/reboot-required` on Debian/Ubuntu).
* **Minimal Resource Footprint:** Pure standard library or minimal dependency Python daemon running within an isolated sandbox.
* **Automated Failure Recovery:** Handles intermittent network partitions gracefully with configurable retry backoffs and execution result caching.

## 💻 System Requirements

### Recommended Hardware
| Component | Managed Host Requirements |
| :--- | :--- |
| **CPU** | Minimal (< 1% CPU utilization during routine polling) |
| **RAM** | ~35 MB - 60 MB resident memory (RSS) |
| **Storage** | < 100 MB free space in `/opt` and `/var/lib` |

### Supported Operating Systems
* **RHEL / Derivatives:** RHEL 7/8/9, Rocky Linux 8/9, AlmaLinux 8/9, CentOS 7/Stream.
* **Debian / Ubuntu:** Debian 10/11/12, Ubuntu 18.04/20.04/22.04/24.04 LTS.
* **Runtimes:** Python 3.6 or higher.
* **Init System:** `systemd`.

## 📁 Architecture & FHS Standards

Orbit Agent follows the standard Linux **Filesystem Hierarchy Standard (FHS)** layout:

* `/opt/orbit-agent`: Source files, runtime binaries. Owned by `root:orbit-agent`.
* `/var/lib/orbit-agent`: Ephemeral state, task cache buffers, and execution history.
* `/etc/sysconfig/orbit-agent` (or `/etc/default/orbit-agent`): Service-level runtime overrides.
* `/etc/sudoers.d/orbit-agent` : Least-privilege sudoers permissions for package managers.

## 🚀 Installation Procedure

### Option A: Quick Bootstrap Installer (Recommended)

Bootstrap and register the agent directly against your central server instance:

```bash
curl -sSL https://raw.githubusercontent.com/ramonromancastro/orbit-agent/main/get_orbit_agent.sh | sudo bash -s -- \
  --server https://orbit.company.local \
  --token YOUR_ORBIT_API_TOKEN
```

### Option B: Manual Git Clone

To audit the code and deploy manually on a host:

```bash
# 1. Clone repository into the FHS directory
sudo git clone https://github.com/ramonromancastro/orbit-agent.git /opt/orbit-agent

# 2. Enter workspace
cd /opt/orbit-agent

# 3. Execute provisioner passing server URL and API token
sudo chmod +x install.sh
sudo ./install.sh --server https://orbit.company.local --token YOUR_ORBIT_API_TOKEN
```

The `install.sh` provisioner executes the following actions:

1. Creates the unprivileged system user/group `orbit-agent`.
2. Creates `/opt/orbit-agent`, `/var/lib/orbit-agent`, and `/var/log/orbit-agent`.
3. Prepares the Python virtual environment and installs local requirements.
4. Deploys, enables, and starts the `orbit-agent.service` and `orbit-agent.timer` systemd unit.

## ⚙️ Configuration Reference

### Environment Variables (`/etc/sysconfig/orbit-agent` or `/etc/default/orbit-agent`)

The agent daemon reads low-level network, authentication, and TLS parameters directly from `/etc/sysconfig/orbit-agent` (or `/etc/default/orbit-agent` on Debian/Ubuntu derivatives). Recommended file permissions: `0600`.

| Variable | Type / Example | Default | Description |
| :--- | :--- | :--- | :--- |
| `ORBIT_SERVER_URL` | String (`URL`) | *(Required)* | Fully qualified domain name or IP address of the central Orbit Enterprise Server (e.g., `https://orbit.company.internal`). Include the subpath context prefix if applicable (e.g., `https://services.company.internal/orbit-server`). |
| `ORBIT_API_TOKEN` | String (`Secret`) | *(Required)* | Master authentication Bearer token configured on the server (`ORBIT_API_TOKEN`) to validate client-to-server communications. |
| `ORBIT_TAGS` | Comma-separated list | *(None)* | Group and environment identifiers assigned to the node (e.g., `production,http,database`) used for task filtering, batch targeting, and dashboard categorization. |
| `ORBIT_SSL_CERT` | Filesystem Path | *(None)* | Absolute path to a custom Certificate Authority (CA) root bundle or public server certificate (e.g., `/opt/orbit/orbit.crt`). Required when connecting to an internal orchestrator secured with a private/self-signed enterprise CA. |
| `ORBIT_IGNORE_SSL_ERRORS` | Boolean (`true`/`false`) | `false` | Explicitly disables TLS certificate verification. **Warning:** Use only in staging or testing labs; never enable in production environments as it exposes communications to Man-in-the-Middle (MITM) risks. |

## 🛠️ Service Management

The agent daemon is registered as a native systemd unit:

```bash
# Inspect agent status
sudo systemctl status orbit-agent.timer
sudo systemctl status orbit-agent.service
sudo systemctl list-timers orbit-agent.timer

# Inspect runtime activity logs
sudo journalctl -u orbit-agent.service -f
```

## 🔒 Security Model

* **Sandboxed Systemd Execution:** Includes directives such as `ProtectSystem=full`, `PrivateTmp=true`, and restricted write targets limited to operational folders (`/var/lib/orbit-agent`).
* **Controlled Privilege Escalation:** When invoking package managers (`dnf`, `apt`), the daemon switches execution contexts only for authorized binary wrappers via `sudoers` drop-in rules (`/etc/sudoers.d/orbit-agent`).
* **Encrypted Communication:** All communications run over TLS (HTTPS).

## 📄 License

Orbit Agent is released under the **Apache License, Version 2.0**. This allows integration into diverse enterprise environments and proprietary deployment workflows without copyleft viral constraints on surrounding host software. Refer to the [LICENSE](https://www.google.com/search?q=LICENSE) file for details.

## 🤖 Acknowledgments & Development Note

This project was developed with the assistance of Artificial Intelligence (AI) tools, which provided support in code scaffolding, architectural design, documentation, and operational hardening. All source code, security configurations, and deployment logic have been reviewed, tested, and validated for production environments.