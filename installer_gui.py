import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def get_bundle_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Setup - Database Cloud Backup System")
        self.geometry("540, 420")
        self.resizable(False, False)

        self.bundle_dir = get_bundle_dir()
        self.source_app_dir = os.path.join(self.bundle_dir, "DatabaseBackupApp")
        if not os.path.exists(self.source_app_dir):
            # Fallback to local dist if running during development
            self.source_app_dir = os.path.join(self.bundle_dir, "dist", "DatabaseBackupApp")

        self.target_dir = os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Programs", "DatabaseBackupApp")

        # Set icon
        ico = os.path.join(self.bundle_dir, "app_icon.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self._build_ui()

    def _build_ui(self):
        # Header banner
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

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=25, pady=20)

        ctk.CTkLabel(
            body,
            text="Installation Directory:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", pady=(0, 5))

        dir_box = ctk.CTkFrame(body, fg_color=("#1e293b", "#0f172a"), corner_radius=6)
        dir_box.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(
            dir_box,
            text=self.target_dir,
            font=ctk.CTkFont(size=11),
            text_color="#60a5fa"
        ).pack(anchor="w", padx=10, pady=8)

        # Options
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

        # Progress bar
        self.progress = ctk.CTkProgressBar(body, width=490, height=10)
        self.progress.pack(pady=(15, 5))
        self.progress.set(0)

        self.status_lbl = ctk.CTkLabel(body, text="Ready to install.", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self.status_lbl.pack(anchor="w")

        # Bottom buttons
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

    def _do_install(self):
        self.btn_install.configure(state="disabled", text="Installing...")
        self.btn_cancel.configure(state="disabled")
        self.status_lbl.configure(text="Copying application files...")
        self.progress.set(0.3)
        self.update()

        try:
            if not os.path.exists(self.source_app_dir):
                messagebox.showerror("Error", f"Source folder not found:\n{self.source_app_dir}")
                self.destroy()
                return

            os.makedirs(self.target_dir, exist_ok=True)

            # Copy files using robocopy or shutil
            cmd = f'robocopy "{self.source_app_dir}" "{self.target_dir}" /E /IS /IT'
            subprocess.run(cmd, shell=True)

            self.progress.set(0.7)
            self.status_lbl.configure(text="Creating shortcuts...")
            self.update()

            target_exe = os.path.join(self.target_dir, "DatabaseBackupApp.exe")
            target_ico = os.path.join(self.target_dir, "app_icon.ico")

            # Create shortcuts via PowerShell WScript.Shell
            if self.cb_desktop.get():
                ps_cmd = f'$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut([Environment]::GetFolderPath("Desktop") + "\\Database Cloud Backup.lnk"); $sc.TargetPath = "{target_exe}"; $sc.WorkingDirectory = "{self.target_dir}"; if (Test-Path "{target_ico}") {{ $sc.IconLocation = "{target_ico},0" }}; $sc.Save()'
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], shell=True)

            if self.cb_startmenu.get():
                ps_cmd2 = f'$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut([Environment]::GetFolderPath("Programs") + "\\Database Cloud Backup.lnk"); $sc.TargetPath = "{target_exe}"; $sc.WorkingDirectory = "{self.target_dir}"; if (Test-Path "{target_ico}") {{ $sc.IconLocation = "{target_ico},0" }}; $sc.Save()'
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd2], shell=True)

            # Task scheduler
            if self.cb_schedule.get():
                self.status_lbl.configure(text="Configuring Task Scheduler...")
                self.progress.set(0.9)
                self.update()
                sched_cmd = f'schtasks /create /tn "Database Cloud Backup" /tr "\\"{target_exe}\\" --auto" /sc weekly /d MON /st 02:00 /f'
                subprocess.run(sched_cmd, shell=True)

            self.progress.set(1.0)
            self.status_lbl.configure(text="Installation Complete!", text_color="#10b981")
            self.btn_install.configure(text="Finished", state="normal", command=self._finish)
            messagebox.showinfo("Success", "Database Cloud Backup was installed successfully!\n\nA shortcut has been created on your Desktop.")

            if self.cb_launch.get():
                os.startfile(target_exe)

            self.destroy()

        except Exception as e:
            messagebox.showerror("Installation Failed", str(e))
            self.btn_install.configure(state="normal", text="Install Now")
            self.btn_cancel.configure(state="normal")

    def _finish(self):
        self.destroy()

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
