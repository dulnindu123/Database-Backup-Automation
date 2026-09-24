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

        # Apply branding icon if available
        ico = os.path.join(self.bundle_dir, "app_icon.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
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

            # Step 1: Copy application payload via Robocopy
            cmd = f'robocopy "{self.source_app_dir}" "{self.target_dir}" /E /IS /IT'
            subprocess.run(cmd, shell=True)

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
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], shell=True)

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
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd2], shell=True)

            # Step 4: Configure Windows Task Scheduler
            if self.cb_schedule.get():
                self.status_lbl.configure(text="Configuring Windows Task Scheduler...")
                self.progress.set(0.85)
                self.update()
                sched_cmd = f'schtasks /create /tn "Database Cloud Backup" /tr "\\"{target_exe}\\" --auto" /sc weekly /d MON /st 02:00 /f'
                subprocess.run(sched_cmd, shell=True)

            # Step 5: Install self-migrating Uninstaller & register with Windows Installed Apps
            self.status_lbl.configure(text="Registering uninstaller and Windows configuration...")
            self.progress.set(0.95)
            self.update()
            create_uninstaller_script(self.target_dir, target_ico)

            # Step 6: Finalize installation
            self.progress.set(1.0)
            self.status_lbl.configure(text="Installation Complete!", text_color="#10b981")
            self.btn_install.configure(text="Finished", state="normal", command=self._finish)
            messagebox.showinfo("Success", "Database Cloud Backup was installed successfully!\n\nA shortcut has been created on your Desktop.")

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
    Creates a robust, self-migrating uninstaller script in target_dir and
    registers the application in Windows Settings > Installed Apps (Add or Remove Programs).
    """
    uninstall_bat_content = r'''@echo off
setlocal EnableDelayedExpansion

title Database Cloud Backup - Clean Uninstaller

set "APP_DIR=%~1"
if "%APP_DIR%"=="" set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

:: Migrate execution to %TEMP% so Windows releases all file locks on APP_DIR
if /i not "%~dp0"=="%TEMP%\" (
    copy /y "%~f0" "%TEMP%\Uninstall_DatabaseBackupApp.bat" >nul 2>&1
    start "" "%TEMP%\Uninstall_DatabaseBackupApp.bat" "%APP_DIR%" %2
    exit /b 0
)

:: Ensure working directory is %TEMP%, completely releasing APP_DIR
cd /d "%TEMP%"

if /i not "%~2"=="/quiet" if /i not "%~2"=="/silent" (
    cls
    echo ============================================================
    echo   UNINSTALL DATABASE CLOUD BACKUP
    echo ============================================================
    echo.
    echo Target Directory: "%APP_DIR%"
    echo.
    echo This will cleanly remove:
    echo  - Running application processes
    echo  - Windows Task Scheduler automated backup jobs
    echo  - Desktop and Start Menu shortcuts
    echo  - Windows Installed Apps registry entries
    echo  - Application binaries and configurations
    echo.
    set /p CONFIRM="Are you sure you want to completely uninstall? (Y/N): "
    if /i not "!CONFIRM!"=="Y" (
        echo.
        echo Uninstallation cancelled by user.
        timeout /t 2 >nul
        (goto) 2>nul & del "%~f0"
        exit /b 0
    )
)

echo.
echo [1/5] Terminating active application processes...
taskkill /F /IM DatabaseBackupApp.exe >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
taskkill /F /IM sqlcmd.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/5] Removing Windows Task Scheduler tasks and services...
schtasks /delete /tn "Database Cloud Backup" /f >nul 2>&1
schtasks /delete /tn "Database Cloud Backup (System Service)" /f >nul 2>&1
schtasks /delete /tn "Database Cloud Backup Service" /f >nul 2>&1

echo [3/5] Removing Desktop and Start Menu shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Programs')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue;" >nul 2>&1
del /f /q "%USERPROFILE%\Desktop\Database Cloud Backup.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Database Cloud Backup.lnk" >nul 2>&1

echo [4/5] Removing Windows Registry registration...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1

echo [5/5] Purging application directory...
if exist "%APP_DIR%" (
    timeout /t 1 /nobreak >nul
    rmdir /s /q "%APP_DIR%" >nul 2>&1
    if exist "%APP_DIR%" (
        timeout /t 1 /nobreak >nul
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%APP_DIR%' -Recurse -Force -ErrorAction SilentlyContinue" >nul 2>&1
    )
    if exist "%APP_DIR%" (
        timeout /t 1 /nobreak >nul
        rmdir /s /q "%APP_DIR%" >nul 2>&1
    )
)

echo.
echo ============================================================
echo   UNINSTALLATION COMPLETE!
echo ============================================================
echo Database Cloud Backup was completely and cleanly removed.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Database Cloud Backup has been completely and cleanly uninstalled from this computer.', 'Uninstallation Complete', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)" >nul 2>&1

(goto) 2>nul & del "%~f0"
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
            f'reg add "{reg_key}" /v "DisplayName" /d "Database Cloud Backup" /t REG_SZ /f',
            f'reg add "{reg_key}" /v "DisplayVersion" /d "2.0.0" /t REG_SZ /f',
            f'reg add "{reg_key}" /v "Publisher" /d "Dulnindu Saranga" /t REG_SZ /f',
            f'reg add "{reg_key}" /v "InstallLocation" /d "{target_dir}" /t REG_SZ /f',
            f'reg add "{reg_key}" /v "DisplayIcon" /d "{target_ico}" /t REG_SZ /f',
            f'reg add "{reg_key}" /v "UninstallString" /d "cmd.exe /c \\"{uninstall_path}\\"" /t REG_SZ /f',
            f'reg add "{reg_key}" /v "NoModify" /d 1 /t REG_DWORD /f',
            f'reg add "{reg_key}" /v "NoRepair" /d 1 /t REG_DWORD /f'
        ]
        for cmd in reg_cmds:
            subprocess.run(cmd, shell=True, capture_output=True)
    except Exception:
        pass


def main():
    """Runs the installation wizard."""
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
