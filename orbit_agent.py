#!/usr/bin/env python3
"""
Orbit Enterprise Linux Agent (One-Shot Execution)
Orchestration agent for Linux fleet patch management.
Compatible with standard Python 3.6+ (No external dependencies).
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# --- AGENT VERSION ---
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
APP_VERSION = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "1.0.0"

# --- PATH CONFIGURATION ---
VAR_DIR = Path("/var/lib/orbit-agent")
UUID_FILE = VAR_DIR / "node_uuid"
STATE_FILE = VAR_DIR / "state.json"

# --- CLI ARGUMENT PARSING ---
def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orbit Enterprise Linux Agent")
    parser.add_argument("-u", "--url", help="Orbit Server URL (e.g., https://10.0.0.5:8080)")
    parser.add_argument("-t", "--token", help="API Authentication Token")
    parser.add_argument("-c", "--ssl-cert", help="Path to custom SSL public certificate (.crt)")
    parser.add_argument("-k", "--insecure", action="store_true", help="Ignore SSL certificate validation errors")
    parser.add_argument("--tags", help="Comma-separated group tags")
    return parser.parse_args()


args = parse_arguments()

# --- ENVIRONMENT CONFIGURATION (Precedence: CLI > ENV > Default) ---
ORBIT_SERVER_URL: str = (args.url or os.getenv("ORBIT_SERVER_URL", "http://127.0.0.1:8000")).rstrip("/")
API_TOKEN: str = args.token or os.getenv("ORBIT_API_TOKEN", "")
SSL_CERT_PATH: str = args.ssl_cert or os.getenv("ORBIT_SSL_CERT", "")
IGNORE_SSL_ERRORS: bool = args.insecure or (os.getenv("ORBIT_IGNORE_SSL_ERRORS", "false").lower() in ("true", "1", "yes"))
RAW_TAGS: str = args.tags or os.getenv("ORBIT_TAGS", "")
NODE_TAGS: List[str] = [t.strip() for t in RAW_TAGS.split(",") if t.strip()]


# --- SECURE FILE HELPERS ---
def secure_write_text(filepath: Path, content: str) -> None:
    """Escribe un archivo de texto garantizando permisos 0600."""
    filepath.write_text(content, encoding="utf-8")
    try:
        os.chmod(filepath, 0o600)
    except OSError:
        pass


# --- STATE PERSISTENCE ---
def get_last_state() -> Dict[str, str]:
    """Retrieves the execution state of the last task from previous runs."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"status": "none", "message": ""}


def save_last_state(status: str, message: str) -> None:
    """Saves the result of the current task for the next status report."""
    try:
        VAR_DIR.mkdir(parents=True, exist_ok=True)
        secure_write_text(STATE_FILE, json.dumps({"status": status, "message": message}))
    except Exception as e:
        print(f"[WARN] Failed to save local state: {e}", file=sys.stderr)


# --- DETERMINISTIC NODE IDENTIFICATION ---
def get_or_create_uuid() -> str:
    """Generates an immutable, persistent UUID based on hardware machine-id (FIPS-safe)."""
    VAR_DIR.mkdir(parents=True, exist_ok=True)

    for mid_file in [Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")]:
        if mid_file.exists():
            try:
                mid = mid_file.read_text(encoding="utf-8").strip()
                if mid:
                    # Uso de SHA-256 (compatible FIPS) tomando los primeros 16 bytes (32 hex)
                    sha_digest = hashlib.sha256(mid.encode("utf-8")).hexdigest()[:32]
                    return str(uuid.UUID(sha_digest))
            except Exception:
                pass

    if UUID_FILE.exists():
        try:
            content = UUID_FILE.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass

    new_uuid = str(uuid.uuid4())
    try:
        secure_write_text(UUID_FILE, new_uuid)
    except Exception as e:
        print(f"[WARN] Failed to persist node_uuid: {e}", file=sys.stderr)

    return new_uuid


NODE_UUID: str = get_or_create_uuid()


# --- ROBUST HTTP/HTTPS COMMUNICATION ---
def get_ssl_context() -> Optional[ssl.SSLContext]:
    if not ORBIT_SERVER_URL.startswith("https"):
        return None

    if SSL_CERT_PATH and os.path.exists(SSL_CERT_PATH):
        return ssl.create_default_context(cafile=SSL_CERT_PATH)
    elif IGNORE_SSL_ERRORS:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    return ssl.create_default_context()


def api_request(endpoint: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    url = f"{ORBIT_SERVER_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": f"Orbit-Agent/{APP_VERSION} ({NODE_UUID})"
    }

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        ctx = get_ssl_context()
        urlopen_kwargs = {"context": ctx} if ctx else {}
        with urllib.request.urlopen(req, timeout=20, **urlopen_kwargs) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code} on {endpoint}: {e.reason}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Connection failure on {endpoint}: {e}", file=sys.stderr)
    return None


# --- SYSTEM TELEMETRY ---
def get_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_true_hostname() -> str:
    host_file = Path("/etc/hostname")
    if host_file.exists():
        try:
            name = host_file.read_text(encoding="utf-8").strip()
            if name:
                return name
        except Exception:
            pass
    return socket.gethostname()


def get_os_info() -> str:
    os_release = Path("/etc/os-release")
    if os_release.exists():
        try:
            for line in os_release.read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
    return "Unknown Linux"


def get_uptime() -> float:
    proc_uptime = Path("/proc/uptime")
    if proc_uptime.exists():
        try:
            return float(proc_uptime.read_text(encoding="utf-8").split()[0])
        except Exception:
            pass
    return 0.0


def get_ram_mb() -> int:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(int(line.split()[1]) / 1024)
        except Exception:
            pass
    return 0


# --- ENVIRONMENT HELPER ---
def get_clean_env() -> Dict[str, str]:
    """Garantiza salidas en inglés estándar y neutraliza traducciones locales."""
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["LANGUAGE"] = "en_US:en"
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return env


def normalize_security_level(raw_level: str) -> str:
    lvl = raw_level.lower().split('/')[0].strip()
    if any(k in lvl for k in ["crit"]):
        return "CRITICAL"
    if any(k in lvl for k in ["import"]):
        return "IMPORTANT"
    if any(k in lvl for k in ["mod"]):
        return "MODERATE"
    if any(k in lvl for k in ["low"]):
        return "LOW"
    return "NONE"


# --- PACKAGE AND UPDATE SCANNING ---
def _extract_rpm_name_from_nevra(nevra_str: str) -> str:
    no_arch = nevra_str.rsplit('.', 1)[0] if '.' in nevra_str else nevra_str
    parts = no_arch.rsplit('-', 2)
    if len(parts) == 3:
        return parts[0]
    return no_arch


def _check_updates_rhel(pkg_mgr: str) -> List[Dict[str, Any]]:
    updates: List[Dict[str, Any]] = []
    sec_map: Dict[str, str] = {}
    clean_env = get_clean_env()
    SEV_WEIGHT = {"NONE": 0, "LOW": 1, "MODERATE": 2, "IMPORTANT": 3, "CRITICAL": 4}

    try:
        sec_res = subprocess.run(
            [pkg_mgr, "updateinfo", "list", "--security", "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            env=clean_env,
            timeout=120
        )
        if sec_res.returncode in (0, 100):
            for line in sec_res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3:
                    raw_level = parts[1]
                    raw_pkg = parts[-1]
                    pkg_name = _extract_rpm_name_from_nevra(raw_pkg)
                    if pkg_name:
                        level = normalize_security_level(raw_level)
                        current_level = sec_map.get(pkg_name, "NONE")
                        if SEV_WEIGHT.get(level, 0) > SEV_WEIGHT.get(current_level, 0):
                            sec_map[pkg_name] = level
    except subprocess.TimeoutExpired:
        print(f"[WARN] Timeout fetching security updateinfo from {pkg_mgr}", file=sys.stderr)

    try:
        gen_res = subprocess.run(
            [pkg_mgr, "check-update", "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            env=clean_env,
            timeout=120
        )
        if gen_res.returncode in (0, 100):
            for raw_line in gen_res.stdout.splitlines():
                if raw_line.startswith((" ", "\t")):
                    continue
                line = raw_line.strip()
                if not line or any(term in line.lower() for term in ["obsoleting"]):
                    continue

                parts = line.split()
                if len(parts) >= 3 and "." in parts[0]:
                    full_name, pkg_ver_rel = parts[0], parts[1]
                    name_only, arch = full_name.rsplit(".", 1)

                    if len(arch) > 10 or "/" in arch:
                        continue

                    version, release = (pkg_ver_rel.rsplit("-", 1) if "-" in pkg_ver_rel else (pkg_ver_rel, "0"))
                    sec_level = sec_map.get(name_only, "NONE")

                    updates.append({
                        "name": name_only,
                        "version": version,
                        "release": release,
                        "arch": arch,
                        "is_security": (sec_level != "NONE"),
                        "security_level": sec_level
                    })
    except subprocess.TimeoutExpired:
        print(f"[WARN] Timeout during check-update from {pkg_mgr}", file=sys.stderr)

    return updates


def _check_updates_debian() -> List[Dict[str, Any]]:
    updates: List[Dict[str, Any]] = []
    clean_env = get_clean_env()

    # Detección real de arquitectura en el host Debian/Ubuntu
    arch = "amd64"
    try:
        dpkg_arch = subprocess.run(
            ["dpkg", "--print-architecture"],
            stdout=subprocess.PIPE,
            universal_newlines=True,
            timeout=5
        )
        if dpkg_arch.returncode == 0:
            arch = dpkg_arch.stdout.strip()
    except Exception:
        arch = os.uname().machine

    # Refresco con timeout
    try:
        subprocess.run(["apt-get", "update", "-qq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env, timeout=90)
    except subprocess.TimeoutExpired:
        print("[WARN] Timeout updating apt repositories", file=sys.stderr)

    try:
        res = subprocess.run(
            ["apt-get", "-s", "upgrade"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            env=clean_env,
            timeout=60
        )
        for line in res.stdout.splitlines():
            if line.startswith("Inst "):
                parts = line.split()
                if len(parts) >= 3:
                    pkg_name = parts[1]
                    new_ver = parts[2].strip("[]()")
                    is_sec = "-security" in line.lower() or "debian-security" in line.lower()

                    updates.append({
                        "name": pkg_name,
                        "version": new_ver,
                        "release": "0",
                        "arch": arch,
                        "is_security": is_sec,
                        "security_level": "IMPORTANT" if is_sec else "NONE"
                    })
    except subprocess.TimeoutExpired:
        print("[WARN] Timeout simulating apt upgrade", file=sys.stderr)

    return updates


def check_updates() -> List[Dict[str, Any]]:
    """Detects available updates with package deduplication."""
    raw_updates: List[Dict[str, Any]] = []
    dnf_path = shutil.which("dnf") or shutil.which("yum")
    apt_path = shutil.which("apt-get")

    try:
        if dnf_path:
            raw_updates = _check_updates_rhel(dnf_path)
        elif apt_path:
            raw_updates = _check_updates_debian()
    except Exception as e:
        print(f"[WARN] Error scanning for updates: {e}", file=sys.stderr)

    deduped: List[Dict[str, Any]] = []
    seen_names: Set[str] = set()
    for pkg in raw_updates:
        if pkg["name"] not in seen_names:
            seen_names.add(pkg["name"])
            deduped.append(pkg)

    return deduped


def check_needs_reboot() -> bool:
    """Verifies whether core libraries or running kernel require a system reboot."""
    if Path("/var/run/reboot-required").exists():
        return True

    nr_path = shutil.which("needs-restarting")
    if nr_path:
        try:
            res = subprocess.run([nr_path, "-r"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            if res.returncode == 1:
                return True
        except Exception:
            pass

    return False


# --- TASK EXECUTION ENGINE (INJECTION-SAFE) ---
def execute_task(task: Dict[str, Any]) -> Tuple[str, str]:
    """
    Ejecuta una tarea asignada de forma segura.
    Retorna una tupla: (action_name, status)
    """
    task_id = task.get("task_id")
    action = task.get("action", "")
    packages = task.get("packages", [])
    clean_env = get_clean_env()

    print(f"[*] Executing task {task_id}: {action} targeting {packages}")
    status, log_output = "failed", ""

    if action == "reboot":
        try:
            res = subprocess.run(
                ["shutdown", "-r", "+1", "Orbit Enterprise: Reboot requested by administrator"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                env=clean_env,
                timeout=10
            )
            log_output = res.stdout or "Reboot scheduled successfully for +1 minute."
            status = "success" if res.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            log_output = "Timeout executing shutdown command."
        except Exception as e:
            log_output = f"Exception executing reboot: {e}"

    elif action == "update" and packages:
        # Prevenir inyección de flags: no permitir paquetes que comiencen con '-'
        safe_pkgs = [
            p for p in packages 
            if p and not p.startswith("-") and all(c.isalnum() or c in "-._:+" for c in p)
        ]
        
        cmd: List[str] = []
        if shutil.which("dnf"):
            cmd = ["dnf", "update", "-y"] + safe_pkgs
        elif shutil.which("yum"):
            cmd = ["yum", "update", "-y"] + safe_pkgs
        elif shutil.which("apt-get"):
            cmd = ["apt-get", "install", "--only-upgrade", "-y"] + safe_pkgs

        if cmd and safe_pkgs:
            try:
                # Timeout generoso de 15 minutos para descargas e instalaciones masivas
                proc = subprocess.run(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    universal_newlines=True, 
                    env=clean_env, 
                    timeout=900
                )
                log_output = proc.stdout
                status = "success" if proc.returncode == 0 else "failed"
            except subprocess.TimeoutExpired:
                log_output = "Execution timed out (exceeded 15 minutes limit)."
            except Exception as e:
                log_output = f"Exception during update execution: {e}"
        else:
            log_output = "No valid packages or supported package manager found."
    else:
        log_output = f"Action '{action}' is invalid or missing valid package targets."

    final_message = log_output[-200:].replace('\n', ' ') if log_output else "No output produced."

    # 1. Enviar salida a la API
    payload = {"task_id": task_id, "status": status, "log": log_output}
    print(f"[*] Task {task_id} completed with status: {status}")
    api_request(f"/api/v1/agent/{NODE_UUID}/results", method="POST", payload=payload)

    # 2. Persistir localmente
    save_last_state(status, final_message)
    return action, status


# --- POST-ACTION TELEMETRY AND REPORTING ---
def send_node_report(reboot_in_progress: bool = False) -> None:
    """Inspects and reports current node state post-execution."""
    state = get_last_state()
    
    # Si acabamos de programar un reinicio exitoso, needs_reboot debe ser False
    needs_reboot = False if reboot_in_progress else check_needs_reboot()

    report = {
        "APP_VERSION": APP_VERSION,
        "fqdn": get_true_hostname(),
        "ip_address": get_ip_address(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "os_version": get_os_info(),
        "kernel_version": os.uname().release,
        "uptime_seconds": get_uptime(),
        "cpu_cores": os.cpu_count() or 1,
        "ram_total_mb": get_ram_mb(),
        "installed_packages": [],
        "available_updates": check_updates(),
        "needs_reboot": needs_reboot,
        "last_action_status": state.get("status", "none"),
        "last_action_message": state.get("message", ""),
        "tags": NODE_TAGS
    }

    print("[*] Sending consolidated telemetry and state report to server...")
    api_request(f"/api/v1/agent/{NODE_UUID}/report", method="POST", payload=report)


# --- ENTRYPOINT ---
def main() -> None:
    print(f"[+] Starting Orbit Agent v{APP_VERSION} (UUID: {NODE_UUID})")
    reboot_scheduled = False

    try:
        # 1. Obtener y procesar tareas
        response = api_request(f"/api/v1/agent/{NODE_UUID}/tasks", method="GET")
        if response and isinstance(response.get("tasks"), list):
            tasks = response["tasks"]
            if tasks:
                for task in tasks:
                    action, status = execute_task(task)
                    # Si la última tarea fue un reboot exitoso, anotamos el estado
                    if action == "reboot" and status == "success":
                        reboot_scheduled = True
            else:
                print("[*] No pending tasks assigned to this node.")

        # 2. Enviar reporte consolidado pasando el estado del reinicio
        send_node_report(reboot_in_progress=reboot_scheduled)

    except Exception as e:
        print(f"[ERROR] Unhandled exception in main execution loop: {e}", file=sys.stderr)

    print("[+] Execution finished successfully.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[ERROR] The Orbit Enterprise agent must run as root to manage patches.", file=sys.stderr)
        sys.exit(1)
    main()