"""
Graphical Installation Wizard for Enterprise Database Cloud Backup (v4.1.0)
Provides a streamlined, user-friendly setup with interactive Cloud Run Broker
and Customer Google Drive / Master Google Sheet configuration.
"""
import os
import sys
import json
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

# Configure theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

INSTALLER_VERSION = "4.1.0"


def get_bundle_dir():
    """Resolves directory containing the installer executable and payload files."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def extract_clean_id(url_or_id):
    """Extracts raw ID from full Google URLs."""
    import re
    if not url_or_id:
        return ""
    s = str(url_or_id).strip()
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', s)
    if m:
        return m.group(1)
    m = re.search(r'/folders/([a-zA-Z0-9_-]+)', s)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', s)
    if m:
        return m.group(1)
    return s


class InstallerApp(ctk.CTk):
    """Interactive Installation Wizard for Database Cloud Backup System."""
    def __init__(self):
        super().__init__()
        
        self.title(f"Setup - Database Cloud Backup System v{INSTALLER_VERSION}")
        self.geometry("640, 680")
        self.resizable(True, True)

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
            if os.path.exists(os.path.join(candidate, "DatabaseBackupApp.exe")):
                self.source_app_dir = candidate
                break
        if not self.source_app_dir:
            self.source_app_dir = os.path.join(self.bundle_dir, "AppFiles")

        self.target_dir = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Programs", "DatabaseBackupApp")
        self.data_dir = os.path.join(os.environ.get("ALLUSERSPROFILE", "C:\\ProgramData"), "DatabaseBackupApp")

        # Load any existing or package-provided defaults
        self.default_broker = self._read_file_or_default("broker_url.txt", "http://127.0.0.1:5000")
        self.default_drive = self._read_file_or_default("drive_folder.txt", "")
        self.default_sheet = self._read_file_or_default("sheet_id.txt", "")

        # Check existing config in target or data dir
        for chk in [os.path.join(self.target_dir, "config.json"), os.path.join(self.data_dir, "config.json")]:
            if os.path.exists(chk):
                try:
                    with open(chk, 'r', encoding='utf-8') as f:
                        c = json.load(f)
                        self.default_broker = c.get("BROKER_URL") or self.default_broker
                        self.default_drive = c.get("GOOGLE_DRIVE_FOLDER_ID") or self.default_drive
                        self.default_sheet = c.get("GOOGLE_SHEET_ID") or self.default_sheet
                except Exception:
                    pass

        # Apply branding icon
        ico = os.path.join(self.bundle_dir, "app_icon.ico")
        if sys.platform.startswith("win") and os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_ui()

    def _read_file_or_default(self, filename, default_val):
        p = os.path.join(self.bundle_dir, filename)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    txt = f.read().strip()
                    if txt:
                        return txt
            except Exception:
                pass
        return default_val

    def _build_ui(self):
        # Header Banner
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("#1f2937", "#111827"), height=75)
        header.pack(fill="x", side="top")

        ctk.CTkLabel(
            header,
            text=f"Database Cloud Backup Setup (v{INSTALLER_VERSION})",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w", padx=25, pady=(12, 2))

        ctk.CTkLabel(
            header,
            text="Zero-Trust Disaster Recovery & Multi-Module Cloud Sync",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=25)

        # Scrollable Body Content
        scroll_body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll_body.pack(fill="both", expand=True, padx=25, pady=15)

        # 1. Target Directory
        ctk.CTkLabel(scroll_body, text="1. Installation Destination:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        dir_frame = ctk.CTkFrame(scroll_body, fg_color="transparent")
        dir_frame.pack(fill="x", pady=(0, 15))

        self.target_dir_var = tk.StringVar(value=self.target_dir)
        self.entry_dir = ctk.CTkEntry(dir_frame, textvariable=self.target_dir_var, font=ctk.CTkFont(size=11), height=32)
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(dir_frame, text="Browse...", font=ctk.CTkFont(size=11, weight="bold"), width=80, height=32,
                      fg_color="#374151", hover_color="#4b5563", command=self._browse_directory).pack(side="right")

        # 2. Upload Broker URL (Cloud Run Endpoint)
        ctk.CTkLabel(scroll_body, text="2. Upload Broker URL (Cloud Run Endpoint):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#60a5fa").pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(scroll_body, text="Connects this client PC to the Cloud Run Upload Broker. Once configured, this URL is locked.", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(anchor="w", pady=(0, 4))
        self.entry_broker = ctk.CTkEntry(scroll_body, height=32, placeholder_text="e.g. https://upload-broker-xxxx-uc.a.run.app")
        self.entry_broker.pack(fill="x", pady=(0, 15))
        self.entry_broker.insert(0, self.default_broker)

        # 3. Customer Cloud Integration
        ctk.CTkLabel(scroll_body, text="3. Customer Cloud Integration (Google Drive & Master Sheet):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#34d399").pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(scroll_body, text="Each customer has a dedicated Google Drive folder and Master Sheet (with tabs: Backup, Cleanup, Query).", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(anchor="w", pady=(0, 6))

        ctk.CTkLabel(scroll_body, text="Customer Google Drive Folder ID or Link:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.entry_drive = ctk.CTkEntry(scroll_body, height=32, placeholder_text="e.g. 1LKuo7j4cHvvP0-p0C6PVo6gdkgoVBaQ4 or https://drive.google.com/...")
        self.entry_drive.pack(fill="x", pady=(0, 8))
        if self.default_drive:
            self.entry_drive.insert(0, self.default_drive)

        ctk.CTkLabel(scroll_body, text="Customer Master Google Sheet ID or Link:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        self.entry_sheet = ctk.CTkEntry(scroll_body, height=32, placeholder_text="e.g. 1FAnmfTAixeDgwA5f3TvJ9IEtFp1OuFTyw3UpDiOdvwg or https://docs.google.com/...")
        self.entry_sheet.pack(fill="x", pady=(0, 15))
        if self.default_sheet:
            self.entry_sheet.insert(0, self.default_sheet)

        # 4. Installation Preferences
        ctk.CTkLabel(scroll_body, text="4. Installation Preferences:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(0, 4))
        self.cb_desktop = ctk.CTkCheckBox(scroll_body, text="Create Desktop Shortcut", font=ctk.CTkFont(size=12))
        self.cb_desktop.pack(anchor="w", pady=3)
        self.cb_desktop.select()

        self.cb_startmenu = ctk.CTkCheckBox(scroll_body, text="Create Start Menu Shortcut", font=ctk.CTkFont(size=12))
        self.cb_startmenu.pack(anchor="w", pady=3)
        self.cb_startmenu.select()

        self.cb_schedule = ctk.CTkCheckBox(scroll_body, text="Enable Automatic Monday 2:00 AM Backup Schedule", font=ctk.CTkFont(size=12))
        self.cb_schedule.pack(anchor="w", pady=3)
        self.cb_schedule.select()

        self.cb_launch = ctk.CTkCheckBox(scroll_body, text="Launch Application after setup completes", font=ctk.CTkFont(size=12))
        self.cb_launch.pack(anchor="w", pady=3)
        self.cb_launch.select()

        # Progress bar & status
        self.progress = ctk.CTkProgressBar(scroll_body, width=540, height=10)
        self.progress.pack(pady=(15, 5))
        self.progress.set(0)

        self.status_lbl = ctk.CTkLabel(scroll_body, text="Ready to install.", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self.status_lbl.pack(anchor="w")

        # Footer Buttons
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=25, pady=(0, 15))

        self.btn_install = ctk.CTkButton(
            footer, text="Install Now", font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb", hover_color="#1d4ed8", height=38, width=130, command=self._do_install
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

    def _do_install(self):
        self.btn_install.configure(state="disabled", text="Installing...")
        self.btn_cancel.configure(state="disabled")
        self.entry_dir.configure(state="disabled")
        self.target_dir = os.path.normpath(self.target_dir_var.get().strip())

        broker_input = self.entry_broker.get().strip()
        drive_input = extract_clean_id(self.entry_drive.get().strip())
        sheet_input = extract_clean_id(self.entry_sheet.get().strip())

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
            self.status_lbl.configure(text="Copying updated application binaries...")
            subprocess.run(["robocopy.exe", self.source_app_dir, self.target_dir, "/E", "/IS", "/IT"], capture_output=True)

            # Restore existing config/tokens if upgrade
            if is_upgrade and os.path.exists(temp_safety_dir):
                for save_file in ["config.json", "token.dpapi", "backup_public.pem", "escrow_public.pem", "backup_log.txt"]:
                    backed_f = os.path.join(temp_safety_dir, save_file)
                    if os.path.exists(backed_f):
                        shutil.copy2(backed_f, os.path.join(self.target_dir, save_file))
                legacy_dat = os.path.join(temp_safety_dir, "broker_token.dat")
                target_dpapi = os.path.join(self.target_dir, "token.dpapi")
                if os.path.exists(legacy_dat) and not os.path.exists(target_dpapi):
                    shutil.copy2(legacy_dat, target_dpapi)
                shutil.rmtree(temp_safety_dir, ignore_errors=True)

            # 2. Update config.json with Broker URL, Google Drive Folder, and Master Google Sheet
            self.status_lbl.configure(text="Saving customer parameters & cloud links...")
            cfg_paths = [os.path.join(self.target_dir, "config.json"), os.path.join(self.data_dir, "config.json")]
            for cp in cfg_paths:
                cfg = {}
                if os.path.exists(cp):
                    try:
                        with open(cp, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                    except Exception:
                        cfg = {}
                if broker_input:
                    cfg["BROKER_URL"] = broker_input
                if drive_input:
                    cfg["GOOGLE_DRIVE_FOLDER_ID"] = drive_input
                if sheet_input:
                    cfg["GOOGLE_SHEET_ID"] = sheet_input
                cfg["SHEET_TABS"] = {
                    "BACKUP": "Backup Automation",
                    "CLEANUP": "Server Cleanup",
                    "PERF_QUERY": "Performance Query"
                }
                with open(cp, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=4)

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

            # 4. Register Task Scheduler
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

            # Finalize
            self.progress.set(1.0)
            self.status_lbl.configure(text="Installation Complete!", text_color="#10b981")
            self.btn_install.configure(text="Finished", state="normal", command=self.destroy)

            msg = f"Database Cloud Backup v{INSTALLER_VERSION} setup complete!\n\nParameters and customer cloud links configured."
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
