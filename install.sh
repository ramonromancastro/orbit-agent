#!/usr/bin/env bash
# ==============================================================================
# Orbit Enterprise Agent - Automated Production Provisioner
# ==============================================================================

set -euo pipefail

###################################
# CONSTANTS & DIRECTORIES
###################################
APP_DIR="/opt/orbit-agent"
VAR_DIR="/var/lib/orbit-agent"
SERVICE_FILE="/etc/systemd/system/orbit-agent.service"
TIMER_FILE="/etc/systemd/system/orbit-agent.timer"
SUDOERS_FILE="/etc/sudoers.d/orbit-agent"

# Determine sysconfig / default path according to OS family
if [ -d "/etc/sysconfig" ]; then
    SYSCONFIG_FILE="/etc/sysconfig/orbit-agent"
else
    SYSCONFIG_FILE="/etc/default/orbit-agent"
fi

# ANSI Terminal Colors
COLOR_RESET="\033[0m"
COLOR_INFO="\033[38;5;39m"
COLOR_SUCCESS="\033[38;5;48m"
COLOR_WARN="\033[38;5;214m"
COLOR_ERROR="\033[38;5;196m"

log_info() {
    printf "${COLOR_INFO}[INFO]${COLOR_RESET} %s\n" "$1"
}

log_success() {
    printf "${COLOR_SUCCESS}[OK]${COLOR_RESET} %s\n" "$1"
}

log_warn() {
    printf "${COLOR_WARN}[WARN]${COLOR_RESET} %s\n" "$1"
}

log_error() {
    printf "${COLOR_ERROR}[ERROR]${COLOR_RESET} %s\n" "$1" >&2
}

###################################
# CLI ARGUMENTS PARSING
###################################
SERVER_URL=""
API_TOKEN=""
TAGS=""
SSL_CERT=""
IGNORE_SSL="false"

usage() {
    cat << EOF
Usage: $0 --server <URL> --token <TOKEN> [OPTIONS]

Required Arguments:
  -s, --server <URL>        Orbit Server base URL (e.g. https://orbit.company.internal)
  -t, --token <TOKEN>       Orbit Master API Token

Optional Arguments:
  --tags <TAG1,TAG2>        Host group tags (e.g. production,db)
  --ssl-cert <PATH>         Path to custom SSL/TLS Certificate Authority (CA) bundle
  --ignore-ssl              Ignore TLS certificate verification errors (Staging only)
  -h, --help                Show this help message
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -s|--server)
            SERVER_URL="$2"
            shift 2
            ;;
        -t|--token)
            API_TOKEN="$2"
            shift 2
            ;;
        --tags)
            TAGS="$2"
            shift 2
            ;;
        --ssl-cert)
            SSL_CERT="$2"
            shift 2
            ;;
        --ignore-ssl)
            IGNORE_SSL="true"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown parameter: $1"
            usage
            ;;
    esac
done

###################################
# PRIVILEGE & ARGUMENT VALIDATION
###################################
if [ "$(id -u)" -ne 0 ]; then
    log_error "This script must be executed with root privileges (e.g., via sudo)."
    exit 1
fi

# If existing config exists, server and token might not be strictly needed on upgrades
if [ ! -f "${SYSCONFIG_FILE}" ]; then
    if [ -z "${SERVER_URL}" ] || [ -z "${API_TOKEN}" ]; then
        log_error "Missing required parameters: --server and --token are required for new installations."
        usage
    fi
fi

printf "\n"
printf "  =======================================================\n"
printf "   Orbit Enterprise Agent - System Provisioning          \n"
printf "  =======================================================\n\n"

###################################
# SYSTEM USER PROVISIONING
###################################
log_info "Ensuring system group and dedicated service user exist..."
if ! getent group orbit-agent >/dev/null 2>&1; then
    groupadd -r orbit-agent
    log_success "Created system group: orbit-agent"
fi

if ! getent passwd orbit-agent >/dev/null 2>&1; then
    useradd -r -g orbit-agent -s /sbin/nologin -d "${VAR_DIR}" -c "Orbit Enterprise Agent Service" orbit-agent
    log_success "Created system user: orbit-agent"
fi

###################################
# FILESYSTEM HIERARCHY INITIALIZATION
###################################
log_info "Creating required directory hierarchy..."
mkdir -p "${APP_DIR}"
mkdir -p "${VAR_DIR}"

###################################
# RUNTIME ENVIRONMENT FILE
###################################
if [ ! -f "${SYSCONFIG_FILE}" ]; then
    log_info "Generating environment configuration: ${SYSCONFIG_FILE}..."

    cat << EOF > "${SYSCONFIG_FILE}"
# (Required) Fully qualified domain name or IP address of the central Orbit Enterprise Server (e.g., https://orbit.company.internal). Include the subpath context prefix if applicable (e.g., https://services.company.internal/orbit-server).
# Format: String (URL)
ORBIT_SERVER_URL=${SERVER_URL}

# (Required) Master authentication Bearer token configured on the server (ORBIT_API_TOKEN) to validate client-to-server communications.
# Format: String (Secret)
ORBIT_API_TOKEN=${API_TOKEN}

# Group and environment identifiers assigned to the node (e.g., production,http,database) used for task filtering, batch targeting, and dashboard categorization.
# Format: Comma-separated list
ORBIT_TAGS=${TAGS}

# Absolute path to a custom Certificate Authority (CA) root bundle or public server certificate (e.g., /opt/orbit/orbit.crt). Required when connecting to an internal orchestrator secured with a private/self-signed enterprise CA.
# Format: Filesystem Path
ORBIT_SSL_CERT=${SSL_CERT}

# Explicitly disables TLS certificate verification. Warning: Use only in staging or testing labs; never enable in production environments as it exposes communications to Man-in-the-Middle (MITM) risks.
# Format: Boolean (true|false)
ORBIT_IGNORE_SSL_ERRORS=${IGNORE_SSL}
EOF
    chmod 0600 "${SYSCONFIG_FILE}"
    log_success "Generated new system configuration."
else
    log_info "Existing ${SYSCONFIG_FILE} detected. Keeping current secrets and settings."
fi

###################################
# CONTROLLED PRIVILEGE ESCALATION (SUDOERS)
###################################
log_info "Configuring least-privilege sudoers permissions for package managers..."
cat << 'EOF' > "${SUDOERS_FILE}"
# Orbit Enterprise Agent - Limited command permissions for system updates
Defaults:orbit-agent !requiretty
orbit-agent ALL=(ALL) NOPASSWD: /usr/bin/dnf, /usr/bin/yum, /usr/bin/apt, /usr/bin/apt-get, /usr/bin/needs-restarting
EOF
chmod 0440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}" >/dev/null
log_success "Sudoers drop-in validated and configured."

###################################
# SYSTEM SECURITY & PERMISSIONS
###################################
log_info "Applying restrictive system permissions (Least Privilege)..."

# Source code tree
chown -R root:orbit-agent "${APP_DIR}"
find "${APP_DIR}" -type d -exec chmod o=,u=rwx,g=rx {} +
find "${APP_DIR}" -type f -exec chmod o=,u=rwX,g=rX {} +

# Data store (/var/lib/orbit-agent)
chown -R orbit-agent:orbit-agent "${VAR_DIR}"
chmod 0700 "${VAR_DIR}"

log_success "Filesystem permissions applied."

###################################
# SYSTEMD SERVICE DEPLOYMENT
###################################
log_info "Deploying systemd service unit..."
cat << EOF > "${SERVICE_FILE}"
[Unit]
Description=Orbit Enterprise Agent (One-Shot)
After=network.target

[Service]
Type=oneshot
User=orbit-agent
Group=orbit-agent

# Load environment variables (supports both Debian and RHEL paths)
EnvironmentFile=-/etc/default/orbit-agent
EnvironmentFile=-/etc/sysconfig/orbit-agent

ExecStart=/usr/bin/python3 /opt/orbit-agent/orbit_agent.py
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=orbit-agent

# Security Hardening Directives
ProtectSystem=full
ProtectHome=true
ReadOnlyPaths=${APP_DIR}
ReadWritePaths=${VAR_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

chmod 0644 "${SERVICE_FILE}"

log_info "Deploying systemd timer unit..."
cat << EOF > "${TIMER_FILE}"
[Unit]
Description=Timer for Orbit Enterprise Agent

[Timer]
# Wait 2 minutes after system boot before the first execution
OnBootSec=2min

# Execute the agent every 10 minutes
OnUnitActiveSec=10min

# Add a random delay of up to 30 seconds to distribute network load
RandomizedDelaySec=30
Unit=orbit-agent.service

[Install]
WantedBy=timers.target
EOF

chmod 0644 "${TIMER_FILE}"

systemctl daemon-reload
systemctl enable orbit-agent.service
log_success "Service unit installed and enabled."

printf "\n"
printf "==========================================================================\n"
printf " ${COLOR_SUCCESS}[SUCCESS]${COLOR_RESET} Orbit Enterprise Agent has been successfully provisioned.\n"
printf " ------------------------------------------------------------------------\n"
printf " Start service:        systemctl start orbit-agent.timer\n"
printf " Check service health: systemctl status orbit-agent.timer\n"
printf "                       systemctl status orbit-agent.service\n"
printf " Configuration file:   ${SYSCONFIG_FILE}\n"
printf "==========================================================================\n\n"