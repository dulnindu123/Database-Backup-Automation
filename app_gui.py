"""
Enterprise Database Cloud Backup Automation - Desktop Graphical Interface
=============================================================================
Author: Dulnindu Saranga
Architecture: Presentation Layer (CustomTkinter Windows 11 GUI)

Key Architectural & Design Decisions:
1. Concurrency & Threading:
   - Database operations (sqlcmd) and multi-megabyte cloud uploads (Google Drive) 
     are highly I/O intensive.
   - All heavy operations run in dedicated background daemon threads 
     (threading.Thread(target=..., daemon=True)).
   - This ensures the UI thread remains 100% fluid, responsive, and never enters
     Windows' "Not Responding" frozen state.

2. Thread-Safe Event Dispatching:
   - Python Tkinter widgets cannot be safely mutated from background threads.
   - All progress updates, status messages, and log records are marshaled back to 
     the main GUI thread using self.after(0, callback).

3. Tabular Workflow Layout:
   - Dashboard: Real-time status cards, one-click execution, quick links, storage purge.
   - Auto Schedule: Windows Task Scheduler integration (Monday 02:00 AM automation).
   - Settings: Visual configuration for SQL instances, databases, and Google IDs.
   - Live Logs: Monospace terminal autoscrolling through live execution telemetry.
"""

import os
import sys
import json
import webbrowser
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Allow Google OAuth scope relaxation (prevents ScopeChangedError)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# Import headless, thread-safe core engine functions
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
    cleanup_local_backup_folder,
    format_file_size,
    grant_sql_folder_permissions,
    stop_active_backup,
    is_backup_cancelled,
    emit_log
)

# -----------------------------------------------------------------------------
# APPLICATION THEME CONFIGURATION
# -----------------------------------------------------------------------------
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class BackupAutomationApp(ctk.CTk):
    """
    Main Application Window for Enterprise Database Cloud Backup Automation.
    Inherits from customtkinter.CTk to render dark-mode Windows 11 controls.
    """
    def __init__(self):
        super().__init__()

        # Window properties
        self.title("Database Cloud Backup Automation System")
        self.geometry("960, 680")
        self.minsize(860, 600)
        
        # Load window icon
        icon_path = os.path.join(BASE_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Load active configuration and initialize execution flags
        self.config_data = load_config()
        self.is_running = False
        self.was_cancelled = False

        # Build UI components
        self._build_layout()
        self._load_config_into_ui()
        self._refresh_schedule_status()

    # =========================================================================
    # MASTER LAYOUT BUILDER
    # =========================================================================
    def _build_layout(self):
        """Builds header banner, status badge, and primary tabbed container."""
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

        # Global status pill badge
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

        # Global Emergency Stop button (in header, visible across all tabs during backup)
        self.btn_header_stop = ctk.CTkButton(
            self.header_frame,
            text="⏹  STOP BACKUP",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            text_color="#ffffff",
            height=34,
            width=135,
            corner_radius=17,
            command=self._stop_backup
        )

        # ── Main TabView ──────────────────────────────────────────────
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=15)

        self.tab_dashboard = self.tabview.add("  Dashboard  ")
        self.tab_schedule = self.tabview.add("  Auto Schedule  ")
        self.tab_settings = self.tabview.add("  Settings  ")
        self.tab_diagnostics = self.tabview.add("  Live Logs  ")

        # Initialize individual tabs
        self._build_dashboard_tab()
        self._build_schedule_tab()
        self._build_settings_tab()
        self._build_diagnostics_tab()

    # =========================================================================
    # TAB 1: DASHBOARD
    # =========================================================================
    def _build_dashboard_tab(self):
        """Builds quick-metric status cards, one-click backup button, and links."""
        tab = self.tab_dashboard

        # Quick stats 3-column container
        stats_frame = ctk.CTkFrame(tab, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(10, 15))
        stats_frame.columnconfigure((0, 1, 2), weight=1, uniform="a")

        # Card 1: SQL Server Status
        c1 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c1.grid(row=0, column=0, padx=6, sticky="nsew")
        ctk.CTkLabel(c1, text="SQL SERVER", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=15, pady=(12, 2))
        self.card_sql_label = ctk.CTkLabel(c1, text=self.config_data.get("SQL_SERVER_NAME", "localhost"), font=ctk.CTkFont(size=14, weight="bold"))
        self.card_sql_label.pack(anchor="w", padx=15)
        dbs_count = len(self.config_data.get("TARGET_DATABASES", []))
        self.card_dbs_label = ctk.CTkLabel(c1, text=f"{dbs_count} Databases Configured", font=ctk.CTkFont(size=12), text_color="#9ca3af")
        self.card_dbs_label.pack(anchor="w", padx=15, pady=(2, 12))

        # Card 2: Cloud Sync Status
        c2 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c2.grid(row=0, column=1, padx=6, sticky="nsew")
        ctk.CTkLabel(c2, text="GOOGLE CLOUD SYNC", font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399").pack(anchor="w", padx=15, pady=(12, 2))
        ctk.CTkLabel(c2, text="Drive & Sheets Linked", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15)
        ctk.CTkLabel(c2, text="Compressed Level 9 ZIP", font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(anchor="w", padx=15, pady=(2, 12))

        # Card 3: Scheduler Status
        c3 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c3.grid(row=0, column=2, padx=6, sticky="nsew")
        ctk.CTkLabel(c3, text="AUTO SCHEDULE", font=ctk.CTkFont(size=11, weight="bold"), text_color="#fbbf24").pack(anchor="w", padx=15, pady=(12, 2))
        self.card_sched_label = ctk.CTkLabel(c3, text="Mondays at 02:00 AM", font=ctk.CTkFont(size=14, weight="bold"))
        self.card_sched_label.pack(anchor="w", padx=15)
        self.card_sched_sub = ctk.CTkLabel(c3, text="Task Scheduler: Checking...", font=ctk.CTkFont(size=12), text_color="#9ca3af")
        self.card_sched_sub.pack(anchor="w", padx=15, pady=(2, 12))

        # Central Action Card (Run Backup Now)
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

        # Action button dual container
        btn_action_box = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_action_box.pack(pady=10)

        self.btn_run_backup = ctk.CTkButton(
            btn_action_box,
            text="⚡  RUN FULL BACKUP NOW",
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=48,
            width=260,
            corner_radius=24,
            command=self._start_backup_thread
        )
        self.btn_run_backup.pack(side="left", padx=6)

        self.btn_stop_backup = ctk.CTkButton(
            btn_action_box,
            text="⏹  STOP BACKUP",
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=48,
            width=170,
            corner_radius=24,
            state="disabled",
            command=self._stop_backup
        )
        self.btn_stop_backup.pack(side="left", padx=6)

        # Dynamic progress bar
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

        # Quick access action buttons
        links_frame = ctk.CTkFrame(action_card, fg_color="transparent")
        links_frame.pack(pady=(10, 20))

        # Button 1: Open Local Backups Folder
        ctk.CTkButton(
            links_frame,
            text="📁 Open Backups",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=135,
            command=self._open_local_backup_folder
        ).pack(side="left", padx=5)

        # Button 2: Open Google Drive Folder
        ctk.CTkButton(
            links_frame,
            text="☁ Open Drive",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=135,
            command=self._open_google_drive
        ).pack(side="left", padx=5)

        # Button 3: Open Google Sheet Audit Log
        ctk.CTkButton(
            links_frame,
            text="📊 Open Sheet",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=135,
            command=self._open_google_sheet
        ).pack(side="left", padx=5)

        # Button 4: Clean Local Storage Drive
        ctk.CTkButton(
            links_frame,
            text="🧹 Clean Storage",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#dc2626",
            width=135,
            command=self._clean_local_storage
        ).pack(side="left", padx=5)

    # =========================================================================
    # TAB 2: SCHEDULE & WINDOWS SERVICE AUTOMATION
    # =========================================================================
    def _build_schedule_tab(self):
        """Builds controls to configure Unattended Windows System Service or User Schedule."""
        tab = self.tab_schedule

        scroll = ctk.CTkScrollableFrame(tab, corner_radius=10, fg_color=("#374151", "#1f2937"))
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            scroll,
            text="Unattended Automation & Windows Service Engine",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            scroll,
            text="Configure automated backups to execute in the background with zero human intervention.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=20, pady=(0, 15))

        # Status row box
        status_box = ctk.CTkFrame(scroll, fg_color=("#1e293b", "#0f172a"), corner_radius=8)
        status_box.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            status_box,
            text="Current Engine Status:",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=15, pady=12)

        self.sched_status_badge = ctk.CTkLabel(
            status_box,
            text="Checking...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        )
        self.sched_status_badge.pack(side="left", padx=5)

        # ── Mode Selection Card ───────────────────────────────────────
        mode_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        mode_card.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            mode_card,
            text="EXECUTION SECURITY CONTEXT (SERVICE LEVEL)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#60a5fa"
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.sched_mode_var = tk.StringVar(value="SYSTEM")

        # Option A: System Service
        self.radio_system = ctk.CTkRadioButton(
            mode_card,
            text="Unattended Windows System Service (Recommended for Windows Server & RDP)",
            variable=self.sched_mode_var,
            value="SYSTEM",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.radio_system.pack(anchor="w", padx=15, pady=(5, 2))

        ctk.CTkLabel(
            mode_card,
            text="• Runs under NT AUTHORITY\\SYSTEM in Session 0 with highest privileges.\n"
                 "• Operates 100% unattended before any user logs in, survives reboots, and is never disrupted by RDP logoffs.",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af",
            justify="left"
        ).pack(anchor="w", padx=40, pady=(0, 10))

        # Option B: Standard User Task
        self.radio_user = ctk.CTkRadioButton(
            mode_card,
            text="Standard User Task (Interactive Desktop Only)",
            variable=self.sched_mode_var,
            value="USER",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.radio_user.pack(anchor="w", padx=15, pady=(5, 2))

        ctk.CTkLabel(
            mode_card,
            text="• Runs under your current Windows user account (/rl LIMITED).\n"
                 "• Requires no administrator rights, but only executes when you are actively logged into Windows.",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af",
            justify="left"
        ).pack(anchor="w", padx=40, pady=(0, 12))

        # ── Trigger & Time Settings ───────────────────────────────────
        trigger_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        trigger_card.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            trigger_card,
            text="SCHEDULE PARAMETERS & RECOVERY TRIGGERS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399"
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.monday_only_switch = ctk.CTkSwitch(
            trigger_card,
            text="Strictly Mondays Only (Recommended for weekly disaster recovery cycles)",
            font=ctk.CTkFont(size=13)
        )
        self.monday_only_switch.pack(anchor="w", padx=15, pady=(5, 8))
        self.monday_only_switch.select()

        time_row = ctk.CTkFrame(trigger_card, fg_color="transparent")
        time_row.pack(anchor="w", padx=15, pady=(0, 8))

        ctk.CTkLabel(time_row, text="Execution Time (24h format):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 15))
        self.entry_sched_time = ctk.CTkEntry(time_row, width=120)
        self.entry_sched_time.insert(0, self.config_data.get("SCHEDULE_TIME", "02:00"))
        self.entry_sched_time.pack(side="left")
        ctk.CTkLabel(time_row, text="(e.g. 02:00 for 2:00 AM)", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(side="left", padx=10)

        self.chk_boot_trigger = ctk.CTkCheckBox(
            trigger_card,
            text="Register Startup Recovery Trigger (Automatically execute at system boot if missed)",
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db"
        )
        self.chk_boot_trigger.pack(anchor="w", padx=15, pady=(0, 12))
        self.chk_boot_trigger.select()

        # ── Action Buttons Row ─────────────────────────────────────────
        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(5, 15))

        self.btn_enable_sched = ctk.CTkButton(
            btn_row,
            text="✔ Apply & Enable Automation",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=42,
            width=220,
            command=self._enable_schedule
        )
        self.btn_enable_sched.pack(side="left", padx=(0, 10))

        self.btn_disable_sched = ctk.CTkButton(
            btn_row,
            text="✖ Disable Automation",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=42,
            width=180,
            command=self._disable_schedule
        )
        self.btn_disable_sched.pack(side="left", padx=10)

        ctk.CTkButton(
            btn_row,
            text="🔄 Refresh Status",
            font=ctk.CTkFont(size=13),
            fg_color="#4b5563",
            hover_color="#6b7280",
            height=42,
            width=140,
            command=self._refresh_schedule_status
        ).pack(side="left", padx=10)

    # =========================================================================
    # TAB 3: SETTINGS
    # =========================================================================
    def _build_settings_tab(self):
        """Builds parameter configuration form for SQL Server and Google Cloud targets."""
        tab = self.tab_settings

        scroll = ctk.CTkScrollableFrame(tab, corner_radius=10, fg_color=("#374151", "#1f2937"))
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(scroll, text="Configuration & Target Parameters", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=20, pady=(15, 15))

        # SQL Server Instance Name + Auto-detect button
        self._create_field_label(scroll, "SQL Server Instance Name:")
        sql_row = ctk.CTkFrame(scroll, fg_color="transparent")
        sql_row.pack(fill="x", padx=20, pady=(0, 10))
        self.entry_sql_server = ctk.CTkEntry(sql_row, width=370)
        self.entry_sql_server.pack(side="left", padx=(0, 10))
        ctk.CTkButton(sql_row, text="Auto-Detect", width=120, fg_color="#374151", hover_color="#4b5563", command=self._auto_detect_sql).pack(side="left")

        # SQL Authentication fields (optional)
        auth_row = ctk.CTkFrame(scroll, fg_color="transparent")
        auth_row.pack(fill="x", padx=20, pady=(0, 10))
        
        self._create_field_label(auth_row, "SQL Username (optional, leave blank for Windows Auth):", pack_padx=0)
        self.entry_sql_user = ctk.CTkEntry(auth_row, width=240)
        self.entry_sql_user.pack(side="left", padx=(0, 15))
        
        self.entry_sql_pass = ctk.CTkEntry(auth_row, width=240, placeholder_text="SQL Password", show="*")
        self.entry_sql_pass.pack(side="left")

        # Target Databases List
        self._create_field_label(scroll, "Target Databases (separated by commas):")
        self.entry_databases = ctk.CTkEntry(scroll, width=500)
        self.entry_databases.pack(anchor="w", padx=20, pady=(0, 10))

        # Local Backup Directory
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
        self.entry_sheet_id.pack(anchor="w", padx=20, pady=(0, 10))

        # Storage Management / Zero-Footprint Toggle
        self.chk_delete_local = ctk.CTkCheckBox(
            scroll,
            text="Delete local backup file after upload (Preserves local storage drive space)",
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db"
        )
        self.chk_delete_local.pack(anchor="w", padx=20, pady=(5, 15))

        # Action Buttons row
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

        # ── Danger Zone / Application Lifecycle ─────────────────────────
        danger_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#1f2937", "#111827"), border_width=1, border_color="#374151")
        danger_frame.pack(fill="x", padx=20, pady=(25, 20))

        danger_top = ctk.CTkFrame(danger_frame, fg_color="transparent")
        danger_top.pack(fill="x", padx=15, pady=(12, 6))

        ctk.CTkLabel(
            danger_top,
            text="APPLICATION LIFECYCLE & UNINSTALL",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#ef4444"
        ).pack(side="left")

        ctk.CTkLabel(
            danger_frame,
            text="Completely remove Database Cloud Backup, scheduled backup tasks, and desktop shortcuts from this PC.",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=15, pady=(0, 10))

        self.btn_uninstall_app = ctk.CTkButton(
            danger_frame,
            text="🗑️  Uninstall Application",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            text_color="#fca5a5",
            height=34,
            width=180,
            command=self._launch_uninstaller
        )
        self.btn_uninstall_app.pack(anchor="w", padx=15, pady=(0, 12))

    def _create_field_label(self, parent, text, pack_padx=20):
        lbl = ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=12, weight="bold"), text_color="#d1d5db")
        lbl.pack(anchor="w", padx=pack_padx, pady=(5, 3))
        return lbl

    def _launch_uninstaller(self):
        """
        Launches the robust uninstaller script and terminates the application cleanly.
        """
        if not messagebox.askyesno(
            "Confirm Uninstallation",
            "Are you sure you want to completely uninstall Database Cloud Backup?\n\n"
            "This will permanently remove the application files, desktop shortcuts, "
            "and Windows Task Scheduler jobs."
        ):
            return

        uninstall_candidates = [
            os.path.join(BASE_DIR, "Uninstall.bat"),
            os.path.join(os.path.dirname(BASE_DIR), "Uninstall.bat"),
            os.path.join(os.environ.get("LOCALAPPDATA", "C:\\"), "Programs", "DatabaseBackupApp", "Uninstall.bat")
        ]
        uninstaller_path = None
        for cand in uninstall_candidates:
            if os.path.exists(cand):
                uninstaller_path = cand
                break

        if uninstaller_path and os.path.exists(uninstaller_path):
            subprocess.Popen(f'start "" "{uninstaller_path}" "{BASE_DIR}"', shell=True)
            self.destroy()
            sys.exit(0)
        else:
            messagebox.showerror(
                "Uninstaller Not Found",
                f"Could not locate Uninstall.bat in {BASE_DIR}.\n"
                "Please run uninstallation via Windows Settings > Installed Apps."
            )

    # =========================================================================
    # TAB 4: DIAGNOSTICS & LIVE LOGS
    # =========================================================================
    def _build_diagnostics_tab(self):
        """Builds terminal display for live execution telemetry."""
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

        # Initial startup message
        self.append_log(f"System ready. Configuration loaded from {BASE_DIR}")

    # =========================================================================
    # THREAD-SAFE LOGGING CALLBACK
    # =========================================================================
    def append_log(self, text, level="info"):
        """
        Thread-safe logger method passed into the core engine callbacks.
        Uses self.after(0, ...) to marshal UI inserts onto Tkinter's main loop.
        """
        def _update():
            self.log_textbox.insert("end", text + "\n")
            self.log_textbox.see("end")
        self.after(0, _update)

    # =========================================================================
    # CONFIGURATION & SETTINGS CONTROLLERS
    # =========================================================================
    def _load_config_into_ui(self):
        """Populates UI input fields from self.config_data."""
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

        if c.get("DELETE_LOCAL_AFTER_UPLOAD", True):
            self.chk_delete_local.select()
        else:
            self.chk_delete_local.deselect()

    def _auto_detect_sql(self):
        """Queries Windows Registry for local SQL Server instances and databases."""
        instances = detect_sql_server_instances()
        if instances:
            instance_str = f"localhost\\{instances[0]}"
            self.entry_sql_server.delete(0, "end")
            self.entry_sql_server.insert(0, instance_str)
            self.append_log(f"Auto-detected SQL Server instance: {instance_str}")
            
            dbs = detect_user_databases(instance_str, self.entry_sql_user.get().strip(), self.entry_sql_pass.get().strip())
            if dbs:
                self.entry_databases.delete(0, "end")
                self.entry_databases.insert(0, ", ".join(dbs))
                self.append_log(f"Auto-detected databases: {', '.join(dbs)}")
                messagebox.showinfo("SQL Server Detected", f"Found SQL Server instance:\n{instance_str}\n\nDatabases discovered:\n{', '.join(dbs)}")
            else:
                messagebox.showinfo("SQL Server Detected", f"Found SQL Server instance:\n{instance_str}")
        else:
            messagebox.showwarning("Notice", "No local named SQL Server instances found in Windows Registry.")

    def _browse_backup_folder(self):
        """Displays Windows folder picker for local backup directory."""
        folder = filedialog.askdirectory(initialdir=self.entry_backup_folder.get())
        if folder:
            norm_folder = os.path.normpath(folder)
            self.entry_backup_folder.delete(0, "end")
            self.entry_backup_folder.insert(0, norm_folder)
            grant_sql_folder_permissions(norm_folder)

    def _save_settings(self):
        """Validates and persists updated settings to config.json."""
        dbs_str = self.entry_databases.get().strip()
        db_list = [d.strip() for d in dbs_str.split(",") if d.strip()]
        backup_dir = os.path.normpath(self.entry_backup_folder.get().strip())
        if backup_dir:
            grant_sql_folder_permissions(backup_dir)

        new_config = {
            "SQL_SERVER_NAME": self.entry_sql_server.get().strip(),
            "SQL_USERNAME": self.entry_sql_user.get().strip(),
            "SQL_PASSWORD": self.entry_sql_pass.get().strip(),
            "BACKUP_FOLDER": backup_dir,
            "BACKUP_EXTENSION": ".zip",
            "TARGET_DATABASES": db_list,
            "GOOGLE_DRIVE_FOLDER_ID": self.entry_drive_id.get().strip(),
            "GOOGLE_SHEET_ID": self.entry_sheet_id.get().strip(),
            "STRICTLY_MONDAYS_ONLY": bool(self.monday_only_switch.get()),
            "SCHEDULE_TIME": self.entry_sched_time.get().strip() or "02:00",
            "DELETE_LOCAL_AFTER_UPLOAD": bool(self.chk_delete_local.get())
        }

        ok, msg = save_config(new_config)
        if ok:
            self.config_data = new_config
            self.card_sql_label.configure(text=new_config["SQL_SERVER_NAME"])
            self.card_dbs_label.configure(text=f"{len(db_list)} Databases Configured")
            messagebox.showinfo("Saved", "Configuration saved successfully!")
        else:
            messagebox.showerror("Error", f"Failed to save configuration:\n{msg}")

    # =========================================================================
    # TASK SCHEDULER & WINDOWS SERVICE CONTROLLERS
    # =========================================================================
    def _refresh_schedule_status(self):
        """Queries Windows Task Scheduler and updates the UI status badge."""
        active, status_desc, mode = get_scheduler_status()
        if active:
            if mode == "SYSTEM_SERVICE":
                self.sched_status_badge.configure(text=f"● {status_desc}", text_color="#10b981")
                self.sched_mode_var.set("SYSTEM")
            else:
                self.sched_status_badge.configure(text=f"● {status_desc}", text_color="#60a5fa")
                self.sched_mode_var.set("USER")
            self.card_sched_sub.configure(text="Automation: ACTIVE", text_color="#10b981")
        else:
            self.sched_status_badge.configure(text="○ Not Scheduled", text_color="#9ca3af")
            self.card_sched_sub.configure(text="Automation: INACTIVE", text_color="#9ca3af")

    def _enable_schedule(self):
        """Enables the recurring schedule as either a Windows System Service or User Task."""
        time_str = self.entry_sched_time.get().strip() or "02:00"
        as_system = (self.sched_mode_var.get() == "SYSTEM")
        on_boot = bool(self.chk_boot_trigger.get())
        
        mode_label = "Unattended System Service (Session 0)" if as_system else "Standard User Task"
        self.append_log(f"Configuring Windows automation ({mode_label}) for Mondays at {time_str}...")
        
        ok, msg = enable_scheduler(time_str=time_str, as_system_service=as_system, on_boot=on_boot)
        if ok:
            messagebox.showinfo("Automation Configured", f"{msg}\n\nSchedule: Every Monday at {time_str}\nMode: {mode_label}")
        else:
            messagebox.showerror("Configuration Error", f"Failed to configure automation:\n{msg}")
        self._refresh_schedule_status()

    def _disable_schedule(self):
        """Removes all recurring automation tasks from Windows."""
        if messagebox.askyesno("Confirm", "Are you sure you want to disable all automatic backup schedules and services?"):
            ok, msg = disable_scheduler()
            if ok:
                messagebox.showinfo("Automation Disabled", "All automatic backup schedules and service triggers were removed.")
            else:
                messagebox.showerror("Error", f"Failed to disable automation:\n{msg}")
            self._refresh_schedule_status()

    # =========================================================================
    # EXTERNAL TOOLS & STORAGE MAINTENANCE
    # =========================================================================
    def _open_local_backup_folder(self):
        """Opens local backup directory in Windows File Explorer."""
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

    def _clean_local_storage(self):
        """Prompts and executes on-demand sweep of local residual backup files."""
        folder = self.config_data.get("BACKUP_FOLDER", "C:\\temp\\backups")
        if not os.path.exists(folder):
            messagebox.showinfo("Storage Cleaned", f"Backup folder does not exist yet:\n{folder}\n0 files found.")
            return

        if messagebox.askyesno("Clean Storage Drive", f"Delete all residual backup files (.bak and .zip) from:\n{folder}\n\nProceed to free local storage drive space?"):
            deleted, freed = cleanup_local_backup_folder(folder=folder, log_cb=self.append_log)
            if deleted > 0:
                messagebox.showinfo("Storage Cleaned", f"Successfully cleaned storage drive!\nRemoved: {deleted} files\nSpace freed: {format_file_size(freed)}")
            else:
                messagebox.showinfo("Storage Cleaned", "Storage drive is already clean.\n0 residual backup files found.")

    def _open_google_drive(self):
        """Opens configured Google Drive folder in default web browser."""
        folder_id = self.config_data.get("GOOGLE_DRIVE_FOLDER_ID", "")
        if folder_id:
            webbrowser.open(f"https://drive.google.com/drive/folders/{folder_id}")
        else:
            messagebox.showinfo("Notice", "Google Drive Folder ID not configured.")

    def _open_google_sheet(self):
        """Opens configured Google Sheet audit trail in default web browser."""
        sheet_id = self.config_data.get("GOOGLE_SHEET_ID", "")
        if sheet_id:
            webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
        else:
            messagebox.showinfo("Notice", "Google Sheet ID not configured.")

    def _open_log_file(self):
        """Opens backup_log.txt in default text editor."""
        if os.path.exists(LOG_FILE):
            os.startfile(LOG_FILE)
        else:
            messagebox.showinfo("Log", "No log file found yet.")

    def _clear_logs(self):
        """Clears the live log viewer textbox."""
        self.log_textbox.delete("1.0", "end")

    def _switch_google_account(self):
        """Disconnects current Google account by deleting cached token.json."""
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
                self.tabview.set("  Live Logs  ")
                self._start_test_connection_thread()
            else:
                messagebox.showerror("Error", msg)

    # =========================================================================
    # ASYNCHRONOUS THREADING: TEST CONNECTION
    # =========================================================================
    def _start_test_connection_thread(self):
        """Spawns non-blocking daemon thread to test Google connection."""
        if self.is_running:
            return
        self.btn_test_conn.configure(state="disabled", text="Testing...")
        self.append_log("\n--- Testing Google Services Connection ---")
        threading.Thread(target=self._run_test_connection, daemon=True).start()

    def _run_test_connection(self):
        """Background worker validating Google Drive and Google Sheets connectivity."""
        try:
            creds = authenticate(interactive=True, log_cb=self.append_log)
            res = test_google_connection(
                creds,
                drive_folder_id=self.entry_drive_id.get().strip(),
                sheet_id=self.entry_sheet_id.get().strip(),
                log_cb=self.append_log
            )
            
            if res["auth"] and res["drive"] and res["sheet"]:
                msg = f"SUCCESS!\n\nDrive Destination: {res['drive_name']}\nGoogle Sheet: {res['sheet_title']}"
                self.after(0, lambda: messagebox.showinfo("Connection OK", msg))
            else:
                err_text = "\n".join(res["errors"])
                self.after(0, lambda: messagebox.showerror("Connection Failed", f"Issues detected:\n\n{err_text}"))
        except Exception as e:
            self.append_log(f"Test error: {e}", "error")
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, lambda: self.btn_test_conn.configure(state="normal", text="🔍  Test Google Connection"))

    # =========================================================================
    # ASYNCHRONOUS THREADING: FULL BACKUP WORKFLOW
    # =========================================================================
    def _start_backup_thread(self):
        """Spawns non-blocking daemon thread to execute the full backup pipeline."""
        if self.is_running:
            messagebox.showwarning("Busy", "A backup workflow is already running!")
            return

        self.is_running = True
        self.was_cancelled = False
        self.btn_run_backup.configure(state="disabled", text="⏳  BACKUP IN PROGRESS...")
        self.btn_stop_backup.configure(state="normal", text="⏹  STOP BACKUP")
        self.btn_header_stop.configure(state="normal", text="⏹  STOP BACKUP")
        self.btn_header_stop.pack(side="right", padx=(0, 15), pady=20)
        self.header_badge.configure(text="● BACKUP RUNNING", text_color="#fbbf24", fg_color="#78350f")
        self.progress_bar.set(0.05)
        self.status_text_label.configure(text="Initializing backup workflow...")
        
        # Switch to live logs tab so the user sees real-time progress immediately
        self.tabview.set("  Live Logs  ")

        threading.Thread(target=self._execute_backup_worker, daemon=True).start()

    def _stop_backup(self):
        """Emergency stop handler invoked from Header or Dashboard."""
        if not self.is_running:
            return

        if messagebox.askyesno("Emergency Stop", "Are you sure you want to immediately stop the backup and upload process?"):
            self.was_cancelled = True
            self.append_log(">>> USER TRIGGERED EMERGENCY STOP <<<", "warning")
            self.status_text_label.configure(text="Stopping backup operations...")
            self.header_badge.configure(text="● STOPPING...", text_color="#f87171", fg_color="#7f1d1d")
            self.btn_stop_backup.configure(state="disabled", text="Stopping...")
            self.btn_header_stop.configure(state="disabled", text="Stopping...")
            stop_active_backup()

    def _execute_backup_worker(self):
        """
        Background worker executing the complete backup cycle.
        Thread-safe marshaling is used for all UI updates.
        """
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
            if self.was_cancelled or is_backup_cancelled():
                self.after(0, lambda: messagebox.showinfo("Backup Stopped", "The backup and cloud sync process was safely stopped.\n\nAll temporary files have been cleaned up."))
            elif success:
                self.after(0, lambda: messagebox.showinfo("Backup Finished", summary))
            else:
                self.after(0, lambda: messagebox.showwarning("Completed with Warnings", summary))
        except Exception as e:
            if self.was_cancelled or is_backup_cancelled():
                self.append_log("Backup process terminated cleanly.", "info")
            else:
                self.append_log(f"Fatal execution error: {e}", "critical")
                self.after(0, lambda: messagebox.showerror("Fatal Error", f"Workflow failed:\n{e}"))
        finally:
            def _reset_ui():
                self.is_running = False
                self.btn_run_backup.configure(state="normal", text="⚡  RUN FULL BACKUP NOW")
                self.btn_stop_backup.configure(state="disabled", text="⏹  STOP BACKUP")
                self.btn_header_stop.pack_forget()
                if self.was_cancelled or is_backup_cancelled():
                    self.header_badge.configure(text="● STOPPED", text_color="#ef4444", fg_color="#450a0a")
                    self.status_text_label.configure(text="Backup stopped by user")
                    self.progress_bar.set(0)
                else:
                    self.header_badge.configure(text="● SYSTEM READY", text_color="#10b981", fg_color="#064e3b")
                    self.status_text_label.configure(text="Ready to execute backup")
                self.was_cancelled = False
            self.after(0, _reset_ui)


def main():
    """Launches the desktop GUI application."""
    app = BackupAutomationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
