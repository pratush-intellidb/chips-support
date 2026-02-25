#!/usr/bin/env python3
"""
IntelliDB PostgreSQL HA Setup on RHEL 9
Production-grade menu-driven console application.

Components: PostgreSQL 17, Patroni, etcd (3 node), HAProxy, firewalld, SELinux, systemd

Copyright (c) 2025. Use under your organization's license terms.
"""

from __future__ import annotations

__version__ = "1.0.0"

import argparse
import functools
import getpass
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import yaml
except ImportError:
    yaml = None

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
LOG_FILE = "/var/log/pg_ha_setup.log"
CONFIG_DIR = "/etc/pg_ha_setup"
ETCD_CONFIG_DIR = "/etc/etcd"
PATRONI_CONFIG_DIR = "/etc/patroni"
POSTGRESQL_DATA_DIR = "/var/lib/pgsql/17/data"
HAPROXY_CONFIG = "/etc/haproxy/haproxy.cfg"
REPLICATION_SLOT_NAME = "patroni"
REPLICATION_USER = "replicator"
SUPERUSER = "postgres"

# Port definitions with metadata
PORTS = {
    5432: {
        "name": "PostgreSQL",
        "purpose": "PostgreSQL client connections",
        "internal": "Primary database access for applications",
        "external": "Should NOT be exposed externally; use HAProxy instead",
        "security": "Bind to private IP; restrict via pg_hba.conf CIDR",
        "default_bind": "127.0.0.1,<private_ip>",
    },
    8008: {
        "name": "Patroni REST API",
        "purpose": "Patroni health checks and cluster state",
        "internal": "HAProxy and monitoring tools query leader status",
        "external": "Internal cluster only; never expose to internet",
        "security": "Bind to 127.0.0.1 and private network only",
        "default_bind": "127.0.0.1,<private_ip>",
    },
    2379: {
        "name": "etcd Client",
        "purpose": "etcd client communication (Patroni, HAProxy)",
        "internal": "Cluster members and clients connect for DCS",
        "external": "Cluster-internal only",
        "security": "Use etcd peer TLS in production; bind to private IP",
        "default_bind": "<private_ip>",
    },
    2380: {
        "name": "etcd Peer",
        "purpose": "etcd peer-to-peer replication",
        "internal": "etcd nodes replicate data between themselves",
        "external": "Must never be exposed; cluster nodes only",
        "security": "Bind to private IP; enable peer TLS",
        "default_bind": "<private_ip>",
    },
    5000: {
        "name": "HAProxy Frontend",
        "purpose": "HAProxy frontend for PostgreSQL connections",
        "internal": "Applications connect here for read/write routing",
        "external": "Can be exposed to app tier; restrict source IPs",
        "security": "Bind to specific interface; use firewall rules",
        "default_bind": "0.0.0.0 (configurable)",
    },
    7000: {
        "name": "Read Replica (Optional)",
        "purpose": "Optional dedicated read replica port",
        "internal": "Read-only connections when using port separation",
        "external": "Internal or app tier only",
        "security": "Configurable; bind to private IP if used",
        "default_bind": "Configurable",
    },
    5555: {
        "name": "IntelliDB PostgreSQL",
        "purpose": "IntelliDB Enterprise customized PostgreSQL 17 port",
        "internal": "Primary database access when using IntelliDB Enterprise",
        "external": "Should NOT be exposed externally; use HAProxy instead",
        "security": "Bind to private IP; restrict via pg_hba.conf CIDR",
        "default_bind": "<intellidb_private_ip>",
    },
}


# -----------------------------------------------------------------------------
# Retry Decorator
# -----------------------------------------------------------------------------
def retry(
    max_attempts: int = 3,
    delay: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Retry decorator for transient failures."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        time.sleep(delay)
            raise last_exc

        return wrapper

    return decorator


# -----------------------------------------------------------------------------
# Colored Console UI
# -----------------------------------------------------------------------------
class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @staticmethod
    def success(msg: str) -> str:
        return f"{Colors.GREEN}✓ {msg}{Colors.RESET}"

    @staticmethod
    def fail(msg: str) -> str:
        return f"{Colors.RED}✗ {msg}{Colors.RESET}"

    @staticmethod
    def warn(msg: str) -> str:
        return f"{Colors.YELLOW}⚠ {msg}{Colors.RESET}"

    @staticmethod
    def info(msg: str) -> str:
        return f"{Colors.CYAN}ℹ {msg}{Colors.RESET}"

    @staticmethod
    def header(msg: str) -> str:
        return f"{Colors.BOLD}{Colors.BLUE}{msg}{Colors.RESET}"


# -----------------------------------------------------------------------------
# Logging Setup
# -----------------------------------------------------------------------------
def setup_logging() -> logging.Logger:
    """Configure structured logging to file and console."""
    log = logging.getLogger("pg_ha_setup")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()

    # File handler
    try:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        log.addHandler(fh)
    except (PermissionError, OSError):
        fh = logging.StreamHandler(sys.stderr)
        fh.setLevel(logging.WARNING)
        log.addHandler(fh)

    # Console handler (less verbose)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(ch)

    return log


logger = setup_logging()


# -----------------------------------------------------------------------------
# Configuration Dataclass
# -----------------------------------------------------------------------------
@dataclass
class HAConfig:
    """Configuration for HA setup."""

    etcd_nodes: list[str] = field(default_factory=lambda: ["node1", "node2", "node3"])
    etcd_ips: list[str] = field(default_factory=lambda: ["192.168.1.11", "192.168.1.12", "192.168.1.13"])
    current_node: str = "node1"
    current_node_ip: str = "192.168.1.11"
    cluster_name: str = "pg-cluster"
    replication_password: str = ""
    postgres_password: str = ""
    haproxy_port: int = 5000
    read_replica_port: int = 7000
    haproxy_bind: str = "0.0.0.0"
    enable_tls: bool = False
    dry_run: bool = False

    # IntelliDB Enterprise (custom PostgreSQL 17) integration
    use_intellidb: bool = False
    intellidb_port: int = 5555
    intellidb_user: str = "intellidb"
    intellidb_db: str = "intellidb"
    intellidb_password: str = "IDBE@2025"
    intellidb_bin_dir: str = "/usr/pgsql-17/bin"
    intellidb_data_dir: str = "/var/lib/intellidb/data"


# -----------------------------------------------------------------------------
# Port Validation
# -----------------------------------------------------------------------------
class PortValidator:
    """Validate port availability and detect conflicts."""

    @staticmethod
    def is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
        """Check if port is in use using socket."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0
        except Exception:
            return False

    @staticmethod
    def get_listening_services() -> str:
        """Get active listening services via ss."""
        try:
            r = subprocess.run(
                ["ss", "-tulnp"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.stdout if r.returncode == 0 else ""
        except Exception as e:
            logger.warning("Could not run ss: %s", e)
            return ""

    @staticmethod
    def check_port_conflict(port: int) -> tuple[bool, str]:
        """Check if port has conflict. Returns (has_conflict, message)."""
        output = PortValidator.get_listening_services()
        # ss output: *:5432 or 0.0.0.0:5432 or 127.0.0.1:5432 or :::5432
        for line in output.splitlines():
            # Match port as separate number (avoid 5432 matching 15432)
            if re.search(rf"(?<![0-9]){port}(?![0-9])", line) and ("LISTEN" in line or ":" in line):
                return True, f"Port {port} in use: {line.strip()}"
        return False, ""

    @staticmethod
    def is_listening_on_all_interfaces(port: int) -> bool:
        """Check if port listens on 0.0.0.0 (all interfaces)."""
        output = PortValidator.get_listening_services()
        for line in output.splitlines():
            if re.search(rf"(?<![0-9]){port}(?![0-9])", line) and (":" in line or "*" in line):
                return "*" in line or "0.0.0.0" in line or ":::" in line
        return False

    @staticmethod
    def validate_connectivity(host: str, port: int, timeout: float = 2.0) -> bool:
        """Validate TCP connectivity to host:port."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((host, port))
                return True
        except (socket.error, socket.timeout, OSError):
            return False


# -----------------------------------------------------------------------------
# Firewall Manager
# -----------------------------------------------------------------------------
class FirewallManager:
    """Manage firewalld for HA stack ports."""

    def __init__(self, config: HAConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run or config.dry_run

    def _db_port(self) -> int:
        """Return database port (5432 for standard PostgreSQL, or IntelliDB port when enabled)."""
        try:
            if getattr(self.config, "use_intellidb", False):
                return int(getattr(self.config, "intellidb_port", 5555))
        except Exception:
            pass
        return 5432

    def _run_firewall_cmd(self, *args: str) -> tuple[bool, str]:
        """Execute firewall-cmd."""
        cmd = ["firewall-cmd"] + list(args)
        if self.dry_run:
            logger.info("[DRY-RUN] Would execute: %s", " ".join(cmd))
            return True, "Dry-run"
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            out = (r.stdout or "").strip() + (r.stderr or "").strip()
            return r.returncode == 0, out or ("OK" if r.returncode == 0 else "Failed")
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except FileNotFoundError:
            return False, "firewall-cmd not found (firewalld not installed?)"
        except Exception as e:
            return False, str(e)

    def is_firewalld_running(self) -> bool:
        """Check if firewalld service is active."""
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "firewalld"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return r.returncode == 0 and r.stdout.strip() == "active"
        except Exception:
            return False

    def add_port(self, port: int, protocol: str = "tcp") -> bool:
        """Add port to firewall permanently and reload."""
        ok, msg = self._run_firewall_cmd("--permanent", f"--add-port={port}/{protocol}")
        if not ok:
            logger.error("Failed to add port %s: %s", port, msg)
            return False
        ok2, msg2 = self._run_firewall_cmd("--reload")
        if not ok2:
            logger.error("Failed to reload firewall: %s", msg2)
            return False
        return True

    def remove_port(self, port: int, protocol: str = "tcp") -> bool:
        """Remove port from firewall."""
        self._run_firewall_cmd("--permanent", f"--remove-port={port}/{protocol}")
        self._run_firewall_cmd("--reload")
        return True

    def get_permanent_ports(self) -> list[int]:
        """List permanently open ports."""
        ok, out = self._run_firewall_cmd("--permanent", "--list-ports")
        if not ok:
            return []
        ports = []
        for p in out.split():
            if "/" in p:
                port_str = p.split("/")[0]
                try:
                    ports.append(int(port_str))
                except ValueError:
                    pass
        return ports

    def open_required_ports(self) -> bool:
        """Open all required HA stack ports."""
        db_port = self._db_port()
        required = [db_port, 8008, 2379, 2380, self.config.haproxy_port]
        if self.config.read_replica_port and self.config.read_replica_port != 5432:
            required.append(self.config.read_replica_port)
        required = list(dict.fromkeys(required))

        if not self.is_firewalld_running():
            logger.error("firewalld is not running. Start with: systemctl start firewalld")
            return False

        all_ok = True
        for port in required:
            if self.add_port(port):
                logger.info("Opened port %s", port)
            else:
                all_ok = False
        return all_ok

    def verify_ports_open(self, ports: Optional[list[int]] = None) -> dict[int, bool]:
        """Verify which ports are in permanent firewall rules."""
        if ports is None:
            ports = [self._db_port(), 8008, 2379, 2380, self.config.haproxy_port]
        permanent = set(self.get_permanent_ports())
        return {p: p in permanent for p in ports}


# -----------------------------------------------------------------------------
# SELinux Helper
# -----------------------------------------------------------------------------
class SELinuxHelper:
    """SELinux context and policy helpers."""

    @staticmethod
    def is_enforcing() -> bool:
        try:
            with open("/sys/fs/selinux/enforce", "r") as f:
                return f.read().strip() == "1"
        except Exception:
            return False

    @staticmethod
    def get_context(path: str) -> str:
        try:
            r = subprocess.run(
                ["ls", "-Z", path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout.strip().split()[-1] if path in r.stdout else ""
        except Exception:
            pass
        return ""

    @staticmethod
    def suggest_restorecon(paths: list[str]) -> list[str]:
        return [f"restorecon -Rv {p}" for p in paths]


# -----------------------------------------------------------------------------
# Main HA Setup Class
# -----------------------------------------------------------------------------
class PGHASetup:
    """PostgreSQL HA Setup orchestrator."""

    def __init__(self, config: Optional[HAConfig] = None, config_file: Optional[str] = None):
        self.config = config or HAConfig()
        if config_file:
            self._load_yaml_config(config_file)
        self.firewall = FirewallManager(self.config)
        self.port_validator = PortValidator()

    def _db_port(self) -> int:
        """Return effective PostgreSQL port (5432 or IntelliDB 5555)."""
        try:
            if getattr(self.config, "use_intellidb", False):
                return int(getattr(self.config, "intellidb_port", 5555))
        except Exception:
            pass
        return 5432

    def _load_yaml_config(self, path: str) -> None:
        """Load configuration from YAML file."""
        if not yaml:
            logger.warning("PyYAML not installed. Install with: pip install pyyaml")
            return
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data:
                return
            for key, val in data.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, val)
            self._validate_config()
            logger.info("Loaded config from %s", path)
        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error("Failed to load YAML config: %s", e)
            raise

    def _validate_config(self) -> None:
        """Validate configuration consistency."""
        if not isinstance(self.config.etcd_nodes, list) or not isinstance(self.config.etcd_ips, list):
            raise ValueError("etcd_nodes and etcd_ips must be YAML lists (e.g. [node1, node2, node3])")
        if len(self.config.etcd_nodes) != len(self.config.etcd_ips):
            raise ValueError(
                "etcd_nodes and etcd_ips must have the same length. "
                f"Got {len(self.config.etcd_nodes)} nodes and {len(self.config.etcd_ips)} IPs."
            )
        if self.config.current_node and self.config.current_node not in self.config.etcd_nodes:
            logger.warning(
                "current_node '%s' is not in etcd_nodes %s",
                self.config.current_node,
                self.config.etcd_nodes,
            )
        if len(self.config.etcd_nodes) != 3:
            logger.warning("etcd cluster should have 3 nodes for quorum. Got %d.", len(self.config.etcd_nodes))

    def _require_root(self) -> bool:
        """Ensure running as root."""
        if os.geteuid() != 0:
            print(Colors.fail("This application must be run as root."))
            logger.error("Not running as root")
            return False
        return True

    def _validate_rhel9(self) -> bool:
        """Validate RHEL 9 (or compatible)."""
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                content = f.read()
            if "rhel" in content.lower() or "centos" in content.lower() or "rocky" in content.lower():
                if "9" in content or "stream" in content.lower():
                    return True
            if "almalinux" in content.lower() and "9" in content:
                return True
            logger.warning("OS may not be RHEL 9 compatible. Proceed with caution.")
            return True  # Allow on other EL9-like
        except Exception as e:
            logger.error("Could not read os-release: %s", e)
            return False

    def _run_cmd(
        self,
        cmd: list[str],
        check: bool = True,
        capture: bool = True,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess:
        """Run command with optional dry-run."""
        if self.config.dry_run:
            logger.info("[DRY-RUN] Would run: %s", " ".join(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        try:
            return subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                timeout=timeout,
                check=check,
            )
        except subprocess.CalledProcessError as e:
            logger.error("Command failed: %s", e)
            raise
        except subprocess.TimeoutExpired:
            logger.error("Command timed out: %s", " ".join(cmd))
            raise

    # -------------------------------------------------------------------------
    # Menu Handlers
    # -------------------------------------------------------------------------

    def show_ports_and_firewall_menu(self) -> None:
        """Dedicated menu: Show Required Ports & Open Firewall Ports."""
        while True:
            print()
            print(Colors.header("=== Required Ports & Firewall Management ==="))
            print()
            self._display_port_documentation()
            print()
            print("Options:")
            print("  1. Open required ports (firewalld)")
            print("  2. Verify ports are open")
            print("  3. Close specific port")
            print("  4. Check if ports are already in use")
            print("  5. Show active listening services (ss -tulnp)")
            print("  6. Bind services to specific interface (guidance)")
            print("  7. Validate connectivity between nodes")
            print("  8. Back to main menu")
            print()
            try:
                choice = input("Select option [1-8]: ").strip() or "8"
            except EOFError:
                choice = "8"

            if choice == "1":
                self._open_ports_interactive()
            elif choice == "2":
                self._verify_ports_interactive()
            elif choice == "3":
                self._close_port_interactive()
            elif choice == "4":
                self._check_ports_in_use()
            elif choice == "5":
                self._show_listening_services()
            elif choice == "6":
                self._show_bind_guidance()
            elif choice == "7":
                self._validate_node_connectivity()
            elif choice == "8":
                break
            else:
                print(Colors.warn("Invalid option"))

    def _display_port_documentation(self) -> None:
        """Display port purpose, exposure, and security for each port."""
        print(Colors.header("Port Documentation"))
        print("-" * 70)
        ports_to_show = [self._db_port(), 8008, 2379, 2380, 5000]
        if self.config.haproxy_port != 5000:
            ports_to_show[4] = self.config.haproxy_port
        ports_to_show.append(self.config.read_replica_port)
        seen = set()
        for port in ports_to_show:
            if port in seen:
                continue
            seen.add(port)
            info = PORTS.get(port, PORTS.get(7000, {}))
            if port == self.config.read_replica_port and port != 7000:
                info = PORTS.get(7000, info)
            print(f"\n{Colors.BOLD}Port {port} - {info.get('name', 'Custom')}{Colors.RESET}")
            print(f"  Purpose: {info.get('purpose', 'N/A')}")
            print(f"  Internal: {info.get('internal', 'N/A')}")
            print(f"  External: {info.get('external', 'N/A')}")
            print(f"  Security: {info.get('security', 'N/A')}")
            print(f"  Default bind: {info.get('default_bind', 'N/A')}")

    def _open_ports_interactive(self) -> None:
        """Open required ports via firewalld."""
        if not self._require_root():
            return
        if not self.firewall.is_firewalld_running():
            print(Colors.fail("firewalld is not running."))
            print("Start with: systemctl start firewalld && systemctl enable firewalld")
            return
        db_port = self._db_port()
        ports = [db_port, 8008, 2379, 2380, self.config.haproxy_port]
        if self.config.read_replica_port and self.config.read_replica_port not in ports:
            ports.append(self.config.read_replica_port)
        print(f"Opening ports: {ports}")
        if self.firewall.open_required_ports():
            print(Colors.success("All ports opened and firewall reloaded."))
        else:
            print(Colors.fail("Some ports could not be opened. Check logs."))

    def _verify_ports_interactive(self) -> None:
        """Verify which ports are open."""
        ports = [self._db_port(), 8008, 2379, 2380, self.config.haproxy_port]
        result = self.firewall.verify_ports_open(ports)
        print()
        for port, open_ in result.items():
            status = Colors.success("OPEN") if open_ else Colors.fail("CLOSED")
            print(f"  Port {port}: {status}")

    def _close_port_interactive(self) -> None:
        """Close a specific port."""
        if not self._require_root():
            return
        try:
            port_str = input("Enter port to close: ").strip()
            port = int(port_str)
            if self.firewall.remove_port(port):
                print(Colors.success(f"Port {port} closed."))
            else:
                print(Colors.fail("Could not close port."))
        except ValueError:
            print(Colors.fail("Invalid port number"))

    def _check_ports_in_use(self) -> None:
        """Check if required ports are in use."""
        ports = [self._db_port(), 8008, 2379, 2380, self.config.haproxy_port]
        print()
        for port in ports:
            conflict, msg = self.port_validator.check_port_conflict(port)
            if conflict:
                print(Colors.warn(f"Port {port}: IN USE - {msg}"))
                if self.port_validator.is_listening_on_all_interfaces(port):
                    print(Colors.warn(f"  → Listening on 0.0.0.0. Consider binding to private IP."))
            else:
                print(Colors.success(f"Port {port}: Available"))

    def _show_listening_services(self) -> None:
        """Show ss -tulnp output."""
        output = self.port_validator.get_listening_services()
        print()
        print(Colors.header("Active listening services (ss -tulnp):"))
        print(output or "No output (ss not available)")

    def _validate_node_connectivity(self) -> None:
        """Validate TCP connectivity between cluster nodes."""
        print()
        print(Colors.header("Validate Connectivity Between Nodes"))
        print("-" * 50)
        nodes = list(zip(self.config.etcd_nodes, self.config.etcd_ips))
        ports_to_check = [
            (2379, "etcd client"),
            (2380, "etcd peer"),
            (self._db_port(), "PostgreSQL / IntelliDB"),
            (8008, "Patroni REST"),
        ]
        for node_name, ip in nodes:
            print(f"\nFrom this host to {node_name} ({ip}):")
            for port, desc in ports_to_check:
                ok = self.port_validator.validate_connectivity(ip, port)
                status = Colors.success("OK") if ok else Colors.fail("FAIL")
                print(f"  {desc} ({port}): {status}")

    def _show_bind_guidance(self) -> None:
        """Show guidance for binding services to specific interface."""
        print()
        print(Colors.header("Binding Services to Specific Interface"))
        print("-" * 60)
        print("""
PostgreSQL: Set listen_addresses in postgresql.conf
  listen_addresses = 'localhost,192.168.1.11'

Patroni: Set listen in patroni.yml
  restapi:
    listen: 192.168.1.11:8008

etcd: Set listen-client-urls and listen-peer-urls
  listen-client-urls: http://192.168.1.11:2379
  listen-peer-urls: http://192.168.1.11:2380

HAProxy: Set bind in haproxy.cfg
  bind 192.168.1.10:5000  # Use VIP or specific IP

Firewall: Use --add-source for restricted access
  firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="5432" protocol="tcp" accept'
""")

    def validate_system_requirements(self) -> None:
        """Validate system requirements."""
        print(Colors.header("\n=== System Requirements Validation ===\n"))
        checks = []

        # Root (check only; do not print "must be root" here)
        is_root = os.geteuid() == 0
        checks.append(("Root privileges", is_root))

        # RHEL 9
        checks.append(("RHEL 9 (or compatible)", self._validate_rhel9()))

        # firewalld
        checks.append(("firewalld running", self.firewall.is_firewalld_running()))

        # SELinux
        checks.append(("SELinux enforcing", SELinuxHelper.is_enforcing()))

        # Port conflicts
        ports_ok = True
        for port in [self._db_port(), 8008, 2379, 2380, self.config.haproxy_port]:
            conflict, _ = self.port_validator.check_port_conflict(port)
            if conflict:
                ports_ok = False
                break
        checks.append(("No port conflicts", ports_ok))

        # Security: PostgreSQL on all interfaces
        db_port = self._db_port()
        if self.port_validator.is_listening_on_all_interfaces(db_port):
            print(Colors.warn(f"  PostgreSQL ({db_port}) listening on 0.0.0.0 - consider binding to private IP"))

        # Python
        checks.append(("Python 3", sys.version_info >= (3, 6)))

        for name, ok in checks:
            status = Colors.success("OK") if ok else Colors.fail("FAIL")
            print(f"  {name}: {status}")

    @retry(max_attempts=2, delay=5.0, exceptions=(subprocess.CalledProcessError,))
    def install_packages(self) -> None:
        """Install required packages."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Installing Required Packages ===\n"))
        # NOTE: This function assumes all required RPMs are already available
        # in one of the following locations:
        #   1) In the current working directory as *.rpm files (e.g. you
        #      pre-downloaded them and copied them here), OR
        #   2) In local/internal yum repositories reachable from this server.
        #
        # It does NOT attempt to download anything from the public internet,
        # making it safe for offline/air-gapped environments.

        # 1) Prefer RPMs staged in current directory or ./rpms/ (Docker download output)
        rpm_files = sorted(str(p) for p in Path(".").glob("*.rpm"))
        rpms_dir = Path("rpms")
        if rpms_dir.is_dir():
            rpm_files.extend(sorted(str(p) for p in rpms_dir.glob("*.rpm")))
        rpm_files = list(dict.fromkeys(rpm_files))  # keep order, no duplicates
        if rpm_files:
            print(Colors.info("Installing local RPMs from current directory and ./rpms/:"))
            for f in rpm_files:
                print(f"  - {f}")
            try:
                self._run_cmd(["dnf", "install", "-y"] + rpm_files, timeout=300, check=False)
            except Exception as e:
                print(Colors.warn(f"Local RPM install failed (continuing to repo-based install): {e}"))

        # 2) Fallback to package names from configured local/internal repos
        rpms_dir = Path("rpms").resolve()
        packages = [
            "postgresql17-server",
            "postgresql17-contrib",
            "haproxy",
            "firewalld",
            "python3-pyyaml",
            "python3-psycopg2",
        ]
        have_etcd_tarball = rpms_dir.is_dir() and list(rpms_dir.glob("etcd-v*-linux-amd64.tar.gz"))
        have_patroni_wheels = (rpms_dir / "patroni-wheels").is_dir() and list((rpms_dir / "patroni-wheels").glob("patroni-*.whl"))
        if not have_etcd_tarball:
            packages.append("etcd")
        if not have_patroni_wheels:
            packages.append("patroni")
        cmd = ["dnf", "install", "-y"] + packages
        try:
            self._run_cmd(cmd, timeout=300)
            print(Colors.success("Packages installed."))
        except Exception as e:
            print(Colors.fail(f"Installation failed: {e}"))
            print(
                Colors.warn(
                    "Ensure all required RPMs are present in local/yum repos or in ./rpms/; "
                    "this setup does not download packages from the internet."
                )
            )

        # 3) Offline: install etcd from rpms/ tarball if present
        if rpms_dir.is_dir():
            etcd_tarballs = sorted(rpms_dir.glob("etcd-v*-linux-amd64.tar.gz"))
            if etcd_tarballs and not self.config.dry_run:
                tarball = etcd_tarballs[-1]
                print(Colors.info(f"Installing etcd from {tarball.name}"))
                try:
                    self._run_cmd(["tar", "xzf", str(tarball), "-C", "/tmp"], timeout=30)
                    extracted = list(Path("/tmp").glob("etcd-v*-linux-amd64"))
                    if extracted:
                        d = extracted[0]
                        bin_dir_path = Path("/usr/local/bin")
                        if not bin_dir_path.exists():
                            os.makedirs(bin_dir_path, exist_ok=True)
                        for name in ["etcd", "etcdctl"]:
                            exe = d / name
                            if exe.exists():
                                self._run_cmd(["cp", str(exe), "/usr/local/bin/"])
                                self._run_cmd(["chmod", "755", f"/usr/local/bin/{name}"])
                        shutil.rmtree(str(d), ignore_errors=True)
                        print(Colors.success("etcd binaries installed to /usr/local/bin"))
                    else:
                        print(Colors.warn("etcd tarball had unexpected layout"))
                except Exception as e:
                    logger.warning("etcd tarball install failed: %s", e)
                    print(Colors.warn("etcd tarball install failed; install manually (see rpms/README-OFFLINE.md)"))

            # 4) Offline: install Patroni from rpms/patroni-wheels if present
            wheels_dir = rpms_dir / "patroni-wheels"
            if wheels_dir.is_dir() and list(wheels_dir.glob("patroni-*.whl")):
                print(Colors.info("Installing Patroni from rpms/patroni-wheels"))
                try:
                    self._run_cmd([
                        "pip3", "install", "--no-index",
                        f"--find-links={wheels_dir}",
                        "patroni",
                    ], timeout=120, check=False)
                    print(Colors.success("Patroni installed from wheels"))
                except Exception as e:
                    logger.warning("Patroni wheels install failed: %s", e)
                    print(Colors.warn("Patroni wheels install failed; run: pip3 install --no-index --find-links=./rpms/patroni-wheels patroni"))

    def configure_etcd(self) -> None:
        """Configure etcd cluster."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Configuring etcd Cluster ===\n"))
        os.makedirs(ETCD_CONFIG_DIR, exist_ok=True)
        os.makedirs("/var/lib/etcd", exist_ok=True)

        initial_cluster = ",".join(
            f"{n}=http://{ip}:2380"
            for n, ip in zip(self.config.etcd_nodes, self.config.etcd_ips)
        )

        etcd_env = f"""# etcd for Patroni DCS
ETCD_NAME={self.config.current_node}
ETCD_DATA_DIR="/var/lib/etcd"
ETCD_LISTEN_CLIENT_URLS="http://{self.config.current_node_ip}:2379"
ETCD_LISTEN_PEER_URLS="http://{self.config.current_node_ip}:2380"
ETCD_INITIAL_ADVERTISE_CLIENT_URLS="http://{self.config.current_node_ip}:2379"
ETCD_INITIAL_CLUSTER="{initial_cluster}"
ETCD_INITIAL_CLUSTER_TOKEN="pg-ha-etcd"
ETCD_INITIAL_CLUSTER_STATE="new"
"""

        env_file = "/etc/etcd/etcd.conf"
        if not self.config.dry_run:
            with open(env_file, "w") as f:
                f.write(etcd_env)
        logger.info("Wrote %s", env_file)

        # systemd: use override if etcd.service exists (from RPM), else create full unit (tarball install)
        etcd_unit = "/etc/systemd/system/etcd.service"
        if not self.config.dry_run:
            if not os.path.exists(etcd_unit):
                unit_content = """[Unit]
Description=etcd - distributed key-value store for Patroni DCS
After=network.target

[Service]
Type=notify
EnvironmentFile=-/etc/etcd/etcd.conf
ExecStart=/usr/local/bin/etcd
Restart=on-failure
RestartSec=10s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
"""
                with open(etcd_unit, "w") as f:
                    f.write(unit_content)
                logger.info("Created %s (etcd from tarball)", etcd_unit)
            else:
                override_dir = "/etc/systemd/system/etcd.service.d"
                os.makedirs(override_dir, exist_ok=True)
                override_content = f"""[Service]
EnvironmentFile={env_file}
"""
                override_file = f"{override_dir}/environment.conf"
                with open(override_file, "w") as f:
                    f.write(override_content)
            # Reload and manage etcd service; handle failures gracefully
            self._run_cmd(["systemctl", "daemon-reload"], check=False)
            self._run_cmd(["systemctl", "enable", "etcd"], check=False)
            result = self._run_cmd(["systemctl", "start", "etcd"], check=False)
            if result.returncode != 0:
                print(Colors.fail("Failed to start etcd service (systemctl start etcd)."))
                if result.stderr:
                    print(result.stderr.strip())
                print(
                    Colors.warn(
                        "Check etcd status with:\n"
                        "  systemctl status etcd -l\n"
                        "  journalctl -u etcd -n 50"
                    )
                )
            else:
                print(Colors.success("etcd configured and service started. Repeat on all 3 nodes."))
        else:
            print(Colors.success("etcd configuration written (dry-run)."))

    def install_postgresql17(self) -> None:
        """Install and initialize PostgreSQL 17."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Installing PostgreSQL 17 ===\n"))
        self._run_cmd(["dnf", "install", "-y", "postgresql17-server", "postgresql17-contrib"], timeout=120)
        os.makedirs(POSTGRESQL_DATA_DIR, exist_ok=True)
        # Ensure data directory is owned by postgres so Patroni / postgres can write to it
        self._run_cmd(["chown", "-R", "postgres:postgres", POSTGRESQL_DATA_DIR], check=False)
        # Patroni will initialize; we don't run postgresql-17-setup
        print(Colors.success("PostgreSQL 17 packages installed."))

    def configure_replication(self) -> None:
        """Configure replication user and slot (handled by Patroni)."""
        print(Colors.header("\n=== PostgreSQL Replication Configuration ===\n"))
        print("Replication is managed by Patroni. Ensure:")
        print("  - replication_password is set in config")
        print("  - Patroni creates replication slot automatically")
        print("  - pg_hba.conf allows replication from replica IPs")
        if not self.config.replication_password:
            print(Colors.warn("replication_password not set. Set in config or YAML."))
        print(Colors.success("Replication config guidance displayed."))

    def _prompt_password(self, prompt: str, default: str = "") -> str:
        """Prompt for password with masking."""
        if default and not self.config.dry_run:
            try:
                p = getpass.getpass(prompt=f"{prompt} [hidden]: ")
                return p if p else default
            except (EOFError, KeyboardInterrupt):
                return default
        return default or "CHANGE_ME"

    def configure_patroni(self) -> None:
        """Install and configure Patroni."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Configuring Patroni ===\n"))

        # Allow selecting IntelliDB Enterprise mode interactively if not set via YAML
        if not self.config.use_intellidb:
            try:
                choice = input(
                    "Use IntelliDB Enterprise mode (existing PostgreSQL 17 on port 5555, user 'intellidb')? [y/N]: "
                ).strip().lower()
            except EOFError:
                choice = "n"
            if choice == "y":
                self.config.use_intellidb = True
                print(Colors.info("IntelliDB Enterprise mode enabled for Patroni and HAProxy."))

        os.makedirs(PATRONI_CONFIG_DIR, exist_ok=True)

        if not self.config.replication_password:
            self.config.replication_password = self._prompt_password("Replication user password", "CHANGE_ME")
        if not self.config.postgres_password:
            # For IntelliDB mode, default to the known IntelliDB password
            default_pw = self.config.intellidb_password if self.config.use_intellidb else "CHANGE_ME"
            prompt = "IntelliDB superuser password" if self.config.use_intellidb else "PostgreSQL superuser password"
            self.config.postgres_password = self._prompt_password(prompt, default_pw)

        etcd_hosts = ",".join(f"http://{ip}:2379" for ip in self.config.etcd_ips)
        repl_pass = self.config.replication_password or "CHANGE_ME"
        super_pass = self.config.postgres_password or "CHANGE_ME"

        # Standard PostgreSQL vs IntelliDB mode
        if self.config.use_intellidb:
            db_port = self.config.intellidb_port
            bin_dir = self.config.intellidb_bin_dir
            data_dir = self.config.intellidb_data_dir
            superuser_name = self.config.intellidb_user
        else:
            db_port = 5432
            bin_dir = "/usr/pgsql-17/bin"
            data_dir = POSTGRESQL_DATA_DIR
            superuser_name = SUPERUSER

        patroni_yml = f"""# Patroni configuration for {self.config.cluster_name}
scope: {self.config.cluster_name}
name: {self.config.current_node}

restapi:
  listen: {self.config.current_node_ip}:8008
  connect_address: {self.config.current_node_ip}:8008

etcd:
  hosts: {etcd_hosts}

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true
      use_slots: true
  initdb:
    - encoding: UTF8
    - data-checksums
  pg_hba:
    - host replication replicator 0.0.0.0/0 md5
    - host all all 0.0.0.0/0 md5
  users:
    {REPLICATION_USER}:
      password: {repl_pass}
      options:
        - replication
    {superuser_name}:
      password: {super_pass}
      options:
        - superuser
        - createdb
        - createrole

postgresql:
  listen: {self.config.current_node_ip}:{db_port}
  connect_address: {self.config.current_node_ip}:{db_port}
  data_dir: {data_dir}
  bin_dir: {bin_dir}
  pgpass: /tmp/pgpass
  authentication:
    replication:
      username: {REPLICATION_USER}
      password: {repl_pass}
    superuser:
      username: {superuser_name}
      password: {super_pass}
  parameters:
    max_connections: "200"
    shared_buffers: "256MB"
    dynamic_shared_memory_type: "posix"
    wal_level: replica
    max_wal_senders: "10"
    max_replication_slots: "10"
    hot_standby: "on"
"""

        cfg_path = f"{PATRONI_CONFIG_DIR}/patroni.yml"
        if not self.config.dry_run:
            with open(cfg_path, "w") as f:
                f.write(patroni_yml)
            try:
                os.chmod(cfg_path, 0o600)
            except OSError as e:
                logger.warning("Could not restrict patroni.yml permissions: %s", e)
        print(Colors.success(f"Patroni config written to {cfg_path}"))
        print(Colors.warn("Review pg_hba CIDR - 0.0.0.0/0 is permissive. Restrict in production."))

    def configure_haproxy(self) -> None:
        """Configure HAProxy for read/write routing."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Configuring HAProxy ===\n"))

        db_port = self.config.intellidb_port if self.config.use_intellidb else 5432
        backends = "\n".join(
            f"    server {n} {ip}:{db_port} check port 8008"
            for n, ip in zip(self.config.etcd_nodes, self.config.etcd_ips)
        )

        haproxy_cfg = f"""# HAProxy for PostgreSQL HA - {self.config.cluster_name}
global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

defaults
    log     global
    mode    tcp
    option  tcplog
    option  dontlognull
    timeout connect 5000
    timeout client  50000
    timeout server  50000

frontend pg_frontend
    bind {self.config.haproxy_bind}:{self.config.haproxy_port}
    default_backend pg_write

backend pg_write
    option httpchk
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
{backends}
"""

        if not self.config.dry_run:
            with open(HAPROXY_CONFIG, "w") as f:
                f.write(haproxy_cfg)
            # Validate config before reload to avoid taking down HAProxy
            r = subprocess.run(
                ["haproxy", "-c", "-f", HAPROXY_CONFIG],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode != 0:
                print(Colors.fail("HAProxy config validation failed:"))
                print(r.stderr or r.stdout or "Unknown error")
                logger.error("HAProxy config invalid: %s", r.stderr or r.stdout)
                return
            self._run_cmd(["systemctl", "reload", "haproxy"], check=False)
        print(Colors.success(f"HAProxy configured at {self.config.haproxy_bind}:{self.config.haproxy_port}"))

    def configure_selinux(self) -> None:
        """Configure SELinux policies."""
        if not self._require_root():
            return
        print(Colors.header("\n=== SELinux Configuration ===\n"))
        paths = [POSTGRESQL_DATA_DIR, "/var/lib/etcd", "/etc/patroni", "/var/log/patroni"]
        try:
            for p in paths:
                if os.path.exists(p):
                    self._run_cmd(["restorecon", "-Rv", p], check=False)
            print(Colors.success("SELinux contexts applied."))
        except FileNotFoundError:
            print(Colors.warn("restorecon not found (minimal install?). Skipped."))
        print(Colors.info("If Patroni/etcd fail, check: ausearch -m avc -ts recent"))

    def initialize_cluster(self) -> None:
        """Initialize the cluster (first node bootstrap)."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Initialize Cluster ===\n"))
        print("Ensure etcd is running on all 3 nodes.")
        print("Start Patroni on first node: systemctl start patroni")
        print("Then start Patroni on remaining nodes.")
        if not self.config.dry_run:
            self._run_cmd(["systemctl", "start", "patroni"], check=False)
        print(Colors.success("Patroni start attempted."))

    def check_cluster_health(self) -> None:
        """Check cluster health."""
        print(Colors.header("\n=== Cluster Health Check ===\n"))
        try:
            r = subprocess.run(
                ["patronictl", "-c", f"{PATRONI_CONFIG_DIR}/patroni.yml", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            print(r.stdout or r.stderr or "No output")
            if r.returncode == 0:
                print(Colors.success("Cluster status retrieved."))
            else:
                print(Colors.warn("patronictl may not be available or cluster not ready."))
        except Exception as e:
            print(Colors.fail(f"Health check failed: {e}"))

    def simulate_failover(self) -> None:
        """Simulate failover."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Simulate Failover ===\n"))
        print("This will trigger a manual failover.")
        try:
            confirm = input("Type 'yes' to confirm: ").strip().lower()
        except EOFError:
            confirm = "no"
        if confirm != "yes":
            print("Aborted.")
            return
        try:
            self._run_cmd([
                "patronictl", "-c", f"{PATRONI_CONFIG_DIR}/patroni.yml",
                "failover", self.config.cluster_name,
                "--force",
            ], timeout=30)
            print(Colors.success("Failover initiated."))
        except Exception as e:
            print(Colors.fail(f"Failover failed: {e}"))

    def backup_pg_basebackup(self) -> None:
        """Backup using pg_basebackup."""
        print(Colors.header("\n=== Backup Using pg_basebackup ===\n"))
        backup_dir = "/var/lib/pgsql/backups"
        os.makedirs(backup_dir, exist_ok=True)
        if self.config.dry_run:
            target = f"{backup_dir}/basebackup_YYYYMMDD_HHMMSS"
        else:
            target = f"{backup_dir}/basebackup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        cmd = [
            "sudo", "-u", "postgres",
            "/usr/pgsql-17/bin/pg_basebackup",
            "-h", self.config.current_node_ip,
            "-D", target,
            "-U", REPLICATION_USER,
            "-Ft", "-z", "-Xs", "-P",
        ]
        print("Example (run as root or with sudo):")
        print("  " + " ".join(cmd))
        print("Or connect via HAProxy for leader: -h <haproxy_ip> -p", self.config.haproxy_port)
        if not self.config.dry_run:
            try:
                self._run_cmd(cmd, timeout=600, check=False)
                print(Colors.success(f"Backup directory: {target}"))
            except Exception as e:
                print(Colors.warn(f"pg_basebackup failed (cluster may be down or replication user not ready): {e}"))

    def full_automated_setup(self) -> None:
        """Run full automated setup."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Full Automated Setup ===\n"))
        steps = [
            ("Validate requirements", self.validate_system_requirements),
            ("Open firewall ports", self._open_ports_interactive),
            ("Install packages", self.install_packages),
            ("Configure etcd", self.configure_etcd),
            ("Install PostgreSQL", self.install_postgresql17),
            ("Configure replication", self.configure_replication),
            ("Configure Patroni", self.configure_patroni),
            ("Configure HAProxy", self.configure_haproxy),
            ("Configure SELinux", self.configure_selinux),
            ("Initialize cluster", self.initialize_cluster),
        ]
        for name, fn in steps:
            print(f"\n--- {name} ---")
            try:
                fn()
            except Exception as e:
                print(Colors.fail(f"Step failed: {e}"))
                try:
                    reply = input("Continue? [y/N]: ").strip().lower()
                except EOFError:
                    reply = "n"
                if reply != "y":
                    break
        print(Colors.success("\nAutomated setup complete. Verify with 'Check Cluster Health'."))

    def uninstall_ha_stack(self) -> None:
        """Uninstall HA stack."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Uninstall HA Stack ===\n"))
        try:
            confirm = input("Type 'UNINSTALL' to confirm: ").strip()
        except EOFError:
            confirm = ""
        if confirm != "UNINSTALL":
            print("Aborted.")
            return
        for svc in ["patroni", "haproxy", "etcd"]:
            self._run_cmd(["systemctl", "stop", svc], check=False)
            self._run_cmd(["systemctl", "disable", svc], check=False)
        self._run_cmd(["dnf", "remove", "-y", "patroni", "etcd", "haproxy", "postgresql17-server"], check=False, timeout=120)
        print(Colors.warn("Data in /var/lib/pgsql and /var/lib/etcd preserved. Remove manually if needed."))

    def security_hardening_menu(self) -> None:
        """Display security hardening recommendations."""
        print(Colors.header("\n=== Security Hardening ===\n"))
        print("""
1. PostgreSQL:
   - Set listen_addresses to specific IPs, not *
   - Restrict pg_hba.conf to application CIDR (e.g., 10.0.0.0/8)
   - Use strong passwords for superuser and replication

2. HAProxy:
   - Bind to specific interface, not 0.0.0.0 if possible
   - Use firewall rules to restrict source IPs

3. etcd:
   - Enable peer TLS (--peer-client-cert-auth)
   - Enable client TLS (--client-cert-auth)
   - Bind to private IP only

4. Patroni REST API:
   - Bind to 127.0.0.1 and private IP only
   - Never expose 8008 to internet

5. TLS (optional):
   - Use self-signed or CA certs for PostgreSQL
   - Configure ssl_cert_file, ssl_key_file in postgresql.conf
   - Run option 17 from main menu to generate self-signed certs
""")

    def enable_tls_self_signed(self) -> None:
        """Generate self-signed TLS certs for PostgreSQL."""
        if not self._require_root():
            return
        print(Colors.header("\n=== Enable TLS (Self-Signed) ===\n"))
        cert_dir = "/var/lib/pgsql/17/certs"
        os.makedirs(cert_dir, exist_ok=True)
        key_file = f"{cert_dir}/server.key"
        cert_file = f"{cert_dir}/server.crt"
        cmd = [
            "openssl", "req", "-new", "-x509", "-days", "365", "-nodes",
            "-text", "-out", cert_file, "-keyout", key_file,
            "-subj", f"/CN=postgresql-{self.config.cluster_name}"
        ]
        if not self.config.dry_run:
            self._run_cmd(cmd)
            self._run_cmd(["chown", "-R", "postgres:postgres", cert_dir])
            self._run_cmd(["chmod", "600", key_file])
        print(Colors.success(f"Certificates written to {cert_dir}"))
        print("Add to postgresql.conf (via Patroni parameters):")
        print(f"  ssl = on")
        print(f"  ssl_cert_file = '{cert_file}'")
        print(f"  ssl_key_file = '{key_file}'")

    def run_menu(self) -> None:
        """Main menu loop."""
        if not self._require_root():
            return
        if not self._validate_rhel9():
            print(Colors.warn("RHEL 9 validation failed. Proceed with caution."))

        while True:
            print()
            print(Colors.header("=== IntelliDB PostgreSQL 17 HA Setup on RHEL 9 ==="))
            print()
            print("  1.  Validate System Requirements")
            print("  2.  Show Required Ports & Open Firewall Ports")
            print("  3.  Install Required Packages")
            print("  4.  Configure etcd Cluster")
            print("  5.  Install PostgreSQL 17")
            print("  6.  Configure PostgreSQL Replication")
            print("  7.  Install & Configure Patroni")
            print("  8.  Configure HAProxy")
            print("  9.  Configure SELinux Policies")
            print("  10. Initialize Cluster")
            print("  11. Check Cluster Health")
            print("  12. Simulate Failover")
            print("  13. Backup Using pg_basebackup")
            print("  14. Full Automated Setup")
            print("  15. Uninstall HA Stack")
            print("  16. Security Hardening (Info)")
            print("  17. Enable TLS (Self-Signed Certs)")
            print("  18. Exit")
            print()
            try:
                choice = input("Select option [1-18]: ").strip()
            except EOFError:
                choice = "18"

            if choice == "1":
                self.validate_system_requirements()
            elif choice == "2":
                self.show_ports_and_firewall_menu()
            elif choice == "3":
                self.install_packages()
            elif choice == "4":
                self.configure_etcd()
            elif choice == "5":
                self.install_postgresql17()
            elif choice == "6":
                self.configure_replication()
            elif choice == "7":
                self.configure_patroni()
            elif choice == "8":
                self.configure_haproxy()
            elif choice == "9":
                self.configure_selinux()
            elif choice == "10":
                self.initialize_cluster()
            elif choice == "11":
                self.check_cluster_health()
            elif choice == "12":
                self.simulate_failover()
            elif choice == "13":
                self.backup_pg_basebackup()
            elif choice == "14":
                self.full_automated_setup()
            elif choice == "15":
                self.uninstall_ha_stack()
            elif choice == "16":
                self.security_hardening_menu()
            elif choice == "17":
                self.enable_tls_self_signed()
            elif choice == "18":
                print("Exiting.")
                break
            else:
                print(Colors.warn("Invalid option"))


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="IntelliDB PostgreSQL HA Setup on RHEL 9 (Patroni, etcd, HAProxy)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Log file: %s" % LOG_FILE,
    )
    parser.add_argument("--config", "-c", help="YAML configuration file path")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without making changes")
    parser.add_argument("--non-interactive", action="store_true", help="Use with --config; run validation and port menu only")
    parser.add_argument("--version", "-v", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args()

    config = HAConfig(dry_run=args.dry_run)
    try:
        app = PGHASetup(config=config, config_file=args.config)
    except FileNotFoundError as e:
        print(Colors.fail(str(e)))
        sys.exit(1)
    except ValueError as e:
        print(Colors.fail(str(e)))
        sys.exit(1)

    try:
        if args.non_interactive and args.config:
            app.validate_system_requirements()
            app.show_ports_and_firewall_menu()
        else:
            app.run_menu()
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
