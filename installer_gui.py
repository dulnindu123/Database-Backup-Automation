"""
Graphical Installation Wizard for Enterprise Database Cloud Backup (v4.1.0)
Streamlined, zero-friction installer with working Cloud Run Broker URL configuration,
live reachability validation, and automatic zero-trust key/token provisioning.
"""
import os
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

from version import (
    APP_VERSION,
    INSTALLER_VERSION,
    APP_NAME,
    EXE_NAME,
    DEFAULT_INSTALL_SUBDIR,
    PROGRAM_DATA_DIR,
    DEFAULT_TASK_NAME,
)
from preflight import run_preflight_suite, validate_broker_url_security, probe_broker_health
from broker_client import _protect_dpapi_native

# Configure theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def get_bundle_dir():
    """Resolves directory containing the installer executable and payload files."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


class InstallerApp(ctk.CTk):
    """Zero-Friction Installation Wizard for Database Cloud Backup System."""
    def __init__(self):
        super().__init__()
        
        self.title(f"{APP_NAME} Setup - v{INSTALLER_VERSION}")
        self.geometry("620x680")
        self.resizable(False, False)

        self.bundle_dir = get_bundle_dir()
        candidates = [
            os.path.join(self.bundle_dir, "AppFiles"),
            os.path.join(self.bundle_dir, "DatabaseBackupApp"),
            os.path.join(self.bundle_dir, "dist", "DatabaseBackupApp"),
            os.path.join(self.bundle_dir, "dist", "AppFiles"),
            self.bundle_dir
        ]
        self.source_app_dir = None
        for candidate in candidates:
            if os.path.exists(os.path.join(candidate, EXE_NAME)):
                self.source_app_dir = candidate
                break
        if not self.source_app_dir:
            self.source_app_dir = os.path.join(self.bundle_dir, "AppFiles")

        # Standard Production Target: Program Files (Admin) & ProgramData (Requirement D)
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        self.target_dir = os.path.join(pf, DEFAULT_INSTALL_SUBDIR)
        self.data_dir = PROGRAM_DATA_DIR

        self.manifest_data = None
        self.manifest_verified = False
        self.manifest_tampered = False
        self.manifest_error = ""
        self.customer_slug = ""
        self.telemetry_url = ""

        # Check for Ed25519-signed manifest in package (Requirement 2)
        from preflight import validate_signed_manifest
        m_data, m_res = validate_signed_manifest(package_dir=self.bundle_dir)
        if m_res.code == "ERR_MANIFEST_TAMPERED":
            self.manifest_tampered = True
            self.manifest_error = m_res.message
        elif m_res.passed and m_data:
            self.manifest_data = m_data
            self.manifest_verified = True
            self.customer_slug = m_data.get("customer_slug", "")
            self.broker_url = m_data.get("broker_url", "")
            self.telemetry_url = m_data.get("telemetry_url", "")
            self.raw_token = m_data.get("initial_token", "")

        # Automatically resolve existing configured Broker URL and Token if not in manifest
        if not self.broker_url:
            self.broker_url = self._auto_resolve_broker_url()
        if not self.raw_token:
            self.raw_token = self._auto_resolve_raw_token()

        # Apply branding icon if available
        ico = os.path.join(self.bundle_dir, "app_icon.ico")
        if sys.platform.startswith("win") and os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_ui()
        self.after(300, self._test_broker_health)

    def _auto_resolve_broker_url(self):
        """Discovers existing configured Upload Broker URL if deployed or packaged."""
        if self.manifest_verified and self.broker_url:
            return self.broker_url

        # 1. Check existing config on client PC (upgrade scenario)
        for chk in [os.path.join(self.data_dir, "config.json"), os.path.join(self.target_dir, "config.json")]:
            if os.path.exists(chk):
                try:
                    with open(chk, 'r', encoding='utf-8') as f:
                        c = json.load(f)
                        b_url = c.get("BROKER_URL", "").strip()
                        if b_url and (b_url.startswith("https://") or b_url.startswith("http://")):
                            return b_url
                except Exception:
                    pass

        # 2. Check config in AppFiles package
        for base in [self.bundle_dir, os.path.join(self.bundle_dir, "AppFiles"), os.getcwd()]:
            cfg_p = os.path.join(base, "config.json")
            if os.path.exists(cfg_p):
                try:
                    with open(cfg_p, 'r', encoding='utf-8') as f:
                        c = json.load(f)
                        b_url = c.get("BROKER_URL", "").strip()
                        if b_url and (b_url.startswith("https://") or b_url.startswith("http://")):
                            return b_url
                except Exception:
                    pass

        # 3. Environment variable
        env_url = os.environ.get("BROKER_URL", "").strip() or os.environ.get("CLOUD_RUN_BROKER_URL", "").strip()
        if env_url:
            return env_url

        return ""

    def _auto_resolve_raw_token(self):
        """Discovers raw token if provided via signed manifest or existing token.dpapi."""
        if self.manifest_verified and self.raw_token:
            return self.raw_token
        from preflight import decrypt_token_dpapi
        t_str, _ = decrypt_token_dpapi(data_dir=self.data_dir, target_dir=self.target_dir)
        return t_str or ""

    def _build_ui(self):
        # Header Banner
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("#1f2937", "#111827"), height=75)
        header.pack(fill="x", side="top")

        ctk.CTkLabel(
            header,
            text=f"Database Cloud Backup Setup (v{INSTALLER_VERSION})",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w", padx=25, pady=(14, 2))

        ctk.CTkLabel(
            header,
            text="Automated One-Click Setup - Zero-Trust Disaster Recovery",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=25)

        # Body Container
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=25, pady=15)

        # Tampered or Verified Manifest Status Banner
        if self.manifest_tampered:
            err_frame = ctk.CTkFrame(body, fg_color="#7f1d1d", corner_radius=6)
            err_frame.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(
                err_frame,
                text=f"⚠️ TAMPERED PACKAGE: {self.manifest_error}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#fca5a5"
            ).pack(padx=10, pady=8)
        elif self.manifest_verified:
            v_frame = ctk.CTkFrame(body, fg_color="#064e3b", corner_radius=6)
            v_frame.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(
                v_frame,
                text=f"🔒 AUTHENTIC ED25519 SIGNED PACKAGE ({self.customer_slug.upper()}) - ZERO TYPING REQUIRED",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#6ee7b7"
            ).pack(padx=10, pady=6)

        # 1. Target Directory Section
        ctk.CTkLabel(body, text="Installation Destination:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        dir_frame = ctk.CTkFrame(body, fg_color="transparent")
        dir_frame.pack(fill="x", pady=(0, 12))

        self.target_dir_var = tk.StringVar(value=self.target_dir)
        self.entry_dir = ctk.CTkEntry(dir_frame, textvariable=self.target_dir_var, font=ctk.CTkFont(size=11), height=32)
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            dir_frame, text="Browse...", font=ctk.CTkFont(size=11, weight="bold"),
            width=80, height=32, fg_color="#374151", hover_color="#4b5563",
            command=self._browse_directory
        ).pack(side="right")

        # 2. Cloud Run Broker Card
        broker_card = ctk.CTkFrame(body, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        broker_card.pack(fill="x", pady=(0, 15))

        card_top = ctk.CTkFrame(broker_card, fg_color="transparent")
        card_top.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            card_top,
            text="CLOUD RUN UPLOAD BROKER ENDPOINT" + (" (LOCKED BY SIGNED MANIFEST)" if self.manifest_verified else ""),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399" if self.manifest_verified else "#60a5fa"
        ).pack(side="left")

        # Auto-detect & Test button
        ctk.CTkButton(
            card_top,
            text="⚡ Auto-Fetch & Test",
            font=ctk.CTkFont(size=10, weight="bold"),
            width=140,
            height=26,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._refresh_and_test_broker
        ).pack(side="right")

        # Broker URL Entry Field (clean, editable or locked)
        self.broker_url_var = tk.StringVar(value=self.broker_url)
        self.entry_broker = ctk.CTkEntry(
            broker_card,
            textvariable=self.broker_url_var,
            placeholder_text="Enter Cloud Run Broker URL (e.g. https://upload-broker-xxx.run.app)",
            font=ctk.CTkFont(family="Consolas", size=11),
            height=30
        )
        self.entry_broker.pack(fill="x", padx=12, pady=(2, 4))
        if self.manifest_verified and self.broker_url:
            self.entry_broker.configure(state="disabled")

        # Token Entry Field
        ctk.CTkLabel(
            broker_card,
            text="MACHINE AUTHENTICATION TOKEN (DPAPI ENCRYPTED):" + (" (PRE-SEALED)" if self.manifest_verified and self.raw_token else ""),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=12, pady=(2, 1))

        self.token_var = tk.StringVar(value=self.raw_token)
        self.entry_token = ctk.CTkEntry(
            broker_card,
            textvariable=self.token_var,
            placeholder_text="Enter PC Token (e.g. pc-id.secret) or leave blank if pre-packaged",
            font=ctk.CTkFont(family="Consolas", size=11),
            height=30
        )
        self.entry_token.pack(fill="x", padx=12, pady=(1, 4))
        if self.manifest_verified and self.raw_token:
            self.entry_token.configure(state="disabled")

        # Status indicator badge
        self.lbl_broker_status = ctk.CTkLabel(
            broker_card,
            text="● Probing broker connectivity...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f59e0b",
            anchor="w"
        )
        self.lbl_broker_status.pack(anchor="w", padx=12, pady=(0, 10))

        # 3. Installation Options
        ctk.CTkLabel(body, text="Installation Options:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        
        self.cb_desktop = ctk.CTkCheckBox(body, text="Create Desktop Shortcut", font=ctk.CTkFont(size=12))
        self.cb_desktop.pack(anchor="w", pady=3)
        self.cb_desktop.select()

        self.cb_startmenu = ctk.CTkCheckBox(body, text="Create Start Menu Shortcut", font=ctk.CTkFont(size=12))
        self.cb_startmenu.pack(anchor="w", pady=3)
        self.cb_startmenu.select()

        self.cb_schedule = ctk.CTkCheckBox(body, text="Enable Automatic Monday 2:00 AM Backup Schedule", font=ctk.CTkFont(size=12))
        self.cb_schedule.pack(anchor="w", pady=3)
        self.cb_schedule.select()

        self.cb_launch = ctk.CTkCheckBox(body, text="Launch Application after setup completes", font=ctk.CTkFont(size=12))
        self.cb_launch.pack(anchor="w", pady=3)
        self.cb_launch.select()

        # Progress bar & status
        self.progress = ctk.CTkProgressBar(body, width=550, height=8)
        self.progress.pack(pady=(12, 4))
        self.progress.set(0)

        self.status_lbl = ctk.CTkLabel(body, text="Ready to install.", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self.status_lbl.pack(anchor="w")

        # Footer Buttons
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=25, pady=(0, 15))

        self.btn_install = ctk.CTkButton(
            footer, text="Install Now", font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669", hover_color="#047857", height=38, width=130, command=self._do_install
        )
        self.btn_install.pack(side="right", padx=(10, 0))

        self.btn_cancel = ctk.CTkButton(
            footer, text="Cancel", font=ctk.CTkFont(size=13),
            fg_color="#374151", hover_color="#4b5563", height=38, width=90, command=self.destroy
        )
        self.btn_cancel.pack(side="right")

    def _browse_directory(self):
        chosen = filedialog.askdirectory(title="Select Installation Directory", initialdir=self.target_dir_var.get())
        if chosen:
            self.target_dir = os.path.normpath(chosen)
            self.target_dir_var.set(self.target_dir)

    def _refresh_and_test_broker(self):
        """Refreshes the auto-detected broker URL and tests its connectivity."""
        self.lbl_broker_status.configure(text="● Auto-detecting working broker...", text_color="#f59e0b")
        self.update()
        detected = self._auto_resolve_broker_url()
        if detected:
            self.broker_url_var.set(detected)
        self._test_broker_health()

    def _test_broker_health(self):
        """Pings the Upload Broker /healthz or connection probe using shared preflight."""
        url = self.broker_url_var.get().strip()
        token = self.token_var.get().strip()
        if not url:
            self.lbl_broker_status.configure(
                text="● No Broker URL entered (can be configured in Settings later)",
                text_color="#9ca3af"
            )
            return

        self.lbl_broker_status.configure(text="● Probing broker connectivity...", text_color="#f59e0b")
        self.update()

        u_res = validate_broker_url_security(url, allow_insecure=True)
        if not u_res.passed:
            self.lbl_broker_status.configure(text=f"⚠️ {u_res.message}", text_color="#f87171")
            return

        h_res = probe_broker_health(url)
        if not h_res.passed:
            self.lbl_broker_status.configure(text=f"⚠️ Broker Offline: {h_res.message}", text_color="#f87171")
            return

        if token:
            from preflight import verify_token_with_broker
            v_res = verify_token_with_broker(url, token)
            if v_res.passed:
                self.lbl_broker_status.configure(
                    text=f"✓ Broker Reachable & Token Verified ({token.split('.')[0]})",
                    text_color="#34d399"
                )
            else:
                self.lbl_broker_status.configure(
                    text=f"⚠️ Token Rejected by Broker: {v_res.message}",
                    text_color="#f87171"
                )
        else:
            self.lbl_broker_status.configure(
                text="✓ Broker Reachable & Active (Endpoint Verified)",
                text_color="#34d399"
            )

    def _do_install(self):
        self.btn_install.configure(state="disabled", text="Installing...")
        self.btn_cancel.configure(state="disabled")
        self.entry_dir.configure(state="disabled")
        self.target_dir = os.path.normpath(self.target_dir_var.get().strip())

        self.progress.set(0.2)
        self.status_lbl.configure(text="Preparing installation target...")
        self.update()

        try:
            if not os.path.exists(self.source_app_dir):
                messagebox.showerror("Error", f"Source application files not found:\n{self.source_app_dir}")
                self.destroy()
                return

            os.makedirs(self.target_dir, exist_ok=True)
            os.makedirs(self.data_dir, exist_ok=True)

            is_upgrade = os.path.exists(os.path.join(self.target_dir, "DatabaseBackupApp.exe"))
            temp_safety_dir = os.path.join(os.environ.get("TEMP", ""), "DB_Backup_Upgrade_Safety")

            if is_upgrade:
                self.status_lbl.configure(text="Terminating active processes for update...")
                subprocess.run(["taskkill.exe", "/F", "/IM", "DatabaseBackupApp.exe"], capture_output=True)
                os.makedirs(temp_safety_dir, exist_ok=True)
                for save_file in ["config.json", "token.dpapi", "broker_token.dat", "backup_public.pem", "escrow_public.pem", "backup_log.txt"]:
                    src_f = os.path.join(self.target_dir, save_file)
                    if os.path.exists(src_f):
                        shutil.copy2(src_f, os.path.join(temp_safety_dir, save_file))

            # 1. Copy application files via Robocopy
            self.status_lbl.configure(text="Copying application binaries...")
            subprocess.run(["robocopy.exe", self.source_app_dir, self.target_dir, "/E", "/IS", "/IT"], capture_output=True)

            # Ensure public keys are copied to both target_dir and data_dir
            for k in ["backup_public.pem", "escrow_public.pem"]:
                for s_base in [self.source_app_dir, self.bundle_dir]:
                    k_src = os.path.join(s_base, k)
                    if os.path.exists(k_src):
                        shutil.copy2(k_src, os.path.join(self.target_dir, k))
                        shutil.copy2(k_src, os.path.join(self.data_dir, k))
                        break

            # Process machine authentication token
            tok_input = self.token_var.get().strip() if hasattr(self, 'token_var') else ""
            raw_token_found = None
            for s_base in [self.bundle_dir, os.getcwd(), self.source_app_dir]:
                t_chk = os.path.join(s_base, "raw_token.txt")
                if os.path.exists(t_chk):
                    raw_token_found = t_chk
                    break

            if not tok_input and raw_token_found:
                try:
                    with open(raw_token_found, "r", encoding="utf-8") as tf:
                        tok_input = tf.read().strip()
                except Exception:
                    pass

            if tok_input and "." in tok_input:
                self.status_lbl.configure(text="Sealing machine token via native Windows DPAPI (Machine Scope 0x4)...")
                try:
                    prot_bytes = _protect_dpapi_native(tok_input.encode("utf-8"))
                    if prot_bytes:
                        with open(os.path.join(self.target_dir, "token.dpapi"), "wb") as f:
                            f.write(prot_bytes)
                        with open(os.path.join(self.data_dir, "token.dpapi"), "wb") as f:
                            f.write(prot_bytes)
                    if raw_token_found and os.path.exists(raw_token_found):
                        # Securely wipe raw_token.txt
                        flen = os.path.getsize(raw_token_found)
                        with open(raw_token_found, "wb") as wf:
                            wf.write(os.urandom(max(flen, 64)))
                        os.remove(raw_token_found)
                except Exception as ex:
                    print(f"Token DPAPI sealing failed: {ex}")

            # Check for existing token.dpapi in bundle
            for s_base in [self.bundle_dir, self.source_app_dir]:
                dp_src = os.path.join(s_base, "token.dpapi")
                if os.path.exists(dp_src):
                    shutil.copy2(dp_src, os.path.join(self.target_dir, "token.dpapi"))
                    shutil.copy2(dp_src, os.path.join(self.data_dir, "token.dpapi"))
                    break

            # Restore existing config/tokens if upgrade
            if is_upgrade and os.path.exists(temp_safety_dir):
                for save_file in ["config.json", "token.dpapi", "backup_public.pem", "escrow_public.pem", "backup_log.txt"]:
                    backed_f = os.path.join(temp_safety_dir, save_file)
                    if os.path.exists(backed_f):
                        shutil.copy2(backed_f, os.path.join(self.target_dir, save_file))
                        shutil.copy2(backed_f, os.path.join(self.data_dir, save_file))
                shutil.rmtree(temp_safety_dir, ignore_errors=True)

            # 2. Update config.json with verified Broker URL (Requirement A & G: PERF_QUERY removed)
            self.status_lbl.configure(text="Configuring settings and module tabs...")
            b_url = self.broker_url_var.get().strip()
            cfg_paths = [os.path.join(self.target_dir, "config.json"), os.path.join(self.data_dir, "config.json")]
            last_cfg = {}
            for cp in cfg_paths:
                cfg = {}
                if os.path.exists(cp):
                    try:
                        with open(cp, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                    except Exception:
                        cfg = {}
                if b_url:
                    cfg["BROKER_URL"] = b_url
                cfg["SHEET_TABS"] = {
                    "BACKUP": "Backup Automation",
                    "CLEANUP": "Server Cleanup"
                }
                with open(cp, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=4)
                last_cfg = cfg

            # 3. Create Shortcuts
            target_exe = os.path.join(self.target_dir, "DatabaseBackupApp.exe")
            target_ico = os.path.join(self.target_dir, "app_icon.ico")

            if self.cb_desktop.get():
                ps_cmd = (
                    f'$ws = New-Object -ComObject WScript.Shell; '
                    f'$sc = $ws.CreateShortcut([Environment]::GetFolderPath("Desktop") + "\\Database Cloud Backup.lnk"); '
                    f'$sc.TargetPath = "{target_exe}"; '
                    f'$sc.WorkingDirectory = "{self.target_dir}"; '
                    f'if (Test-Path "{target_ico}") {{ $sc.IconLocation = "{target_ico},0" }}; '
                    f'$sc.Save()'
                )
                subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], capture_output=True)

            if self.cb_startmenu.get():
                ps_cmd2 = (
                    f'$ws = New-Object -ComObject WScript.Shell; '
                    f'$sc = $ws.CreateShortcut([Environment]::GetFolderPath("Programs") + "\\Database Cloud Backup.lnk"); '
                    f'$sc.TargetPath = "{target_exe}"; '
                    f'$sc.WorkingDirectory = "{self.target_dir}"; '
                    f'if (Test-Path "{target_ico}") {{ $sc.IconLocation = "{target_ico},0" }}; '
                    f'$sc.Save()'
                )
                subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd2], capture_output=True)

            # 4. Register Task Scheduler with real target exe path (Requirement D)
            if self.cb_schedule.get():
                sched_args = ["schtasks.exe", "/create", "/tn", "Database Cloud Backup", "/tr", f'"{target_exe}" --auto', "/sc", "weekly", "/d", "MON", "/st", "02:00", "/f"]
                subprocess.run(sched_args, capture_output=True)

            # 5. Register in Windows Registry
            reg_key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp"
            for cmd in [
                ["reg.exe", "add", reg_key, "/v", "DisplayName", "/d", "Database Cloud Backup", "/t", "REG_SZ", "/f"],
                ["reg.exe", "add", reg_key, "/v", "DisplayVersion", "/d", INSTALLER_VERSION, "/t", "REG_SZ", "/f"],
                ["reg.exe", "add", reg_key, "/v", "Publisher", "/d", "Enterprise Cloud DR", "/t", "REG_SZ", "/f"],
                ["reg.exe", "add", reg_key, "/v", "InstallLocation", "/d", self.target_dir, "/t", "REG_SZ", "/f"]
            ]:
                subprocess.run(cmd, capture_output=True)

            # 6. Shared Preflight Validation (Requirement B: Fails installer and names failing check)
            self.status_lbl.configure(text="Executing preflight validation suite...")
            self.update()
            preflight_cfg = dict(last_cfg)
            preflight_cfg["_ENABLE_SCHEDULE"] = bool(self.cb_schedule.get())
            report = run_preflight_suite(preflight_cfg, target_dir=self.target_dir, data_dir=self.data_dir, mode="installer")
            if not report.passed:
                first_fail = report.failures[0]
                failures_text = "\n".join([f"• {f.name} ({f.code}): {f.message}" for f in report.failures])
                error_title = f"Installation Failed: {first_fail.name}"
                error_msg = (
                    f"Setup halted because preflight validation failed:\n\n"
                    f"Failing Check: {first_fail.name} ({first_fail.code})\n\n"
                    f"All Failures ({len(report.failures)}):\n{failures_text}\n\n"
                    "Please resolve the issue above and retry installation."
                )
                messagebox.showerror(error_title, error_msg)
                self.status_lbl.configure(text=f"Failed: {first_fail.name} ({first_fail.code})", text_color="#f87171")
                self.btn_install.configure(state="normal", text="Retry Install")
                self.btn_cancel.configure(state="normal")
                self.entry_dir.configure(state="normal")
                return

            # Finalize
            self.progress.set(1.0)
            self.status_lbl.configure(text="Installation Complete!", text_color="#10b981")
            self.btn_install.configure(text="Finished", state="normal", command=self.destroy)

            msg = f"Database Cloud Backup v{INSTALLER_VERSION} setup complete!\n\nApplication installed to:\n{self.target_dir}\n\nYou can now configure your database targets and cloud folders in the application."
            messagebox.showinfo("Success", msg)

            if self.cb_launch.get() and os.path.exists(target_exe):
                os.startfile(target_exe)

            self.destroy()

        except Exception as e:
            messagebox.showerror("Installation Failed", str(e))
            self.btn_install.configure(state="normal", text="Install Now")
            self.btn_cancel.configure(state="normal")
            self.entry_dir.configure(state="normal")


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
