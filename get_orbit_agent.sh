#!/usr/bin/env bash
# ==============================================================================
# Orbit Enterprise Agent - Bootstrap Installer
#
# Usage:
#   sudo ./get_orbit_agent.sh [--version <tag>] [--dir <path>]
#   curl -sSL https://raw.githubusercontent.com/.../get_orbit_agent.sh | sudo bash -s -- --version 1.2.3
# ==============================================================================

set -euo pipefail

# --- CONFIGURATION DEFAULTS ---
REPO_OWNER="ramonromancastro"
REPO_NAME="orbit-agent"
GITHUB_REPO="${REPO_OWNER}/${REPO_NAME}"
TARGET_DIR="/opt/orbit-agent"
TARGET_VERSION="latest"

# --- COLOR DEFINITIONS ---
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

display_help() {
    cat << EOF
Orbit Enterprise Agent - Bootstrap Installer

Usage:
  sudo ./get_orbit_agent.sh [OPTIONS]

Options:
  -v, --version <tag>    Specify release tag (e.g., 1.2.3). Default: latest
  -h, --help             Display this help message

Examples:
  sudo ./get_orbit_agent.sh --version 1.0.0
  sudo ./get_orbit_agent.sh --version latest
EOF
    exit 0
}

# --- CLI ARGUMENT PARSING (NOMINAL) ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--version)
            if [[ -z "${2:-}" || "${2:-}" == -* ]]; then
                log_error "Missing value for argument: $1"
                exit 1
            fi
            TARGET_VERSION="$2"
            shift 2
            ;;
        -h|--help)
            display_help
            ;;
        *)
            log_error "Unknown option: $1"
            display_help
            ;;
    esac
done

# --- PRE-FLIGHT CHECKS ---
if [[ "$(id -u)" -ne 0 ]]; then
    log_error "This script must be executed as root or via sudo."
    exit 1
fi

for cmd in curl tar python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "Required dependency '$cmd' is not installed."
        exit 1
    fi
done

printf "\n"
printf "  =======================================================\n"
printf "   Orbit Enterprise Agent - Production Installer         \n"
printf "  =======================================================\n\n"

log_info "Target installation directory: ${TARGET_DIR}"

# --- RESOLVE RELEASE DOWNLOAD URL ---
if [[ "${TARGET_VERSION}" == "latest" ]]; then
    log_info "Resolving latest stable release from github.com/${GITHUB_REPO}..."
    API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"
    
    API_RESPONSE=$(curl -sSL -H "Accept: application/vnd.github.v3+json" "${API_URL}" || true)
    
    # Extract tag name and tarball URL
    RELEASE_TAG=$(printf "%s" "${API_RESPONSE}" | grep '"tag_name":' | head -n 1 | cut -d '"' -f 4 || true)
    TARBALL_URL=$(printf "%s" "${API_RESPONSE}" | grep '"tarball_url":' | head -n 1 | cut -d '"' -f 4 || true)

    if [[ -z "${TARBALL_URL}" ]]; then
        log_error "Unable to locate the latest published release. Verify that at least one release exists on GitHub."
        exit 1
    fi
    log_info "Selected release: ${RELEASE_TAG}"
else
    log_info "Target release explicitly set to: ${TARGET_VERSION}"
    TARBALL_URL="https://github.com/${GITHUB_REPO}/archive/refs/tags/${TARGET_VERSION}.tar.gz"
fi

# --- DOWNLOAD AND UNPACK ---
log_info "Downloading source archive..."
mkdir -p "${TARGET_DIR}"

if ! curl -sSL --fail "${TARBALL_URL}" | tar -xz -C "${TARGET_DIR}" --strip-components=1; then
    log_error "Failed to download or extract release package. Ensure tag '${TARGET_VERSION}' exists."
    exit 1
fi

log_success "Source archive unpacked successfully into ${TARGET_DIR}"

# --- EXECUTE LOCAL PROVISIONING SCRIPT ---
INSTALL_SCRIPT="${TARGET_DIR}/install.sh"
if [[ ! -f "${INSTALL_SCRIPT}" ]]; then
    log_error "Missing internal provisioner: ${INSTALL_SCRIPT}"
    exit 1
fi

log_info "Executing internal system provisioner (install.sh)..."
chmod +x "${INSTALL_SCRIPT}"
"${INSTALL_SCRIPT}"

printf "\n"
log_success "Orbit Enterprise Agent bootstrap finished successfully."