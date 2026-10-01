"""
Enterprise Database Cloud Backup Automation - Autonomous Setup Wizard
=============================================================================
Author: Dulnindu Saranga
Architecture: Standalone Deployment Installer (CustomTkinter)

Responsibilities:
1. Target Directory Resolution:
   - Installs binaries into %LOCALAPPDATA%\\Programs\\DatabaseBackupApp.
   - Using user-scoped application directories allows complete, autonomous 
     installation without triggering mandatory UAC elevation prompts on locked-down client machines.

2. Application Payload Replication:
   - Copies pre-compiled binary files, internal libraries, and initial config templates
     using robocopy with recursive mirroring (/E /IS /IT).

3. Windows Shortcut Creation:
   - Utilizes Windows Script Host COM object (WScript.Shell) via PowerShell
     to create rich .lnk shortcuts on Desktop and Start Menu programs folder.
   - Binds the application icon (app_icon.ico) directly to the created shortcuts.

4. Unattended Scheduler Registration:
   - Programmatically registers the weekly background task via Windows schtasks CLI.
"""

import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

# Configure theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def get_bundle_dir():
    """
    Resolves the directory containing the installer executable and payload files.
    Works seamlessly both in raw Python development and when packaged as a PyInstaller binary.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


class InstallerApp(ctk.CTk):
    """
    Graphical Installation Wizard providing a streamlined setup experience for end users.
    """
    def __init__(self):
        super().__init__()
        
        # Window configuration
        self.title("Setup - Database Cloud Backup System")
        self.geometry("560, 440")
        self.resizable(False, False)

        # Resolve payload directory across multiple package structures
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

        # Default destination installation directory in %LOCALAPPDATA%\Programs
        self.target_dir = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Programs", "DatabaseBackupApp")

        # Apply branding icon if available (ICO for Windows, PNG for macOS/Linux)
        ico = os.path.join(self.bundle_dir, "app_icon.ico")
        png = os.path.join(self.bundle_dir, "app_icon.png")
        if sys.platform.startswith("win") and os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass
        elif os.path.exists(png):
            try:
                img = tk.PhotoImage(file=png)
                self.wm_iconphoto(True, img)
            except Exception:
                pass

        self._build_ui()

    def _build_ui(self):
        """Constructs installer dialog with destination path and installation options."""
        # ── Header Banner ─────────────────────────────────────────────
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=("#1f2937", "#111827"), height=70)
        header.pack(fill="x", side="top")

        ctk.CTkLabel(
            header,
            text="Database Cloud Backup Setup",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w", padx=25, pady=(15, 2))

        ctk.CTkLabel(
            header,
            text="Install the automated backup desktop application onto this PC",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=25)

        # ── Body Content ──────────────────────────────────────────────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=25, pady=20)

        ctk.CTkLabel(
            body,
            text="Installation Directory:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        # Target directory input box with Browse button
        dir_frame = ctk.CTkFrame(body, fg_color="transparent")
        dir_frame.pack(fill="x", pady=(0, 15))

        self.target_dir_var = tk.StringVar(value=self.target_dir)
        self.entry_dir = ctk.CTkEntry(
            dir_frame,
            textvariable=self.target_dir_var,
            font=ctk.CTkFont(size=11),
            height=34
        )
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_browse = ctk.CTkButton(
            dir_frame,
            text="Browse...",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=80,
            height=34,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self._browse_directory
        )
        self.btn_browse.pack(side="right")

        # Customer Cloud Integration inputs (Optional during install)
        ctk.CTkLabel(body, text="Customer Google Drive Folder ID / Link (Optional):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(8, 2))
        self.entry_google_drive = ctk.CTkEntry(body, placeholder_text="Optional: Folder ID or https://drive.google.com/...", height=30)
        self.entry_google_drive.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(body, text="Customer Master Google Sheet ID / Link (Optional):", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(2, 2))
        self.entry_google_sheet = ctk.CTkEntry(body, placeholder_text="Optional: Sheet ID or https://docs.google.com/spreadsheets/...", height=30)
        self.entry_google_sheet.pack(fill="x", pady=(0, 10))

        # Installation preference checkboxes
        self.cb_desktop = ctk.CTkCheckBox(body, text="Create Desktop Shortcut", font=ctk.CTkFont(size=12))
        self.cb_desktop.pack(anchor="w", pady=4)
        self.cb_desktop.select()

        self.cb_startmenu = ctk.CTkCheckBox(body, text="Create Start Menu Shortcut", font=ctk.CTkFont(size=12))
        self.cb_startmenu.pack(anchor="w", pady=4)
        self.cb_startmenu.select()

        self.cb_schedule = ctk.CTkCheckBox(body, text="Enable Automatic Monday 2:00 AM Schedule", font=ctk.CTkFont(size=12))
        self.cb_schedule.pack(anchor="w", pady=4)
        self.cb_schedule.select()

        self.cb_launch = ctk.CTkCheckBox(body, text="Launch Application after setup completes", font=ctk.CTkFont(size=12))
        self.cb_launch.pack(anchor="w", pady=4)
        self.cb_launch.select()

        # Visual progress bar
        self.progress = ctk.CTkProgressBar(body, width=510, height=10)
        self.progress.pack(pady=(15, 5))
        self.progress.set(0)

        self.status_lbl = ctk.CTkLabel(body, text="Ready to install.", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self.status_lbl.pack(anchor="w")

        # ── Footer Action Buttons ──────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=25, pady=(0, 20))

        self.btn_install = ctk.CTkButton(
            footer,
            text="Install Now",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=38,
            width=130,
            command=self._do_install
        )
        self.btn_install.pack(side="right", padx=(10, 0))

        self.btn_cancel = ctk.CTkButton(
            footer,
            text="Cancel",
            font=ctk.CTkFont(size=13),
            fg_color="#374151",
            hover_color="#4b5563",
            height=38,
            width=90,
            command=self.destroy
        )
        self.btn_cancel.pack(side="right")

    def _browse_directory(self):
        """Allows user to select custom installation destination."""
        chosen = filedialog.askdirectory(
            title="Select Installation Directory",
            initialdir=self.target_dir_var.get()
        )
        if chosen:
            chosen = os.path.normpath(chosen)
            if not chosen.lower().endswith("databasebackupapp"):
                chosen = os.path.join(chosen, "DatabaseBackupApp")
            self.target_dir_var.set(chosen)

    def _do_install(self):
        """
        Executes file replication, shortcut creation, and Task Scheduler registration.
        """
        self.target_dir = os.path.normpath(self.target_dir_var.get().strip())
        if not self.target_dir:
            messagebox.showerror("Error", "Please specify a valid installation directory.")
            return

        self.btn_install.configure(state="disabled", text="Installing...")
        self.btn_cancel.configure(state="disabled")
        self.entry_dir.configure(state="disabled")
        self.btn_browse.configure(state="disabled")
        self.status_lbl.configure(text="Copying application files...")
        self.progress.set(0.3)
        self.update()

        try:
            if not os.path.exists(self.source_app_dir):
                messagebox.showerror("Error", f"Source application files not found:\n{self.source_app_dir}")
                self.destroy()
                return

            os.makedirs(self.target_dir, exist_ok=True)

            # Check if this is an upgrade/update of an existing installation
            is_upgrade = os.path.exists(os.path.join(self.target_dir, "DatabaseBackupApp.exe"))
            temp_safety_dir = os.path.join(os.environ.get("TEMP", ""), "DB_Backup_Upgrade_Safety")

            # Terminate active process to prevent Windows in-use file locks
            if is_upgrade:
                self.status_lbl.configure(text="Terminating active processes for update...")
                subprocess.run(["taskkill.exe", "/F", "/IM", "DatabaseBackupApp.exe"], capture_output=True)
                # Safeguard customer configuration, credentials, tokens, and logs
                os.makedirs(temp_safety_dir, exist_ok=True)
                for save_file in ["config.json", "token.dpapi", "broker_token.dat", "backup_public.pem", "escrow_public.pem", "backup_log.txt"]:
                    src_f = os.path.join(self.target_dir, save_file)
                    if os.path.exists(src_f):
                        shutil.copy2(src_f, os.path.join(temp_safety_dir, save_file))

            # Step 1: Copy application payload via Robocopy
            self.status_lbl.configure(text="Copying application binaries and libraries...")
            subprocess.run(["robocopy.exe", self.source_app_dir, self.target_dir, "/E", "/IS", "/IT"], capture_output=True)

            # Restore customer settings if this was an upgrade
            if is_upgrade and os.path.exists(temp_safety_dir):
                for save_file in ["config.json", "token.dpapi", "backup_public.pem", "escrow_public.pem", "backup_log.txt"]:
                    backed_f = os.path.join(temp_safety_dir, save_file)
                    if os.path.exists(backed_f):
                        shutil.copy2(backed_f, os.path.join(self.target_dir, save_file))
                # Migrate legacy broker_token.dat to token.dpapi if token.dpapi not present
                legacy_dat = os.path.join(temp_safety_dir, "broker_token.dat")
                target_dpapi = os.path.join(self.target_dir, "token.dpapi")
                if os.path.exists(legacy_dat) and not os.path.exists(target_dpapi):
                    shutil.copy2(legacy_dat, target_dpapi)
                shutil.rmtree(temp_safety_dir, ignore_errors=True)

            self.progress.set(0.7)
            self.status_lbl.configure(text="Creating desktop and start menu shortcuts...")
            self.update()

            target_exe = os.path.join(self.target_dir, "DatabaseBackupApp.exe")
            target_ico = os.path.join(self.target_dir, "app_icon.ico")

            # Step 2: Create Windows Desktop Shortcut via WScript.Shell COM
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

            # Step 3: Create Start Menu Shortcut via WScript.Shell COM
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

            # Step 4: Configure Windows Task Scheduler
            if self.cb_schedule.get():
                self.status_lbl.configure(text="Configuring Windows Task Scheduler...")
                self.progress.set(0.85)
                self.update()
                
                # Check if custom schedule settings exist in config.json
                cfg_path = os.path.join(self.target_dir, "config.json")
                sched_time = "02:00"
                sched_days = ["MON"]
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, 'r', encoding='utf-8') as f:
                            c_data = json.load(f)
                            sched_time = c_data.get("SCHEDULE_TIME", "02:00")
                            c_days = c_data.get("SCHEDULE_DAYS")
                            if c_days:
                                sched_days = c_days if isinstance(c_days, list) else [c_days]
                    except Exception:
                        pass
                
                is_daily = ("DAILY" in sched_days or len(sched_days) == 7)
                sched_args = ["schtasks.exe", "/create", "/tn", "Database Cloud Backup", "/tr", f'"{target_exe}" --auto', "/f"]
                if is_daily:
                    sched_args.extend(["/sc", "daily", "/st", sched_time])
                else:
                    days_csv = ",".join([d.strip().upper() for d in sched_days])
                    sched_args.extend(["/sc", "weekly", "/d", days_csv, "/st", sched_time])
                subprocess.run(sched_args, capture_output=True)

            # Step 5: Install self-migrating Uninstaller & register with Windows Installed Apps
            self.status_lbl.configure(text="Registering uninstaller and Windows configuration...")
            self.progress.set(0.95)
            self.update()
            create_uninstaller_script(self.target_dir, target_ico)

            # Step 6: Finalize installation
            self.progress.set(1.0)
            status_text = "Update Complete!" if is_upgrade else "Installation Complete!"
            self.status_lbl.configure(text=status_text, text_color="#10b981")
            self.btn_install.configure(text="Finished", state="normal", command=self._finish)
            
            if is_upgrade:
                msg = "Database Cloud Backup was updated successfully!\n\nAll existing databases, settings, and encryption keys have been preserved."
            else:
                msg = "Database Cloud Backup was installed successfully!\n\nA shortcut has been created on your Desktop."
            messagebox.showinfo("Success", msg)

            # Launch application if requested
            if self.cb_launch.get():
                os.startfile(target_exe)

            self.destroy()

        except Exception as e:
            messagebox.showerror("Installation Failed", str(e))
            self.btn_install.configure(state="normal", text="Install Now")
            self.btn_cancel.configure(state="normal")
            self.entry_dir.configure(state="normal")
            self.btn_browse.configure(state="normal")

    def _finish(self):
        """Closes the setup dialog."""
        self.destroy()


def create_uninstaller_script(target_dir, target_ico=""):
    """
    Creates a robust uninstaller script in target_dir and
    registers the application in Windows Settings > Installed Apps (Add or Remove Programs).
    """
    uninstall_bat_content = r'''@echo off
setlocal EnableDelayedExpansion
title Database Cloud Backup - Clean Uninstaller

:: 1. Identify Target Installation Directory
set "TARGET_DIR=%~dp0"
if "!TARGET_DIR:~-1!"=="\" set "TARGET_DIR=!TARGET_DIR:~0,-1!"

:: 2. Interactive Confirmation (only if not silent)
if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    cls
    echo ============================================================
    echo   DATABASE CLOUD BACKUP - UNINSTALLER
    echo ============================================================
    echo.
    echo Target Installation Directory:
    echo   !TARGET_DIR!
    echo.
    echo This will cleanly remove:
    echo   - Running application processes
    echo   - Windows Task Scheduler automated backup jobs
    echo   - Desktop and Start Menu shortcuts
    echo   - Windows Installed Apps registry entries
    echo   - Application binaries and configurations
    echo.
    set /p CONFIRM="Are you sure you want to completely uninstall? (Y/N): "
    if /i not "!CONFIRM!"=="Y" (
        echo.
        echo Uninstallation cancelled by user.
        ping 127.0.0.1 -n 3 >nul
        exit /b 0
    )
)

echo.
echo [1/5] Terminating active application processes...
taskkill /F /IM DatabaseBackupApp.exe >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
taskkill /F /IM sqlcmd.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
ping 127.0.0.1 -n 2 >nul

echo [2/5] Removing Windows Task Scheduler tasks...
schtasks /delete /tn "Database Cloud Backup" /f >nul 2>&1
schtasks /delete /tn "Database Cloud Backup (System Service)" /f >nul 2>&1
schtasks /delete /tn "EnterpriseDatabaseBackup" /f >nul 2>&1

echo [3/5] Removing Desktop and Start Menu shortcuts...
del /f /q "%USERPROFILE%\Desktop\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%PUBLIC%\Desktop\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs\*Database*Backup*.lnk" >nul 2>&1

echo [4/5] Removing Windows Registry registration...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1

echo [5/5] Purging application directory...
cd /d "%TEMP%"
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 1; Remove-Item -LiteralPath '!TARGET_DIR!' -Recurse -Force -ErrorAction SilentlyContinue"

echo.
echo ============================================================
echo   UNINSTALLATION COMPLETE!
echo ============================================================
echo Database Cloud Backup was completely and cleanly removed.
echo.

if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Database Cloud Backup has been completely and cleanly uninstalled from this computer.', 'Uninstallation Complete', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)" >nul 2>&1
)

exit /b 0
'''
    try:
        uninstall_path = os.path.join(target_dir, "Uninstall.bat")
        with open(uninstall_path, "w", encoding="utf-8") as f:
            f.write(uninstall_bat_content)

        # Register in Windows Settings > Installed Apps (Add or Remove Programs)
        reg_key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp"
        if not target_ico:
            target_ico = os.path.join(target_dir, "app_icon.ico")
        reg_cmds = [
            ["reg.exe", "add", reg_key, "/v", "DisplayName", "/d", "Database Cloud Backup", "/t", "REG_SZ", "/f"],
            ["reg.exe", "add", reg_key, "/v", "DisplayVersion", "/d", "4.0.0", "/t", "REG_SZ", "/f"],
            ["reg.exe", "add", reg_key, "/v", "Publisher", "/d", "Enterprise Cloud DR", "/t", "REG_SZ", "/f"],
            ["reg.exe", "add", reg_key, "/v", "InstallLocation", "/d", target_dir, "/t", "REG_SZ", "/f"],
            ["reg.exe", "add", reg_key, "/v", "DisplayIcon", "/d", target_ico, "/t", "REG_SZ", "/f"],
            ["reg.exe", "add", reg_key, "/v", "UninstallString", "/d", f'"{uninstall_path}"', "/t", "REG_SZ", "/f"],
            ["reg.exe", "add", reg_key, "/v", "NoModify", "/d", "1", "/t", "REG_DWORD", "/f"],
            ["reg.exe", "add", reg_key, "/v", "NoRepair", "/d", "1", "/t", "REG_DWORD", "/f"]
        ]
        for cmd in reg_cmds:
            subprocess.run(cmd, capture_output=True)
    except Exception:
        pass


def main():
    """Runs the installation wizard."""
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
