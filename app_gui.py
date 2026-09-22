import os
import sys
import json
import webbrowser
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Allow OAuth scope relaxation
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# Import core backup logic
from backup_core import (
    BASE_DIR,
    LOG_FILE,
    load_config,
    save_config,
    authenticate,
    reset_credentials,
    test_google_connection,
    run_full_backup,
    get_scheduler_status,
    enable_scheduler,
    disable_scheduler,
    detect_sql_server_instances,
    detect_user_databases,
    emit_log
)



# Configure UI theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class BackupAutomationApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Database Cloud Backup Automation System")
        self.geometry("960, 680")
        self.minsize(860, 600)
        
        # Window icon
        icon_path = os.path.join(BASE_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.config_data = load_config()
        self.is_running = False

        self._build_layout()
        self._load_config_into_ui()
        self._refresh_schedule_status()

    def _build_layout(self):
        # ── Header Frame ──────────────────────────────────────────────
        self.header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=("#1f2937", "#111827"), height=80)
        self.header_frame.pack(fill="x", side="top")

        header_title_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        header_title_frame.pack(side="left", padx=25, pady=15)

        self.title_label = ctk.CTkLabel(
            header_title_frame,
            text="Enterprise Database Backup & Cloud Sync",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#ffffff"
        )
        self.title_label.pack(anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            header_title_frame,
            text="Automated SQL Server Backup to Google Drive & Sheets Sync",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        )
        self.subtitle_label.pack(anchor="w")

        # Status badge in header
        self.header_badge = ctk.CTkLabel(
            self.header_frame,
            text="● SYSTEM READY",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10b981",
            fg_color="#064e3b",
            corner_radius=12,
            padx=14,
            pady=6
        )
        self.header_badge.pack(side="right", padx=25, pady=20)

        # ── Main TabView ──────────────────────────────────────────────
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=15)

        self.tab_dashboard = self.tabview.add("  Dashboard  ")
        self.tab_schedule = self.tabview.add("  Auto Schedule  ")
        self.tab_settings = self.tabview.add("  Settings  ")
        self.tab_diagnostics = self.tabview.add("  Live Logs  ")

        self._build_dashboard_tab()
        self._build_schedule_tab()
        self._build_settings_tab()
        self._build_diagnostics_tab()

    # ── TAB 1: DASHBOARD ──────────────────────────────────────────────
    def _build_dashboard_tab(self):
        tab = self.tab_dashboard

        # Quick stats 3-column container
        stats_frame = ctk.CTkFrame(tab, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(10, 15))
        stats_frame.columnconfigure((0, 1, 2), weight=1, uniform="a")

        # Card 1: SQL Server
        c1 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c1.grid(row=0, column=0, padx=6, sticky="nsew")
        ctk.CTkLabel(c1, text="SQL SERVER", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=15, pady=(12, 2))
        self.card_sql_label = ctk.CTkLabel(c1, text=self.config_data.get("SQL_SERVER_NAME", "localhost"), font=ctk.CTkFont(size=14, weight="bold"))
        self.card_sql_label.pack(anchor="w", padx=15)
        dbs_count = len(self.config_data.get("TARGET_DATABASES", []))
        self.card_dbs_label = ctk.CTkLabel(c1, text=f"{dbs_count} Databases Configured", font=ctk.CTkFont(size=12), text_color="#9ca3af")
        self.card_dbs_label.pack(anchor="w", padx=15, pady=(2, 12))

        # Card 2: Cloud Sync
        c2 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c2.grid(row=0, column=1, padx=6, sticky="nsew")
        ctk.CTkLabel(c2, text="GOOGLE CLOUD SYNC", font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399").pack(anchor="w", padx=15, pady=(12, 2))
        ctk.CTkLabel(c2, text="Drive & Sheets Linked", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15)
        ctk.CTkLabel(c2, text="Compressed Level 9 ZIP", font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(anchor="w", padx=15, pady=(2, 12))

        # Card 3: Schedule
        c3 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c3.grid(row=0, column=2, padx=6, sticky="nsew")
        ctk.CTkLabel(c3, text="AUTO SCHEDULE", font=ctk.CTkFont(size=11, weight="bold"), text_color="#fbbf24").pack(anchor="w", padx=15, pady=(12, 2))
        self.card_sched_label = ctk.CTkLabel(c3, text="Mondays at 02:00 AM", font=ctk.CTkFont(size=14, weight="bold"))
        self.card_sched_label.pack(anchor="w", padx=15)
        self.card_sched_sub = ctk.CTkLabel(c3, text="Task Scheduler: Checking...", font=ctk.CTkFont(size=12), text_color="#9ca3af")
        self.card_sched_sub.pack(anchor="w", padx=15, pady=(2, 12))

        # Central Action Card
        action_card = ctk.CTkFrame(tab, corner_radius=12, fg_color=("#2e3440", "#182030"), border_width=1, border_color="#3b82f6")
        action_card.pack(fill="both", expand=True, pady=10, padx=4)

        ctk.CTkLabel(
            action_card,
            text="Manual One-Click Backup Execution",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(20, 5))

        ctk.CTkLabel(
            action_card,
            text="Runs an immediate full SQL backup, compresses with maximum deflation, uploads to Google Drive, and logs to Google Sheets.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        ).pack(pady=(0, 20))

        self.btn_run_backup = ctk.CTkButton(
            action_card,
            text="⚡  RUN FULL BACKUP NOW",
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=50,
            width=320,
            corner_radius=25,
            command=self._start_backup_thread
        )
        self.btn_run_backup.pack(pady=10)

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(action_card, width=450, height=12, corner_radius=6)
        self.progress_bar.pack(pady=(15, 8))
        self.progress_bar.set(0)

        self.status_text_label = ctk.CTkLabel(
            action_card,
            text="Ready to execute backup",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#60a5fa"
        )
        self.status_text_label.pack(pady=(0, 15))

        # Quick access row
        links_frame = ctk.CTkFrame(action_card, fg_color="transparent")
        links_frame.pack(pady=(10, 20))

        ctk.CTkButton(
            links_frame,
            text="📁 Open Local Backups",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=170,
            command=self._open_local_backup_folder
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            links_frame,
            text="☁ Open Google Drive",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=170,
            command=self._open_google_drive
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            links_frame,
            text="📊 Open Google Sheet",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=170,
            command=self._open_google_sheet
        ).pack(side="left", padx=8)

    # ── TAB 2: SCHEDULE ───────────────────────────────────────────────
    def _build_schedule_tab(self):
        tab = self.tab_schedule

        container = ctk.CTkFrame(tab, corner_radius=10, fg_color=("#374151", "#1f2937"))
        container.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            container,
            text="Windows Task Scheduler Automation",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=25, pady=(20, 5))

        ctk.CTkLabel(
            container,
            text="Set up the backup system to run completely in the background without requiring user intervention.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=25, pady=(0, 20))

        # Status row
        status_box = ctk.CTkFrame(container, fg_color=("#1e293b", "#0f172a"), corner_radius=8)
        status_box.pack(fill="x", padx=25, pady=10)

        ctk.CTkLabel(
            status_box,
            text="Current Task Status:",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=15, pady=12)

        self.sched_status_badge = ctk.CTkLabel(
            status_box,
            text="Checking...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        )
        self.sched_status_badge.pack(side="left", padx=5)

        # Options frame
        opts_frame = ctk.CTkFrame(container, fg_color="transparent")
        opts_frame.pack(fill="x", padx=25, pady=15)

        self.monday_only_switch = ctk.CTkSwitch(
            opts_frame,
            text="Strictly Mondays Only (Recommended for weekly backups)",
            font=ctk.CTkFont(size=13)
        )
        self.monday_only_switch.pack(anchor="w", pady=10)
        self.monday_only_switch.select()

        time_row = ctk.CTkFrame(opts_frame, fg_color="transparent")
        time_row.pack(anchor="w", pady=10)

        ctk.CTkLabel(time_row, text="Execution Time (24h format):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 15))
        self.entry_sched_time = ctk.CTkEntry(time_row, width=120)
        self.entry_sched_time.insert(0, self.config_data.get("SCHEDULE_TIME", "02:00"))
        self.entry_sched_time.pack(side="left")
        ctk.CTkLabel(time_row, text="(e.g. 02:00 for 2:00 AM)", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(side="left", padx=10)

        # Action buttons
        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", padx=25, pady=20)

        self.btn_enable_sched = ctk.CTkButton(
            btn_row,
            text="✔ Enable Weekly Monday Schedule",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=40,
            command=self._enable_schedule
        )
        self.btn_enable_sched.pack(side="left", padx=(0, 10))

        self.btn_disable_sched = ctk.CTkButton(
            btn_row,
            text="✖ Disable Schedule",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=40,
            command=self._disable_schedule
        )
        self.btn_disable_sched.pack(side="left", padx=10)

        ctk.CTkButton(
            btn_row,
            text="🔄 Refresh Status",
            font=ctk.CTkFont(size=13),
            fg_color="#4b5563",
            hover_color="#6b7280",
            height=40,
            command=self._refresh_schedule_status
        ).pack(side="left", padx=10)

    # ── TAB 3: SETTINGS ───────────────────────────────────────────────
    def _build_settings_tab(self):
        tab = self.tab_settings

        scroll = ctk.CTkScrollableFrame(tab, corner_radius=10, fg_color=("#374151", "#1f2937"))
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(scroll, text="Configuration & Target Parameters", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=20, pady=(15, 15))

        # SQL Server Name
        self._create_field_label(scroll, "SQL Server Instance Name:")
        sql_row = ctk.CTkFrame(scroll, fg_color="transparent")
        sql_row.pack(fill="x", padx=20, pady=(0, 10))
        self.entry_sql_server = ctk.CTkEntry(sql_row, width=370)
        self.entry_sql_server.pack(side="left", padx=(0, 10))
        ctk.CTkButton(sql_row, text="Auto-Detect", width=120, fg_color="#374151", hover_color="#4b5563", command=self._auto_detect_sql).pack(side="left")


        # SQL Auth
        auth_row = ctk.CTkFrame(scroll, fg_color="transparent")
        auth_row.pack(fill="x", padx=20, pady=(0, 10))
        
        self._create_field_label(auth_row, "SQL Username (optional, leave blank for Windows Auth):", pack_padx=0)
        self.entry_sql_user = ctk.CTkEntry(auth_row, width=240)
        self.entry_sql_user.pack(side="left", padx=(0, 15))
        
        self.entry_sql_pass = ctk.CTkEntry(auth_row, width=240, placeholder_text="SQL Password", show="*")
        self.entry_sql_pass.pack(side="left")

        # Databases
        self._create_field_label(scroll, "Target Databases (separated by commas):")
        self.entry_databases = ctk.CTkEntry(scroll, width=500)
        self.entry_databases.pack(anchor="w", padx=20, pady=(0, 10))

        # Backup folder
        self._create_field_label(scroll, "Local Backup Folder:")
        folder_row = ctk.CTkFrame(scroll, fg_color="transparent")
        folder_row.pack(fill="x", padx=20, pady=(0, 10))
        self.entry_backup_folder = ctk.CTkEntry(folder_row, width=420)
        self.entry_backup_folder.pack(side="left", padx=(0, 10))
        ctk.CTkButton(folder_row, text="Browse...", width=80, command=self._browse_backup_folder).pack(side="left")

        # Google Drive Folder ID
        self._create_field_label(scroll, "Google Drive Folder ID:")
        self.entry_drive_id = ctk.CTkEntry(scroll, width=500)
        self.entry_drive_id.pack(anchor="w", padx=20, pady=(0, 10))

        # Google Sheet ID
        self._create_field_label(scroll, "Google Sheet ID:")
        self.entry_sheet_id = ctk.CTkEntry(scroll, width=500)
        self.entry_sheet_id.pack(anchor="w", padx=20, pady=(0, 15))

        # Buttons
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=15)

        self.btn_save_config = ctk.CTkButton(
            btn_frame,
            text="💾  Save Settings",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=42,
            width=180,
            command=self._save_settings
        )
        self.btn_save_config.pack(side="left", padx=(0, 15))

        self.btn_test_conn = ctk.CTkButton(
            btn_frame,
            text="🔍  Test Google Connection",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=42,
            width=200,
            command=self._start_test_connection_thread
        )
        self.btn_test_conn.pack(side="left", padx=(0, 15))

        self.btn_switch_account = ctk.CTkButton(
            btn_frame,
            text="🔄  Switch Google Account",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#4f46e5",
            hover_color="#4338ca",
            height=42,
            width=200,
            command=self._switch_google_account
        )
        self.btn_switch_account.pack(side="left")


    def _create_field_label(self, parent, text, pack_padx=20):
        lbl = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=12, weight="bold"), text_color="#d1d5db")
        lbl.pack(anchor="w", padx=pack_padx, pady=(5, 3))
        return lbl

    # ── TAB 4: DIAGNOSTICS & LOGS ─────────────────────────────────────
    def _build_diagnostics_tab(self):
        tab = self.tab_diagnostics

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=(5, 10))

        ctk.CTkLabel(toolbar, text="Real-Time Execution Logs", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", padx=5)

        ctk.CTkButton(
            toolbar,
            text="Open Log File",
            font=ctk.CTkFont(size=12),
            width=120,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self._open_log_file
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            toolbar,
            text="Clear Screen",
            font=ctk.CTkFont(size=12),
            width=100,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self._clear_logs
        ).pack(side="right", padx=5)

        self.log_textbox = ctk.CTkTextbox(
            tab,
            corner_radius=8,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("#1e293b", "#0f172a"),
            text_color="#e2e8f0"
        )
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Initial message
        self.append_log(f"System ready. Configuration loaded from {BASE_DIR}")

    # ── LOGGING CALLBACK ──────────────────────────────────────────────
    def append_log(self, text, level="info"):
        def _update():
            self.log_textbox.insert("end", text + "\n")
            self.log_textbox.see("end")
        self.after(0, _update)

    # ── UI POPULATION & SETTINGS ──────────────────────────────────────
    def _load_config_into_ui(self):
        c = self.config_data
        self.entry_sql_server.delete(0, "end")
        self.entry_sql_server.insert(0, c.get("SQL_SERVER_NAME", "localhost\\SQLEXPRESS"))

        self.entry_sql_user.delete(0, "end")
        self.entry_sql_user.insert(0, c.get("SQL_USERNAME", ""))

        self.entry_sql_pass.delete(0, "end")
        self.entry_sql_pass.insert(0, c.get("SQL_PASSWORD", ""))

        dbs = c.get("TARGET_DATABASES", [])
        self.entry_databases.delete(0, "end")
        self.entry_databases.insert(0, ", ".join(dbs))

        self.entry_backup_folder.delete(0, "end")
        self.entry_backup_folder.insert(0, c.get("BACKUP_FOLDER", "C:\\temp\\backups"))

        self.entry_drive_id.delete(0, "end")
        self.entry_drive_id.insert(0, c.get("GOOGLE_DRIVE_FOLDER_ID", ""))

        self.entry_sheet_id.delete(0, "end")
        self.entry_sheet_id.insert(0, c.get("GOOGLE_SHEET_ID", ""))

        if c.get("STRICTLY_MONDAYS_ONLY", True):
            self.monday_only_switch.select()
        else:
            self.monday_only_switch.deselect()

    def _auto_detect_sql(self):
        instances = detect_sql_server_instances()
        if instances:
            instance_str = f"localhost\\{instances[0]}"
            self.entry_sql_server.delete(0, "end")
            self.entry_sql_server.insert(0, instance_str)
            self.append_log(f"Auto-detected SQL Server: {instance_str}")
            
            dbs = detect_user_databases(instance_str, self.entry_sql_user.get().strip(), self.entry_sql_pass.get().strip())
            if dbs:
                self.entry_databases.delete(0, "end")
                self.entry_databases.insert(0, ", ".join(dbs))
                self.append_log(f"Auto-detected databases: {', '.join(dbs)}")
                messagebox.showinfo("SQL Server Detected", f"Found SQL Server instance:\n{instance_str}\n\nDatabases found:\n{', '.join(dbs)}")
            else:
                messagebox.showinfo("SQL Server Detected", f"Found SQL Server instance:\n{instance_str}")
        else:
            messagebox.showwarning("Notice", "No local named SQL Server instances found in Windows registry.")

    def _browse_backup_folder(self):

        folder = filedialog.askdirectory(initialdir=self.entry_backup_folder.get())
        if folder:
            self.entry_backup_folder.delete(0, "end")
            self.entry_backup_folder.insert(0, folder)

    def _save_settings(self):
        dbs_str = self.entry_databases.get().strip()
        db_list = [d.strip() for d in dbs_str.split(",") if d.strip()]

        new_config = {
            "SQL_SERVER_NAME": self.entry_sql_server.get().strip(),
            "SQL_USERNAME": self.entry_sql_user.get().strip(),
            "SQL_PASSWORD": self.entry_sql_pass.get().strip(),
            "BACKUP_FOLDER": self.entry_backup_folder.get().strip(),
            "BACKUP_EXTENSION": ".zip",
            "TARGET_DATABASES": db_list,
            "GOOGLE_DRIVE_FOLDER_ID": self.entry_drive_id.get().strip(),
            "GOOGLE_SHEET_ID": self.entry_sheet_id.get().strip(),
            "STRICTLY_MONDAYS_ONLY": bool(self.monday_only_switch.get()),
            "SCHEDULE_TIME": self.entry_sched_time.get().strip() or "02:00"
        }

        ok, msg = save_config(new_config)
        if ok:
            self.config_data = new_config
            self.card_sql_label.configure(text=new_config["SQL_SERVER_NAME"])
            self.card_dbs_label.configure(text=f"{len(db_list)} Databases Configured")
            messagebox.showinfo("Saved", "Configuration saved successfully!")
        else:
            messagebox.showerror("Error", f"Failed to save configuration:\n{msg}")

    # ── TASK SCHEDULER ACTIONS ────────────────────────────────────────
    def _refresh_schedule_status(self):
        active, status_desc = get_scheduler_status()
        if active:
            self.sched_status_badge.configure(text=f"● {status_desc}", text_color="#10b981")
            self.card_sched_sub.configure(text="Task Scheduler: ACTIVE", text_color="#10b981")
        else:
            self.sched_status_badge.configure(text="○ Not Scheduled", text_color="#ef4444")
            self.card_sched_sub.configure(text="Task Scheduler: INACTIVE", text_color="#ef4444")

    def _enable_schedule(self):
        time_str = self.entry_sched_time.get().strip() or "02:00"
        self.append_log(f"Configuring Windows Task Scheduler for Mondays at {time_str}...")
        ok, msg = enable_scheduler(time_str=time_str)
        if ok:
            messagebox.showinfo("Schedule Enabled", f"Task scheduled successfully!\n\nBackups will run automatically every Monday at {time_str}.")
        else:
            messagebox.showerror("Error", f"Failed to configure Task Scheduler:\n{msg}")
        self._refresh_schedule_status()

    def _disable_schedule(self):
        if messagebox.askyesno("Confirm", "Are you sure you want to disable automatic scheduled backups?"):
            ok, msg = disable_scheduler()
            if ok:
                messagebox.showinfo("Schedule Disabled", "The automatic backup task was removed.")
            else:
                messagebox.showerror("Error", f"Failed to disable schedule:\n{msg}")
            self._refresh_schedule_status()

    # ── EXTERNAL LINKS ────────────────────────────────────────────────
    def _open_local_backup_folder(self):
        folder = self.config_data.get("BACKUP_FOLDER", "C:\\temp\\backups")
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception:
                pass
        if os.path.exists(folder):
            os.startfile(folder)
        else:
            messagebox.showwarning("Warning", f"Folder not found: {folder}")

    def _open_google_drive(self):
        folder_id = self.config_data.get("GOOGLE_DRIVE_FOLDER_ID", "")
        if folder_id:
            webbrowser.open(f"https://drive.google.com/drive/folders/{folder_id}")
        else:
            messagebox.showinfo("Notice", "Google Drive Folder ID not configured.")

    def _open_google_sheet(self):
        sheet_id = self.config_data.get("GOOGLE_SHEET_ID", "")
        if sheet_id:
            webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
        else:
            messagebox.showinfo("Notice", "Google Sheet ID not configured.")

    def _open_log_file(self):
        if os.path.exists(LOG_FILE):
            os.startfile(LOG_FILE)
        else:
            messagebox.showinfo("Log", "No log file found yet.")

    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def _switch_google_account(self):
        if messagebox.askyesno(
            "Switch Google Account", 
            "This will disconnect the current Google account and allow you to sign in with a different account.\n\n"
            "Note: Make sure your new Google account has Edit permissions to the configured Drive Folder and Google Sheet!\n\n"
            "Do you want to proceed?"
        ):
            ok, msg = reset_credentials()
            if ok:
                self.append_log("\nStored Google credentials cleared.")
                self.append_log("Starting sign-in for new Google account...")
                # Switch to live logs tab
                self.tabview.set("  Live Logs  ")
                self._start_test_connection_thread()
            else:
                messagebox.showerror("Error", msg)

    # ── TEST CONNECTION THREAD ────────────────────────────────────────
    def _start_test_connection_thread(self):

        if self.is_running:
            return
        self.btn_test_conn.configure(state="disabled", text="Testing...")
        self.append_log("\n--- Testing Google Services Connection ---")
        threading.Thread(target=self._run_test_connection, daemon=True).start()

    def _run_test_connection(self):
        try:
            creds = authenticate(interactive=True, log_cb=self.append_log)
            res = test_google_connection(
                creds,
                drive_folder_id=self.entry_drive_id.get().strip(),
                sheet_id=self.entry_sheet_id.get().strip(),
                log_cb=self.append_log
            )
            
            if res["auth"] and res["drive"] and res["sheet"]:
                msg = f"SUCCESS!\n\nDrive Folder: {res['drive_name']}\nGoogle Sheet: {res['sheet_title']}"
                self.after(0, lambda: messagebox.showinfo("Connection OK", msg))
            else:
                err_text = "\n".join(res["errors"])
                self.after(0, lambda: messagebox.showerror("Connection Failed", f"Issues detected:\n\n{err_text}"))
        except Exception as e:
            self.append_log(f"Test error: {e}", "error")
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, lambda: self.btn_test_conn.configure(state="normal", text="🔍  Test Google Connection"))

    # ── BACKUP WORKFLOW THREAD ────────────────────────────────────────
    def _start_backup_thread(self):
        if self.is_running:
            messagebox.showwarning("Busy", "A backup workflow is already running!")
            return

        self.is_running = True
        self.btn_run_backup.configure(state="disabled", text="⏳  BACKUP IN PROGRESS...")
        self.header_badge.configure(text="● BACKUP RUNNING", text_color="#fbbf24", fg_color="#78350f")
        self.progress_bar.set(0.05)
        self.status_text_label.configure(text="Initializing backup workflow...")
        
        # Switch to logs tab so user can see progress immediately
        self.tabview.set("  Live Logs  ")

        threading.Thread(target=self._execute_backup_worker, daemon=True).start()

    def _execute_backup_worker(self):
        def update_progress(val):
            self.after(0, lambda: self.progress_bar.set(val))

        def update_status(text):
            self.after(0, lambda: self.status_text_label.configure(text=text))

        try:
            success, summary = run_full_backup(
                config=self.config_data,
                log_cb=self.append_log,
                progress_cb=update_progress,
                status_cb=update_status
            )
            if success:
                self.after(0, lambda: messagebox.showinfo("Backup Finished", summary))
            else:
                self.after(0, lambda: messagebox.showwarning("Completed with Warnings", summary))
        except Exception as e:
            self.append_log(f"Fatal execution error: {e}", "critical")
            self.after(0, lambda: messagebox.showerror("Fatal Error", f"Workflow failed:\n{e}"))
        finally:
            def _reset_ui():
                self.is_running = False
                self.btn_run_backup.configure(state="normal", text="⚡  RUN FULL BACKUP NOW")
                self.header_badge.configure(text="● SYSTEM READY", text_color="#10b981", fg_color="#064e3b")
                self.status_text_label.configure(text="Ready to execute backup")
            self.after(0, _reset_ui)

def main():
    app = BackupAutomationApp()
    app.mainloop()

if __name__ == "__main__":
    main()
