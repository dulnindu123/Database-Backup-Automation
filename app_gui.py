APP_VERSION = "v4.1.0"
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
   - This ensures the UI thread remains fully fluid, responsive, and never enters
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
import subprocess
import sys
import re
import json
import webbrowser
import threading
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Allow Google OAuth scope relaxation (prevents ScopeChangedError)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from version import get_build_id, get_build_info, DEFAULT_TASK_NAME, APP_VERSION

# Import headless, thread-safe core engine functions
from backup_core import (
    DEFAULT_SHEET_TABS,
    extract_google_id,
    build_google_drive_url,
    build_google_sheet_url,
    BASE_DIR,
    DATA_DIR,
    LOG_FILE,
    load_config,
    save_config,
    test_broker_connection,
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
    emit_log,
    open_path_native,
    # Section 9: Server Clean Up — Storage Monitor
    scan_storage_drives,
    run_storage_monitor,
    send_test_storage_email
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

        self.build_id = get_build_id()
        # Window properties
        self.title(f"Database Cloud Backup Automation System - {self.build_id}")
        self.geometry("960, 680")
        self.minsize(860, 600)
        
        # Load window icon with cross-platform fallback (ICO for Windows, PNG for macOS/Linux)
        icon_path_ico = os.path.join(BASE_DIR, "app_icon.ico")
        icon_path_png = os.path.join(BASE_DIR, "app_icon.png")
        if sys.platform.startswith("win") and os.path.exists(icon_path_ico):
            try:
                self.iconbitmap(icon_path_ico)
            except Exception:
                pass
        elif os.path.exists(icon_path_png):
            try:
                img = tk.PhotoImage(file=icon_path_png)
                self.wm_iconphoto(True, img)
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
        emit_log(f"Database Cloud Backup GUI Initialized. Build ID: {self.build_id}")

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
            text=f"Zero-Trust Database Cloud Backup & Multi-Module Monitoring ({self.build_id})",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        )
        self.subtitle_label.pack(anchor="w")

        # Global status pill badge - Initialized to UNVERIFIED (Round 9 Requirement 1)
        self.header_badge = ctk.CTkLabel(
            self.header_frame,
            text="● INITIALIZING / UNTESTED",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9ca3af",
            fg_color="#374151",
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
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(15, 5))

        self.tab_dashboard = self.tabview.add("  Dashboard  ")
        self.tab_schedule = self.tabview.add("  Auto Schedule  ")
        self.tab_settings = self.tabview.add("  Settings  ")
        self.tab_diagnostics = self.tabview.add("  Live Logs  ")
        self.tab_server_health = self.tabview.add("  Server Health  ")
        self.tab_performance = self.tabview.add("  Performance Query  ")

        # Initialize individual tabs
        self._build_dashboard_tab()
        self._build_schedule_tab()
        self._build_settings_tab()
        self._build_diagnostics_tab()
        self._build_server_health_tab()
        self._build_performance_tab()

        # ── Bottom Footer Bar (Version Number Display) ────────────────
        self.footer_frame = ctk.CTkFrame(self, fg_color="transparent", height=24)
        self.footer_frame.pack(fill="x", side="bottom", padx=25, pady=(0, 6))

        self.footer_status_label = ctk.CTkLabel(
            self.footer_frame,
            text="Enterprise Database Cloud Backup & Server Health Monitor",
            font=ctk.CTkFont(size=11),
            text_color="#6b7280"
        )
        self.footer_status_label.pack(side="left")

        b_info = get_build_info()
        b_str = f"v{b_info.get('version', APP_VERSION)} [{b_info.get('short_hash', 'dev')}] • {b_info.get('build_time', '')}"
        self.footer_version_label = ctk.CTkLabel(
            self.footer_frame,
            text=b_str,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9ca3af"
        )
        self.footer_version_label.pack(side="right")

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

        # Card 2: Zero-Trust Security Wall Status
        c2 = ctk.CTkFrame(stats_frame, corner_radius=10, fg_color=("#374151", "#1f2937"))
        c2.grid(row=0, column=1, padx=6, sticky="nsew")
        ctk.CTkLabel(c2, text="ZERO-TRUST CLOUD WALL", font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399").pack(anchor="w", padx=15, pady=(12, 2))
        ctk.CTkLabel(c2, text="Upload & Telemetry Broker", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=15)
        ctk.CTkLabel(c2, text="DBK2 Encrypted (AES-256 + RSA)", font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(anchor="w", padx=15, pady=(2, 12))

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
            text="Runs an immediate full SQL backup, encrypts with DBK2 hybrid AES-256-GCM + RSA-4096, streams to Cloud Storage via Upload Broker, and logs telemetry.",
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

        # Dynamic master progress bar
        self.progress_bar = ctk.CTkProgressBar(action_card, width=520, height=14, corner_radius=7)
        self.progress_bar.pack(pady=(15, 6))
        self.progress_bar.set(0)

        # Status text label (Action / Phase title)
        self.status_text_label = ctk.CTkLabel(
            action_card,
            text="Ready to execute backup",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#60a5fa"
        )
        self.status_text_label.pack(pady=(0, 4))

        # Real-time Cloud Telemetry Pill Box (Upload Speed, ETA, Bytes Done / Total)
        self.telemetry_card = ctk.CTkFrame(action_card, fg_color=("#1e293b", "#0f172a"), corner_radius=8, border_width=1, border_color="#334155")
        self.telemetry_card.pack(fill="x", padx=40, pady=(2, 14))

        self.telemetry_label = ctk.CTkLabel(
            self.telemetry_card,
            text="⚡ Upload Speed: Idle   •   ⏳ ETA: --   •   ☁ Target: Zero-Trust Upload Broker",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#94a3b8"
        )
        self.telemetry_label.pack(padx=12, pady=6)

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

        # Button 2: Test Broker Connection
        ctk.CTkButton(
            links_frame,
            text="🔍 Test Broker",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=135,
            command=self._start_test_connection_thread
        ).pack(side="left", padx=5)

        # Button 3: Clean Local Storage Drive
        ctk.CTkButton(
            links_frame,
            text="🧹 Clean Storage",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            width=135,
            command=self._cleanup_storage
        ).pack(side="left", padx=5)

        # Button 4: Performance Maintenance Module
        ctk.CTkButton(
            links_frame,
            text="⚡ DB Maintenance",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e3a8a",
            hover_color="#1d4ed8",
            width=140,
            command=self._open_performance_tab
        ).pack(side="left", padx=5)

    def _open_performance_tab(self):
        """Switches directly to the Performance Query module tab."""
        self.tabview.set("  Performance Query  ")


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
                 "• Operates unattended before any user logs in, survives reboots, and is not disrupted by RDP logoffs.",
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
        ).pack(anchor="w", padx=15, pady=(12, 4))

        # 1. Recurrence Frequency Preset Buttons
        freq_row = ctk.CTkFrame(trigger_card, fg_color="transparent")
        freq_row.pack(fill="x", padx=15, pady=(4, 8))

        ctk.CTkLabel(freq_row, text="Frequency:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1").pack(side="left", padx=(0, 10))

        self.sched_preset_seg = ctk.CTkSegmentedButton(
            freq_row,
            values=["Weekly (Mondays)", "Daily (Every Day)", "Weekdays (Mon-Fri)", "Custom Days"],
            command=self._on_schedule_preset_changed,
            font=ctk.CTkFont(size=12)
        )
        self.sched_preset_seg.pack(side="left", fill="x", expand=True)

        # 2. Interactive Day Selection Pills / Checkboxes
        days_frame = ctk.CTkFrame(trigger_card, fg_color="#0f172a", corner_radius=6, border_width=1, border_color="#334155")
        days_frame.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(days_frame, text="Active Days:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(12, 10), pady=8)

        self.day_vars = {}
        self.day_checkboxes = {}
        days_info = [
            ("MON", "Mon"),
            ("TUE", "Tue"),
            ("WED", "Wed"),
            ("THU", "Thu"),
            ("FRI", "Fri"),
            ("SAT", "Sat"),
            ("SUN", "Sun"),
        ]

        for code, label in days_info:
            var = ctk.BooleanVar(value=(code == "MON"))
            self.day_vars[code] = var
            chk = ctk.CTkCheckBox(
                days_frame,
                text=label,
                variable=var,
                command=self._on_day_checkbox_clicked,
                font=ctk.CTkFont(size=12, weight="bold"),
                checkbox_width=20,
                checkbox_height=20,
                corner_radius=4,
                fg_color="#10b981",
                hover_color="#059669"
            )
            chk.pack(side="left", padx=(0, 10), pady=8)
            self.day_checkboxes[code] = chk

        # 3. Execution Time Row with Real-Time 12-Hour Helper & Quick Presets
        time_card = ctk.CTkFrame(trigger_card, fg_color="transparent")
        time_card.pack(fill="x", padx=15, pady=(0, 8))

        time_input_row = ctk.CTkFrame(time_card, fg_color="transparent")
        time_input_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(time_input_row, text="Execution Time (24h format):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 12))
        
        self.entry_sched_time = ctk.CTkEntry(time_input_row, width=100, font=ctk.CTkFont(size=13, weight="bold"))
        self.entry_sched_time.insert(0, self.config_data.get("SCHEDULE_TIME", "02:00"))
        self.entry_sched_time.pack(side="left")
        self.entry_sched_time.bind("<KeyRelease>", lambda e: self._update_schedule_summary())

        self.lbl_time_12h = ctk.CTkLabel(time_input_row, text="(2:00 AM)", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        self.lbl_time_12h.pack(side="left", padx=(10, 15))

        # Quick Time Preset Pills
        ctk.CTkLabel(time_input_row, text="Quick Presets:", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left", padx=(5, 6))
        
        for p_label, p_val in [("02:00 AM", "02:00"), ("06:00 AM", "06:00"), ("12:00 PM", "12:00"), ("06:00 PM", "18:00"), ("11:00 PM", "23:00")]:
            ctk.CTkButton(
                time_input_row,
                text=p_label,
                width=68,
                height=24,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#334155",
                hover_color="#475569",
                command=lambda v=p_val: self._set_quick_time(v)
            ).pack(side="left", padx=2)

        # 4. Schedule Live Plan Banner
        self.lbl_sched_summary = ctk.CTkLabel(
            trigger_card,
            text="📅 Plan: Every Monday at 02:00 AM",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#a7f3d0",
            fg_color="#064e3b",
            corner_radius=6,
            height=28
        )
        self.lbl_sched_summary.pack(fill="x", padx=15, pady=(0, 10))

        # 5. Startup Trigger
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

        # Test via Scheduled Task (Round 9 Requirement 7)
        self.btn_test_task = ctk.CTkButton(
            btn_row,
            text="▶ Test via Scheduled Task",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=42,
            width=210,
            command=self._test_via_scheduled_task
        )
        self.btn_test_task.pack(side="left", padx=10)

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
        auth_row.pack(fill="x", padx=20, pady=(0, 2))
        
        self._create_field_label(auth_row, "SQL Username (optional, leave blank for Windows Auth):", pack_padx=0)
        self.entry_sql_user = ctk.CTkEntry(auth_row, width=240)
        self.entry_sql_user.pack(side="left", padx=(0, 15))
        
        self.entry_sql_pass = ctk.CTkEntry(auth_row, width=240, placeholder_text="SQL Password", show="*")
        self.entry_sql_pass.pack(side="left")

        # Warning banner for 'sa' administrative account (Round 9 Requirement 7)
        self.lbl_sql_sa_warning = ctk.CTkLabel(
            scroll,
            text="",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#f59e0b",
            anchor="w"
        )
        self.lbl_sql_sa_warning.pack(anchor="w", padx=20, pady=(0, 8))
        self.entry_sql_user.bind("<KeyRelease>", self._check_sql_sa_warning)

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

        # Customer Cloud Integration (Google Drive & Master Sheet)
        cloud_box = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#1f2937", "#111827"), border_width=1, border_color="#374151")
        cloud_box.pack(fill="x", padx=20, pady=(10, 15))

        cloud_top = ctk.CTkFrame(cloud_box, fg_color="transparent")
        cloud_top.pack(fill="x", padx=15, pady=(12, 6))

        ctk.CTkLabel(
            cloud_top,
            text="CUSTOMER CLOUD INTEGRATION (GOOGLE DRIVE & SHEETS)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#34d399"
        ).pack(side="left")

        ctk.CTkLabel(
            cloud_box,
            text="Database backups stream encrypted (AES-256-GCM + RSA-4096) to Google Cloud Storage via the Upload Broker. Google Sheets receives live telemetry. (The Google Drive link is an optional browser shortcut for user files; backups do not upload to Drive).",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af",
            wraplength=600,
            justify="left"
        ).pack(anchor="w", padx=15, pady=(0, 8))

        # Google Drive Folder ID / Link (Optional Shortcut)
        self._create_field_label(cloud_box, "Customer Google Drive Folder (Optional Quick Link):", pack_padx=15)
        drive_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        drive_row.pack(fill="x", padx=15, pady=(0, 2))
        self.entry_google_drive = ctk.CTkEntry(drive_row, width=420, placeholder_text="Folder ID or https://drive.google.com/drive/folders/... (Optional)")
        self.entry_google_drive.pack(side="left", padx=(0, 10))
        ctk.CTkButton(drive_row, text="Open Folder ->", width=110, fg_color="#374151", hover_color="#4b5563", command=self._open_drive_folder).pack(side="left")

        self.lbl_drive_val_status = ctk.CTkLabel(cloud_box, text="", font=ctk.CTkFont(size=10, weight="bold"), anchor="w")
        self.lbl_drive_val_status.pack(anchor="w", padx=15, pady=(0, 6))
        self.entry_google_drive.bind("<KeyRelease>", self._validate_cloud_inputs)

        # Telemetry Service Account Email Banner (Requirement F)
        sa_card = ctk.CTkFrame(cloud_box, fg_color=("#1e293b", "#0f172a"), corner_radius=6, border_width=1, border_color="#334155")
        sa_card.pack(fill="x", padx=15, pady=(4, 8))
        ctk.CTkLabel(
            sa_card,
            text="📋 Share your Google Sheet with Editor permission to this Telemetry Service Account:\ntelemetry-broker@backupbot-506604.iam.gserviceaccount.com",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#93c5fd",
            justify="left",
            padx=10,
            pady=6
        ).pack(anchor="w")

        # Master Google Sheet ID / Link
        self._create_field_label(cloud_box, "Customer Master Google Sheet ID or Link:", pack_padx=15)
        sheet_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        sheet_row.pack(fill="x", padx=15, pady=(0, 2))
        self.entry_google_sheet = ctk.CTkEntry(sheet_row, width=320, placeholder_text="Spreadsheet ID or https://docs.google.com/spreadsheets/d/...")
        self.entry_google_sheet.pack(side="left", padx=(0, 8))
        ctk.CTkButton(sheet_row, text="Open Sheet ->", width=105, fg_color="#2563eb", hover_color="#1d4ed8", command=self._open_master_sheet).pack(side="left", padx=(0, 6))
        self.btn_test_sheet = ctk.CTkButton(sheet_row, text="🔍 Test Sheet", width=95, fg_color="#059669", hover_color="#047857", command=self._test_customer_sheet)
        self.btn_test_sheet.pack(side="left")

        self.lbl_sheet_val_status = ctk.CTkLabel(cloud_box, text="", font=ctk.CTkFont(size=10, weight="bold"), anchor="w")
        self.lbl_sheet_val_status.pack(anchor="w", padx=15, pady=(0, 8))
        self.entry_google_sheet.bind("<KeyRelease>", self._validate_cloud_inputs)

        # Active Module Tabs Display Badges (Round 9 Requirement 6: Badges must come from real test)
        tabs_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        tabs_row.pack(fill="x", padx=15, pady=(0, 12))
        self.sheet_tab_badges = {}
        for tag, title in DEFAULT_SHEET_TABS.items():
            badge = ctk.CTkLabel(
                tabs_row,
                text=f"Tab: {title} (Not tested)",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#9ca3af",
                fg_color="#374151",
                corner_radius=6,
                padx=8,
                pady=3
            )
            badge.pack(side="left", padx=(0, 8))
            self.sheet_tab_badges[tag] = badge

        # Security Wall & Upload Broker Configuration
        sec_box = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#1f2937", "#111827"), border_width=1, border_color="#374151")
        sec_box.pack(fill="x", padx=20, pady=(10, 15))

        sec_top = ctk.CTkFrame(sec_box, fg_color="transparent")
        sec_top.pack(fill="x", padx=15, pady=(12, 6))

        ctk.CTkLabel(
            sec_top,
            text="ZERO-TRUST CLOUD SECURITY WALL (BROKER & ENCRYPTION)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#60a5fa"
        ).pack(side="left")

        self._create_field_label(sec_box, "Apps Script Web App URL:", pack_padx=15)
        broker_row = ctk.CTkFrame(sec_box, fg_color="transparent")
        broker_row.pack(fill="x", padx=15, pady=(0, 10))
        self.entry_broker_url = ctk.CTkEntry(broker_row, width=370, placeholder_text="https://backup-broker-xxxx.run.app")
        self.entry_broker_url.pack(side="left", padx=(0, 10))
        self.btn_unlock_broker = ctk.CTkButton(
            broker_row,
            text="🔒 Locked",
            width=100,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self._toggle_unlock_broker
        )
        self.btn_unlock_broker.pack(side="left")

        # Status Badges for Token & Encryption Key
        status_row = ctk.CTkFrame(sec_box, fg_color="transparent")
        status_row.pack(fill="x", padx=15, pady=(0, 12))

        self.lbl_token_status = ctk.CTkLabel(
            status_row,
            text="🔑 Broker Token: Checking...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9ca3af",
            fg_color="#374151",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.lbl_token_status.pack(side="left", padx=(0, 8))

        self.btn_import_token = ctk.CTkButton(
            status_row,
            text="🔑 Import Token",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=110,
            height=26,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._open_import_token_dialog
        )
        self.btn_import_token.pack(side="left", padx=(0, 12))

        self.lbl_key_status = ctk.CTkLabel(
            status_row,
            text="🔒 Public Key: Checking...",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9ca3af",
            fg_color="#374151",
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.lbl_key_status.pack(side="left")


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
            text="🔍  Test Broker Connection",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=42,
            width=220,
            command=self._start_test_connection_thread
        )
        self.btn_test_conn.pack(side="left", padx=(0, 15))

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
            subprocess.Popen([uninstaller_path, BASE_DIR])
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

        # Pre-load recent log entries from the single unified backup_log.txt file
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    recent_lines = f.readlines()
                    for line in recent_lines[-250:]:
                        self.log_textbox.insert("end", line)
                    self.log_textbox.see("end")
            except Exception:
                pass

        # Initial startup message
        self.append_log(f"[SYSTEM] Ready. Single unified log file active: {LOG_FILE}")

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

    def _open_local_backup_folder(self):
        """Opens the local backup directory in Windows File Explorer."""
        folder = self.config_data.get("BACKUP_FOLDER", r"C:\temp\backups")
        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create backup directory:\n{e}")
                return
        try:
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open folder:\n{e}")

    def _cleanup_storage(self):
        """Manually triggers local backup storage folder cleanup."""
        folder = self.config_data.get("BACKUP_FOLDER", r"C:\temp\backups")
        if not os.path.exists(folder):
            messagebox.showinfo("Cleanup Storage", "Backup directory does not exist or is already clean.")
            return
        confirm = messagebox.askyesno("Confirm Cleanup", f"Are you sure you want to clean up local temporary backup files in:\n{folder}?")
        if not confirm:
            return
        cleaned, freed_bytes = cleanup_local_backup_folder(folder, log_cb=self.append_log)
        freed_str = format_file_size(freed_bytes)
        messagebox.showinfo("Storage Cleanup Complete", f"Successfully cleaned {cleaned} old files.\nFreed space: {freed_str}")

    def _open_log_file(self):
        """Opens the single unified log file in default text editor / notepad."""
        log_path = LOG_FILE
        if not os.path.exists(log_path):
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"--- Log File Initialized {datetime.datetime.now()} ---\n")
        try:
            os.startfile(log_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open log file:\n{e}")

    def _clear_logs(self):
        """Clears the live on-screen log textbox."""
        if hasattr(self, "log_textbox"):
            self.log_textbox.delete("1.0", "end")
            self.append_log("Log display cleared.")

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
        self._check_sql_sa_warning()

        dbs = c.get("TARGET_DATABASES", [])
        self.entry_databases.delete(0, "end")
        self.entry_databases.insert(0, ", ".join(dbs))

        self.entry_backup_folder.delete(0, "end")
        self.entry_backup_folder.insert(0, c.get("BACKUP_FOLDER", "C:\\temp\\backups"))

        self.entry_broker_url.delete(0, "end")
        self.entry_broker_url.delete(0, "end"); self.entry_broker_url.insert(0, c.get("BROKER_URL", "")); self.entry_broker_url.configure(state="disabled") if c.get("BROKER_URL") else None

        if hasattr(self, "entry_google_drive"):
            self.entry_google_drive.delete(0, "end")
            self.entry_google_drive.insert(0, c.get("GOOGLE_DRIVE_FOLDER_ID", ""))

        if hasattr(self, "entry_google_sheet"):
            self.entry_google_sheet.delete(0, "end")
            self.entry_google_sheet.insert(0, c.get("GOOGLE_SHEET_ID", ""))

        # Check Token and Key files using shared preflight module (Requirement C)
        from preflight import decrypt_token_dpapi, validate_public_keys
        token_str, t_res = decrypt_token_dpapi(data_dir=DATA_DIR, target_dir=BASE_DIR)
        if t_res.passed and token_str:
            pc_name = token_str.split(".")[0]
            self.lbl_token_status.configure(text=f"🔑 Token: Loaded ({pc_name}) - Not Verified", text_color="#9ca3af", fg_color="#374151")
        else:
            reason_map = {
                "ERR_TOKEN_FILE_ABSENT": "File Absent",
                "ERR_TOKEN_ACL_DENIED": "ACL Denied",
                "ERR_TOKEN_ZERO_BYTES": "Empty (0 bytes)",
                "ERR_TOKEN_FORMAT_INVALID": "Format Invalid",
            }
            if t_res.code.startswith("ERR_WIN32_"):
                reason = f"Decrypt Failed ({t_res.code.replace('ERR_WIN32_', '')})"
            else:
                reason = reason_map.get(t_res.code, t_res.code)
            self.lbl_token_status.configure(text=f"🔑 Token: {reason}", text_color="#f87171", fg_color="#7f1d1d")
            self.append_log(f"[PREFLIGHT] Token check: {t_res.message} (Code: {t_res.code})")

        k_res = validate_public_keys(data_dir=DATA_DIR, target_dir=BASE_DIR)
        if k_res.passed:
            self.lbl_key_status.configure(text="🔒 Public Keys: Valid (>=3072-bit)", text_color="#34d399", fg_color="#064e3b")
        else:
            key_reason_map = {
                "ERR_PRIMARY_KEY_ABSENT": "Primary Key Absent",
                "ERR_ESCROW_KEY_ABSENT": "Escrow Key Absent",
                "ERR_PRIMARY_KEY_TOO_SHORT": "Primary <3072b",
                "ERR_ESCROW_KEY_TOO_SHORT": "Escrow <3072b",
                "ERR_KEYS_NOT_DISTINCT": "Keys Identical!",
                "ERR_PRIMARY_KEY_CORRUPT": "Primary Corrupt",
                "ERR_ESCROW_KEY_CORRUPT": "Escrow Corrupt",
            }
            reason = key_reason_map.get(k_res.code, k_res.code)
            self.lbl_key_status.configure(text=f"🔒 Public Keys: {reason}", text_color="#f87171", fg_color="#7f1d1d")
            self.append_log(f"[PREFLIGHT] Public keys check: {k_res.message} (Code: {k_res.code})")

        if hasattr(self, "_validate_cloud_inputs"):
            self._validate_cloud_inputs()

        sched_days = c.get("SCHEDULE_DAYS")
        if not sched_days:
            if c.get("STRICTLY_MONDAYS_ONLY", True):
                sched_days = ["MON"]
            else:
                sched_days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

        if isinstance(sched_days, str):
            sched_days = [d.strip().upper() for d in sched_days.split(",") if d.strip()]
        else:
            sched_days = [str(d).strip().upper() for d in sched_days if str(d).strip()]

        for code in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]:
            if code in self.day_vars:
                self.day_vars[code].set(code in sched_days or "DAILY" in sched_days or "ALL" in sched_days)

        self._on_day_checkbox_clicked()

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

    def _open_drive_folder(self):
        """Opens customer Google Drive folder in default web browser."""
        val = self.entry_google_drive.get().strip() if hasattr(self, "entry_google_drive") else ""
        url = build_google_drive_url(val)
        if url:
            webbrowser.open(url)
        else:
            messagebox.showwarning("Notice", "No Customer Google Drive Folder ID or Link configured.")

    def _open_google_drive(self):
        self._open_drive_folder()

    def _open_master_sheet(self):
        """Opens customer Master Google Sheet in default web browser."""
        val = self.entry_google_sheet.get().strip() if hasattr(self, "entry_google_sheet") else ""
        url = build_google_sheet_url(val)
        if url:
            webbrowser.open(url)
        else:
            messagebox.showwarning("Notice", "No Customer Master Google Sheet ID or Link configured.")

    def _open_google_sheet(self):
        self._open_master_sheet()

    def _validate_cloud_inputs(self, event=None):
        """Live format validation for Customer Google Drive and Master Google Sheet."""
        if hasattr(self, "entry_google_drive") and hasattr(self, "lbl_drive_val_status"):
            raw_drive = self.entry_google_drive.get().strip()
            drive_id = extract_google_id(raw_drive)
            if not raw_drive:
                self.lbl_drive_val_status.configure(
                    text="● Required: Customer Google Drive folder for backup storage",
                    text_color="#9ca3af"
                )
            elif len(drive_id) >= 20:
                self.lbl_drive_val_status.configure(
                    text=f"✓ Valid Drive Folder ID: {drive_id[:16]}...",
                    text_color="#34d399"
                )
            else:
                self.lbl_drive_val_status.configure(
                    text="⚠️ Incomplete Drive ID (must be a valid Drive Folder ID or URL)",
                    text_color="#f59e0b"
                )

        if hasattr(self, "entry_google_sheet") and hasattr(self, "lbl_sheet_val_status"):
            raw_sheet = self.entry_google_sheet.get().strip()
            sheet_id = extract_google_id(raw_sheet)
            if not raw_sheet:
                self.lbl_sheet_val_status.configure(
                    text="● Required: Customer Master Google Sheet for 3-module monitoring",
                    text_color="#9ca3af"
                )
            elif len(sheet_id) >= 25:
                self.lbl_sheet_val_status.configure(
                    text=f"✓ Valid Sheet ID: {sheet_id[:16]}...",
                    text_color="#34d399"
                )
            else:
                self.lbl_sheet_val_status.configure(
                    text="⚠️ Incomplete Sheet ID (must be a valid Google Spreadsheet ID or URL)",
                    text_color="#f59e0b"
                )

    def _open_import_token_dialog(self):
        """Opens modal dialog to securely import and encrypt machine authentication token."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("Import Machine Broker Token")
        dlg.geometry("520, 290")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(
            dlg,
            text="Import PC Authentication Token",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w", padx=20, pady=(15, 4))

        ctk.CTkLabel(
            dlg,
            text="Paste your <pc_id>.<secret> token or select a raw_token.txt file provided by your administrator. It will be encrypted into machine-scoped Windows DPAPI storage.",
            font=ctk.CTkFont(size=11),
            text_color="#9ca3af",
            wraplength=480,
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 10))

        token_var = tk.StringVar()
        entry_tok = ctk.CTkEntry(
            dlg,
            textvariable=token_var,
            placeholder_text="e.g. pc-client-01.a9b8c7d6e5f4...",
            font=ctk.CTkFont(family="Consolas", size=11),
            height=34
        )
        entry_tok.pack(fill="x", padx=20, pady=(0, 10))

        def _browse_raw_token():
            chosen = filedialog.askopenfilename(
                title="Select raw_token.txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                parent=dlg
            )
            if chosen and os.path.exists(chosen):
                try:
                    with open(chosen, "r", encoding="utf-8") as rf:
                        t = rf.read().strip()
                        if t:
                            token_var.set(t)
                except Exception as ex:
                    messagebox.showerror("Error Reading File", str(ex), parent=dlg)

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkButton(
            btn_row,
            text="📁 Browse raw_token.txt...",
            font=ctk.CTkFont(size=11),
            fg_color="#374151",
            hover_color="#4b5563",
            command=_browse_raw_token
        ).pack(side="left")

        def _do_save():
            val = token_var.get().strip()
            if not val or "." not in val:
                messagebox.showerror("Invalid Token", "Please enter a valid token in the format '<pc_id>.<secret>'.", parent=dlg)
                return
            try:
                from broker_client import import_and_protect_token
                for dest_dir in [DATA_DIR, BASE_DIR]:
                    os.makedirs(dest_dir, exist_ok=True)
                    target_file = os.path.join(dest_dir, "token.dpapi")
                    import_and_protect_token(val, target_file)
                self.append_log("Authentication token successfully imported and DPAPI protected.", "info")
                self._load_config_values()
                messagebox.showinfo("Token Saved", "Token successfully encrypted with Windows DPAPI (LocalMachine)!\nPC is now registered and authenticated.", parent=dlg)
                dlg.destroy()
            except Exception as ex:
                messagebox.showerror("Import Error", f"Failed to save token: {ex}", parent=dlg)

        ctk.CTkButton(
            dlg,
            text="🔒  Encrypt & Save Token",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=38,
            command=_do_save
        ).pack(anchor="e", padx=20)

    def _toggle_unlock_broker(self):
        """Controls access to the Upload Broker URL to prevent accidental tampering."""
        if self.entry_broker_url.cget("state") == "disabled":
            if messagebox.askyesno(
                "Unlock Upload Broker URL",
                "The Upload Broker URL connects the application to your secure Google Apps Script microservice.\n\n"
                "Modifying this address may disrupt automated backups and cloud synchronization.\n\n"
                "Are you sure you want to unlock and edit this endpoint?"
            ):
                self.entry_broker_url.configure(state="normal")
                self.btn_unlock_broker.configure(text="🔓 Unlocked", fg_color="#059669")
        else:
            self.entry_broker_url.configure(state="disabled")
            self.btn_unlock_broker.configure(text="🔒 Locked", fg_color="#374151")

    def _browse_backup_folder(self):
        """Displays Windows folder picker for local backup directory."""
        folder = filedialog.askdirectory(initialdir=self.entry_backup_folder.get())
        if folder:
            norm_folder = os.path.normpath(folder)
            self.entry_backup_folder.delete(0, "end")
            self.entry_backup_folder.insert(0, norm_folder)
            grant_sql_folder_permissions(norm_folder)

    def _save_settings(self):
        """Validates and persists updated settings to config.json (Requirement E)."""
        dbs_str = self.entry_databases.get().strip()
        db_list = [d.strip() for d in dbs_str.split(",") if d.strip()]
        backup_dir = os.path.normpath(self.entry_backup_folder.get().strip())

        # Validate backup destination folder (Requirement E: strictly block OneDrive/Dropbox/Google Drive/etc.)
        from preflight import validate_backup_folder_path, validate_broker_url_security
        f_res = validate_backup_folder_path(backup_dir)
        if not f_res.passed:
            messagebox.showerror("Invalid Backup Destination", f_res.message)
            return

        b_url = self.entry_broker_url.get().strip()
        if b_url:
            u_res = validate_broker_url_security(b_url, allow_insecure=True)
            if not u_res.passed:
                messagebox.showerror("Invalid Broker URL", u_res.message)
                return

        if backup_dir:
            grant_sql_folder_permissions(backup_dir)
        selected_days = [d for d in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] if self.day_vars[d].get()]
        if not selected_days:
            selected_days = ["MON"]

        time_val = self.entry_sched_time.get().strip() or "02:00"

        new_config = dict(self.config_data)
        new_config.update({
            "SQL_SERVER_NAME": self.entry_sql_server.get().strip(),
            "SQL_USERNAME": self.entry_sql_user.get().strip(),
            "SQL_PASSWORD": self.entry_sql_pass.get().strip(),
            "BACKUP_FOLDER": backup_dir,
            "BACKUP_EXTENSION": ".zip",
            "TARGET_DATABASES": db_list,
            "BROKER_URL": b_url,
            "STRICTLY_MONDAYS_ONLY": (selected_days == ["MON"]),
            "SCHEDULE_DAYS": selected_days,
            "SCHEDULE_TIME": time_val,
            "DELETE_LOCAL_AFTER_UPLOAD": bool(self.chk_delete_local.get())
        })
        # Preserve customer Google Drive & Sheet IDs for multi-module integration
        drive_val = self.entry_google_drive.get().strip() if hasattr(self, "entry_google_drive") else ""
        sheet_val = self.entry_google_sheet.get().strip() if hasattr(self, "entry_google_sheet") else ""
        new_config["GOOGLE_DRIVE_FOLDER_ID"] = extract_google_id(drive_val) if drive_val else ""
        new_config["GOOGLE_SHEET_ID"] = extract_google_id(sheet_val) if sheet_val else ""
        new_config["SHEET_TABS"] = DEFAULT_SHEET_TABS

        ok, msg = save_config(new_config)
        if ok:
            self.config_data = new_config
            self.card_sql_label.configure(text=new_config.get("SQL_SERVER_NAME", "localhost"))
            self.card_dbs_label.configure(text=f"{len(db_list)} Databases Configured")
            self._load_config_into_ui()
            messagebox.showinfo("Saved", "Configuration saved successfully!")
        else:
            messagebox.showerror("Error", f"Failed to save configuration:\n{msg}")

    def _test_customer_sheet(self):
        """Tests Google Sheets connectivity and binds PC ID to Sheet via Broker (Requirement F)."""
        sheet_val = self.entry_google_sheet.get().strip() if hasattr(self, "entry_google_sheet") else ""
        sheet_id = extract_google_id(sheet_val)
        if not sheet_id:
            messagebox.showwarning("Sheet ID Required", "Please enter a valid Google Spreadsheet ID or URL first.")
            return

        broker_url = self.entry_broker_url.get().strip() or self.config_data.get("BROKER_URL", "").strip()
        if not broker_url:
            messagebox.showwarning("Broker URL Required", "Please configure the Upload/Telemetry Broker URL first.")
            return

        from preflight import decrypt_token_dpapi
        tok_str, tok_res = decrypt_token_dpapi(data_dir=DATA_DIR, target_dir=BASE_DIR)
        if not tok_res.passed or not tok_str:
            messagebox.showerror("Token Missing", f"Cannot authenticate with broker: {tok_res.message}")
            return

        self.btn_test_sheet.configure(state="disabled", text="Testing...")
        self.append_log(f"[SHEET] Testing Google Sheet '{sheet_id[:16]}...' via broker...")

        def _worker():
            try:
                import requests
                endpoint = broker_url.rstrip("/") + "/bind-sheet"
                headers = {
                    "Authorization": f"Bearer {tok_str}",
                    "Content-Type": "application/json"
                }
                resp = requests.post(endpoint, json={"sheet_id": sheet_id}, headers=headers, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    title = data.get("title", "Master Telemetry Sheet")
                    self.append_log(f"[SHEET] Success: Bound to sheet '{title}' (HTTP 200)")
                    def _update_success_badges():
                        for tag, badge in getattr(self, "sheet_tab_badges", {}).items():
                            title = DEFAULT_SHEET_TABS.get(tag, tag)
                            badge.configure(text=f"✓ Tab: {title} (Verified)", text_color="#6ee7b7", fg_color="#064e3b")
                    self.after(0, _update_success_badges)
                    self.after(0, lambda: messagebox.showinfo(
                        "Sheet Verified & Bound",
                        f"SUCCESS!\n\nPC ID is now permanently bound to Google Sheet:\n'{title}'\n\nLive storage telemetry will be appended automatically."
                    ))
                elif resp.status_code == 403:
                    err_msg = resp.json().get("error", "Access denied")
                    self.append_log(f"[SHEET] Permission error: {err_msg}", "error")
                    def _update_fail_badges():
                        for tag, badge in getattr(self, "sheet_tab_badges", {}).items():
                            title = DEFAULT_SHEET_TABS.get(tag, tag)
                            badge.configure(text=f"⚠️ Tab: {title} (Unverified)", text_color="#fca5a5", fg_color="#7f1d1d")
                    self.after(0, _update_fail_badges)
                    self.after(0, lambda: messagebox.showerror(
                        "Permission Denied (HTTP 403)",
                        f"The Telemetry Service Account cannot access this spreadsheet.\n\n"
                        f"Please open your Google Sheet, click 'Share', and grant 'Editor' access to:\n"
                        f"telemetry-broker@backupbot-506604.iam.gserviceaccount.com\n\nDetail: {err_msg}"
                    ))
                else:
                    err_msg = resp.json().get("error", f"HTTP {resp.status_code}")
                    self.append_log(f"[SHEET] Broker error: {err_msg}", "error")
                    def _update_fail_badges():
                        for tag, badge in getattr(self, "sheet_tab_badges", {}).items():
                            title = DEFAULT_SHEET_TABS.get(tag, tag)
                            badge.configure(text=f"⚠️ Tab: {title} (Unverified)", text_color="#fca5a5", fg_color="#7f1d1d")
                    self.after(0, _update_fail_badges)
                    self.after(0, lambda: messagebox.showerror("Sheet Verification Failed", err_msg))
            except Exception as ex:
                self.append_log(f"[SHEET] Network error: {ex}", "error")
                self.after(0, lambda ex=ex: messagebox.showerror("Connection Error", str(ex)))
            finally:
                self.after(0, lambda: self.btn_test_sheet.configure(state="normal", text="🔍 Test Sheet"))

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # SCHEDULE & AUTOMATION CONTROLLERS
    # =========================================================================
    def _set_quick_time(self, time_val):
        """Sets the time entry from a quick preset button."""
        self.entry_sched_time.delete(0, "end")
        self.entry_sched_time.insert(0, time_val)
        self._update_schedule_summary()

    def _on_schedule_preset_changed(self, value):
        """Updates day checkboxes based on frequency preset button."""
        if value == "Weekly (Mondays)":
            for code in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]:
                self.day_vars[code].set(code == "MON")
        elif value == "Daily (Every Day)":
            for code in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]:
                self.day_vars[code].set(True)
        elif value == "Weekdays (Mon-Fri)":
            for code in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]:
                self.day_vars[code].set(code in ["MON", "TUE", "WED", "THU", "FRI"])
        self._update_schedule_summary()

    def _on_day_checkbox_clicked(self):
        """Evaluates active day checkboxes and synchronizes the preset segmented button."""
        active = [code for code in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] if self.day_vars[code].get()]
        if len(active) == 7:
            self.sched_preset_seg.set("Daily (Every Day)")
        elif active == ["MON", "TUE", "WED", "THU", "FRI"]:
            self.sched_preset_seg.set("Weekdays (Mon-Fri)")
        elif active == ["MON"]:
            self.sched_preset_seg.set("Weekly (Mondays)")
        else:
            self.sched_preset_seg.set("Custom Days")
        self._update_schedule_summary()

    def _update_schedule_summary(self):
        """Updates live 12-hour format badge and schedule summary description."""
        time_str = self.entry_sched_time.get().strip() or "02:00"
        time_12h = time_str
        
        # Parse 24h into 12h
        m = re.match(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$", time_str)
        if m:
            hh = int(m.group(1))
            mm = m.group(2)
            suffix = "AM" if hh < 12 else "PM"
            hh12 = hh if (1 <= hh <= 12) else (hh - 12 if hh > 12 else 12)
            time_12h = f"{hh12}:{mm} {suffix}"
            self.lbl_time_12h.configure(text=f"({time_12h})", text_color="#38bdf8")
        else:
            self.lbl_time_12h.configure(text="(Invalid 24h Time)", text_color="#ef4444")

        active = [code for code in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] if self.day_vars[code].get()]
        day_names_map = {
            "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
            "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"
        }
        
        if len(active) == 7:
            desc = f"📅 Plan: Every Day at {time_12h} (24h: {time_str})"
            bg_col = "#064e3b"
            txt_col = "#a7f3d0"
        elif active == ["MON", "TUE", "WED", "THU", "FRI"]:
            desc = f"📅 Plan: Weekdays (Mon through Fri) at {time_12h} (24h: {time_str})"
            bg_col = "#064e3b"
            txt_col = "#a7f3d0"
        elif len(active) > 0:
            names = [day_names_map[d] for d in active]
            desc = f"📅 Plan: Every {', '.join(names)} at {time_12h} (24h: {time_str})"
            bg_col = "#064e3b"
            txt_col = "#a7f3d0"
        else:
            desc = "⚠️ Plan: No days selected - Please select at least one day!"
            bg_col = "#7f1d1d"
            txt_col = "#fca5a5"

        self.lbl_sched_summary.configure(text=desc, fg_color=bg_col, text_color=txt_col)

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
        selected_days = [d for d in ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] if self.day_vars[d].get()]
        if not selected_days:
            messagebox.showwarning("Day Required", "Please select at least one day of the week to run the automated backup.")
            return

        time_str = self.entry_sched_time.get().strip() or "02:00"
        if not re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$", time_str):
            messagebox.showwarning("Invalid Time Format", "Please enter a valid 24-hour time format (e.g. 02:00, 14:30, 23:00).")
            return

        as_system = (self.sched_mode_var.get() == "SYSTEM")
        on_boot = bool(self.chk_boot_trigger.get())
        
        # Save to configuration
        self.config_data["SCHEDULE_DAYS"] = selected_days
        self.config_data["SCHEDULE_TIME"] = time_str
        self.config_data["STRICTLY_MONDAYS_ONLY"] = (selected_days == ["MON"])
        save_config(self.config_data)

        mode_label = "Unattended System Service (Session 0)" if as_system else "Standard User Task"
        self.append_log(f"Configuring Windows automation ({mode_label}) for days {', '.join(selected_days)} at {time_str}...")
        
        ok, msg = enable_scheduler(days=selected_days, time_str=time_str, as_system_service=as_system, on_boot=on_boot)
        if ok:
            messagebox.showinfo("Automation Configured", f"{msg}\n\nMode: {mode_label}\nConfiguration saved to config.json.")
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

    def _check_sql_sa_warning(self, event=None):
        """Displays warning if 'sa' account is specified for SQL Server (Round 9 Requirement 7)."""
        user = ""
        if hasattr(self, "entry_sql_user"):
            user = self.entry_sql_user.get().strip().lower()
        if user == "sa":
            self.lbl_sql_sa_warning.configure(
                text="⚠️ WARNING: Using 'sa' is strongly discouraged. Recommend Windows Authentication (leave username blank) or a dedicated login with db_backupoperator."
            )
        else:
            self.lbl_sql_sa_warning.configure(text="")

    def _test_via_scheduled_task(self):
        """Runs the scheduled task once as its real registered Windows account and reports result (Round 9 Requirement 7)."""
        active, status_desc, mode = get_scheduler_status()
        if not active:
            messagebox.showwarning(
                "Task Not Registered",
                f"The scheduled task '{DEFAULT_TASK_NAME}' is not registered in Windows Task Scheduler.\n\n"
                "Please configure and enable automation first using the buttons above."
            )
            return

        def _worker():
            self.append_log(f"\n[SCHEDULER] Triggering scheduled task '{DEFAULT_TASK_NAME}' as its registered account...")
            import subprocess
            import time

            # 1. Query registered task details to determine Run As User
            run_as_user = "Unknown"
            try:
                detail = subprocess.run(
                    ["schtasks.exe", "/query", "/tn", DEFAULT_TASK_NAME, "/fo", "LIST", "/v"],
                    capture_output=True, text=True, timeout=10
                )
                for line in detail.stdout.splitlines():
                    if line.strip().startswith("Run As User:"):
                        run_as_user = line.split(":", 1)[1].strip()
                        break
            except Exception as ex:
                self.append_log(f"[SCHEDULER] Could not query task details: {ex}", "warning")

            self.append_log(f"[SCHEDULER] Executing task under account: '{run_as_user}'")

            # 2. Trigger task run
            try:
                run_res = subprocess.run(
                    ["schtasks.exe", "/run", "/tn", DEFAULT_TASK_NAME],
                    capture_output=True, text=True, timeout=10
                )
                if run_res.returncode != 0:
                    err = (run_res.stderr or run_res.stdout).strip()
                    self.append_log(f"[SCHEDULER] Failed to trigger task: {err}", "error")
                    self.after(0, lambda: messagebox.showerror(
                        "Task Run Failed",
                        f"Failed to trigger '{DEFAULT_TASK_NAME}':\n{err}"
                    ))
                    return

                self.append_log(f"[SCHEDULER] Task '{DEFAULT_TASK_NAME}' triggered successfully. Waiting for execution result...")
            except Exception as ex:
                self.append_log(f"[SCHEDULER] Execution error: {ex}", "error")
                self.after(0, lambda ex=ex: messagebox.showerror("Execution Error", str(ex)))
                return

            # 3. Poll for completion (up to 15 seconds)
            completed = False
            last_result_code = "Unknown"
            for _ in range(15):
                time.sleep(1)
                try:
                    query_res = subprocess.run(
                        ["schtasks.exe", "/query", "/tn", DEFAULT_TASK_NAME, "/fo", "LIST", "/v"],
                        capture_output=True, text=True, timeout=5
                    )
                    status = ""
                    for line in query_res.stdout.splitlines():
                        if line.strip().startswith("Status:"):
                            status = line.split(":", 1)[1].strip().lower()
                        elif line.strip().startswith("Last Result:"):
                            last_result_code = line.split(":", 1)[1].strip()

                    if status != "running":
                        completed = True
                        break
                except Exception:
                    pass

            if completed:
                if last_result_code in ("0", "0x0"):
                    msg = (
                        f"Scheduled Task Test SUCCESS!\n\n"
                        f"Task: {DEFAULT_TASK_NAME}\n"
                        f"Account: {run_as_user}\n"
                        f"Exit Code: 0 (Success)\n\n"
                        f"The backup executed successfully under its registered account."
                    )
                    self.append_log(f"[SCHEDULER] Task completed successfully with exit code 0 under account '{run_as_user}'.", "info")
                    self.after(0, lambda: messagebox.showinfo("Scheduled Task Succeeded", msg))
                else:
                    msg = (
                        f"Scheduled Task Completed with Result: {last_result_code}\n\n"
                        f"Task: {DEFAULT_TASK_NAME}\n"
                        f"Account: {run_as_user}\n\n"
                        f"Please check application logs for details."
                    )
                    self.append_log(f"[SCHEDULER] Task completed with code: {last_result_code}", "warning")
                    self.after(0, lambda: messagebox.showwarning("Scheduled Task Completed", msg))
            else:
                msg = (
                    f"Scheduled Task is still running.\n\n"
                    f"Task: {DEFAULT_TASK_NAME}\n"
                    f"Account: {run_as_user}\n\n"
                    f"Check Live Logs or Windows Event Viewer for execution progress."
                )
                self.append_log(f"[SCHEDULER] Task is still executing in background.", "info")
                self.after(0, lambda: messagebox.showinfo("Task Running", msg))

        threading.Thread(target=_worker, daemon=True).start()


    # =========================================================================
    # ASYNCHRONOUS THREADING: TEST BROKER CONNECTION
    # =========================================================================
    def _start_test_connection_thread(self):
        """Spawns non-blocking daemon thread to test Upload Broker connection and preflights."""
        if self.is_running:
            return

        # Dynamically read current UI form values so test preflights validates what is typed
        test_cfg = dict(self.config_data)
        try:
            if hasattr(self, 'entry_sql_server') and self.entry_sql_server.get().strip():
                test_cfg["SQL_SERVER_NAME"] = self.entry_sql_server.get().strip()
            if hasattr(self, 'entry_sql_user'):
                test_cfg["SQL_USERNAME"] = self.entry_sql_user.get().strip()
            if hasattr(self, 'entry_sql_pass'):
                test_cfg["SQL_PASSWORD"] = self.entry_sql_pass.get().strip()
            if hasattr(self, 'entry_databases') and self.entry_databases.get().strip():
                dbs_str = self.entry_databases.get().strip()
                test_cfg["TARGET_DATABASES"] = [d.strip() for d in dbs_str.split(",") if d.strip()]
            if hasattr(self, 'entry_backup_folder') and self.entry_backup_folder.get().strip():
                test_cfg["BACKUP_FOLDER"] = self.entry_backup_folder.get().strip()
            if hasattr(self, 'entry_broker_url') and self.entry_broker_url.get().strip():
                test_cfg["BROKER_URL"] = self.entry_broker_url.get().strip()
            if hasattr(self, 'entry_google_drive') and self.entry_google_drive.get().strip():
                test_cfg["GOOGLE_DRIVE_FOLDER_ID"] = extract_google_id(self.entry_google_drive.get().strip())
            if hasattr(self, 'entry_google_sheet') and self.entry_google_sheet.get().strip():
                test_cfg["GOOGLE_SHEET_ID"] = extract_google_id(self.entry_google_sheet.get().strip())
        except Exception:
            pass

        self.btn_test_conn.configure(state="disabled", text="Testing...")
        self.append_log("\n--- Testing Zero-Trust System Preflights ---")
        threading.Thread(target=self._run_test_connection, args=(test_cfg,), daemon=True).start()

    def _run_test_connection(self, test_cfg=None):
        """Background worker executing unified preflight validation suite (Requirement B)."""
        try:
            from preflight import run_preflight_suite
            self.append_log("[PREFLIGHT] Running unified preflight validation suite...")
            cfg_to_test = test_cfg if test_cfg is not None else self.config_data
            report = run_preflight_suite(cfg_to_test, target_dir=BASE_DIR, data_dir=DATA_DIR, mode="test_button")
            for res in report.results:
                status_icon = "✓" if res.passed else "⚠️"
                level = "info" if res.passed else "error"
                self.append_log(f"[PREFLIGHT] {status_icon} {res.name}: {res.message} (Code: {res.code})", level)

            if report.passed:
                self.after(0, lambda: self.header_badge.configure(
                    text="● SYSTEM READY",
                    text_color="#10b981",
                    fg_color="#064e3b"
                ))
                token_passed = any(r.name == "Broker Token Authentication" and r.passed for r in report.results)
                if token_passed and hasattr(self, "lbl_token_status"):
                    self.after(0, lambda: self.lbl_token_status.configure(
                        text="🔑 Token: Active (Verified)",
                        text_color="#34d399",
                        fg_color="#064e3b"
                    ))
                msg = f"SUCCESS! All system preflights passed:\n\n{report.summary()}"
                self.after(0, lambda: messagebox.showinfo("Preflight Verification Passed", msg))
            else:
                self.after(0, lambda: self.header_badge.configure(
                    text="● PREFLIGHT FAILED",
                    text_color="#fca5a5",
                    fg_color="#7f1d1d"
                ))
                token_res = [r for r in report.results if r.name == "Broker Token Authentication"]
                if token_res and not token_res[0].passed and hasattr(self, "lbl_token_status"):
                    self.after(0, lambda: self.lbl_token_status.configure(
                        text=f"🔑 Token: Unverified ({token_res[0].code})",
                        text_color="#fca5a5",
                        fg_color="#7f1d1d"
                    ))
                fail_summary = "\n".join([f"• {f.name} ({f.code}): {f.message}" for f in report.failures])
                msg = f"Preflight Verification Failed ({len(report.failures)} issues):\n\n{fail_summary}"
                self.after(0, lambda: messagebox.showerror("Preflight Verification Failed", msg))
        except Exception as e:
            self.append_log(f"Preflight error: {e}", "error")
            self.after(0, lambda: self.header_badge.configure(
                text="● SYSTEM ERROR",
                text_color="#fca5a5",
                fg_color="#7f1d1d"
            ))
            self.after(0, lambda e=e: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, lambda: self.btn_test_conn.configure(state="normal", text="🔍  Test Preflights"))

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
        self.telemetry_label.configure(text="⚡ Initializing connection...   •   ⏳ Preparing Google Drive stream", text_color="#fbbf24")
        
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
            self.telemetry_label.configure(text="⚡ Halting network streams...   •   Emergency Stop", text_color="#f87171")
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

        def update_telemetry(t):
            def _apply():
                speed = t.get("speed_str", "--")
                eta = t.get("eta_str", "--")
                uploaded = format_file_size(t.get("bytes_done", 0))
                total = format_file_size(t.get("total_bytes", 0))
                pct = t.get("percent", 0.0)
                self.telemetry_label.configure(
                    text=f"⚡ Upload Speed: {speed}   •   ⏳ ETA: {eta}   •   📦 {uploaded} / {total} ({pct:.1f}%)",
                    text_color="#38bdf8"
                )
            self.after(0, _apply)

        try:
            success, summary = run_full_backup(
                config=self.config_data,
                log_cb=self.append_log,
                progress_cb=update_progress,
                status_cb=update_status,
                telemetry_cb=update_telemetry
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
                self.after(0, lambda e=e: messagebox.showerror("Fatal Error", f"Workflow failed:\n{e}"))
        finally:
            def _reset_ui():
                self.is_running = False
                self.btn_run_backup.configure(state="normal", text="⚡  RUN FULL BACKUP NOW")
                self.btn_stop_backup.configure(state="disabled", text="⏹  STOP BACKUP")
                self.btn_header_stop.pack_forget()
                if self.was_cancelled or is_backup_cancelled():
                    self.header_badge.configure(text="● STOPPED", text_color="#ef4444", fg_color="#450a0a")
                    self.status_text_label.configure(text="Backup stopped by user")
                    self.telemetry_label.configure(text="⚡ Upload Speed: Stopped   •   ⏳ ETA: --   •   ☁ Google Drive", text_color="#f87171")
                    self.progress_bar.set(0)
                else:
                    self.header_badge.configure(text="● SYSTEM READY", text_color="#10b981", fg_color="#064e3b")
                    self.status_text_label.configure(text="Ready to execute backup")
                    self.telemetry_label.configure(text="⚡ Upload Speed: Idle   •   ⏳ ETA: --   •   ☁ Target: Google Drive", text_color="#94a3b8")
                self.was_cancelled = False
            self.after(0, _reset_ui)

    # =========================================================================
    # TAB 5: SERVER HEALTH — STORAGE MONITORING & EMAIL ALERTS
    # =========================================================================
    def _build_server_health_tab(self):
        """Builds the Server Health tab with drive status cards, scan controls, and alert configuration."""
        tab = self.tab_server_health

        scroll = ctk.CTkScrollableFrame(tab, corner_radius=10, fg_color=("#374151", "#1f2937"))
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Section Header ─────────────────────────────────────────────
        ctk.CTkLabel(
            scroll,
            text="Server Storage Monitor & Clean Up",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            scroll,
            text="Scans all storage drives, logs capacity to Google Sheets, and sends High Importance email alerts when drives are almost full.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=20, pady=(0, 15))

        # ── Drive Status Cards Container ───────────────────────────────
        self.sh_drives_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.sh_drives_frame.pack(fill="x", padx=20, pady=(0, 10))

        # Placeholder label before first scan
        self.sh_placeholder_label = ctk.CTkLabel(
            self.sh_drives_frame,
            text="Click \"🔍 Scan Now\" to detect and display all storage drives.",
            font=ctk.CTkFont(size=13),
            text_color="#6b7280"
        )
        self.sh_placeholder_label.pack(pady=20)

        # ── Scan Status Bar ────────────────────────────────────────────
        self.sh_status_bar = ctk.CTkFrame(scroll, fg_color=("#1e293b", "#0f172a"), corner_radius=8)
        self.sh_status_bar.pack(fill="x", padx=20, pady=(0, 15))

        self.sh_scan_status = ctk.CTkLabel(
            self.sh_status_bar,
            text="Status: Waiting for scan...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9ca3af"
        )
        self.sh_scan_status.pack(side="left", padx=15, pady=10)

        self.sh_last_scan = ctk.CTkLabel(
            self.sh_status_bar,
            text="Last Scan: Never",
            font=ctk.CTkFont(size=11),
            text_color="#6b7280"
        )
        self.sh_last_scan.pack(side="right", padx=15, pady=10)

        # ── Action Buttons ─────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))

        self.btn_scan_now = ctk.CTkButton(
            btn_frame,
            text="🔍  Scan Now",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=40,
            width=160,
            corner_radius=20,
            command=self._start_storage_scan_thread
        )
        self.btn_scan_now.pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="📊  Open Storage Sheet",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            height=38,
            width=175,
            command=self._open_storage_sheet
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="📧  Test Email",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            height=38,
            width=130,
            command=self._test_storage_email
        ).pack(side="left", padx=5)

        # ── Alert Threshold Settings Card ──────────────────────────────
        threshold_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        threshold_card.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            threshold_card,
            text="ALERT THRESHOLD SETTINGS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#60a5fa"
        ).pack(anchor="w", padx=15, pady=(12, 10))

        # Row 1: C: Drive threshold (GB)
        c_row = ctk.CTkFrame(threshold_card, fg_color="transparent")
        c_row.pack(fill="x", padx=15, pady=(0, 8))

        ctk.CTkLabel(
            c_row,
            text="C: Drive (System) — Alert when free space falls below:",
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db"
        ).pack(side="left")

        self.sh_c_drive_entry = ctk.CTkEntry(c_row, width=60, justify="center")
        self.sh_c_drive_entry.pack(side="left", padx=(10, 5))
        self.sh_c_drive_entry.insert(0, str(self.config_data.get("STORAGE_C_DRIVE_ALERT_GB", 30)))

        ctk.CTkLabel(c_row, text="GB", font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(side="left")

        # Row 2: Other drives threshold (%)
        o_row = ctk.CTkFrame(threshold_card, fg_color="transparent")
        o_row.pack(fill="x", padx=15, pady=(0, 8))

        ctk.CTkLabel(
            o_row,
            text="Other Drives — Alert when usage exceeds:",
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db"
        ).pack(side="left")

        self.sh_other_pct_entry = ctk.CTkEntry(o_row, width=60, justify="center")
        self.sh_other_pct_entry.pack(side="left", padx=(10, 5))
        self.sh_other_pct_entry.insert(0, str(self.config_data.get("STORAGE_OTHER_DRIVES_ALERT_PERCENT", 90)))

        ctk.CTkLabel(o_row, text="%", font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(side="left")

        # Row 3: Include network drives toggle
        net_row = ctk.CTkFrame(threshold_card, fg_color="transparent")
        net_row.pack(fill="x", padx=15, pady=(0, 12))

        self.sh_include_network = ctk.CTkSwitch(
            net_row,
            text="Include Network / Shared Drives",
            font=ctk.CTkFont(size=12)
        )
        self.sh_include_network.pack(side="left")
        if self.config_data.get("STORAGE_INCLUDE_NETWORK_DRIVES", True):
            self.sh_include_network.select()

        # ── Scan Frequency Card ────────────────────────────────────────
        freq_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        freq_card.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            freq_card,
            text="SCAN FREQUENCY",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#60a5fa"
        ).pack(anchor="w", padx=15, pady=(12, 8))

        freq_row = ctk.CTkFrame(freq_card, fg_color="transparent")
        freq_row.pack(fill="x", padx=15, pady=(0, 12))

        ctk.CTkLabel(
            freq_row,
            text="Run storage scan:",
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db"
        ).pack(side="left")

        self.sh_freq_var = ctk.CTkOptionMenu(
            freq_row,
            values=["Daily", "Weekly", "Monthly"],
            width=120,
            fg_color="#374151",
            button_color="#4b5563",
            button_hover_color="#6b7280"
        )
        self.sh_freq_var.pack(side="left", padx=(10, 0))
        self.sh_freq_var.set(self.config_data.get("STORAGE_SCAN_FREQUENCY", "Daily"))

        # ── Email Settings Card ────────────────────────────────────────
        email_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        email_card.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            email_card,
            text="EMAIL ALERT CONFIGURATION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#60a5fa"
        ).pack(anchor="w", padx=15, pady=(12, 10))

        # Recipient
        self._sh_email_row(email_card, "Recipient Email:", "sh_recipient",
                          self.config_data.get("STORAGE_ALERT_EMAIL_RECIPIENT", "support@spillabs.com"))
        # Sender
        self._sh_email_row(email_card, "Sender Email:", "sh_sender",
                          self.config_data.get("STORAGE_ALERT_SENDER_EMAIL", ""))
        # Password
        self._sh_email_row(email_card, "Sender Password:", "sh_password",
                          self.config_data.get("STORAGE_ALERT_SENDER_PASSWORD", ""), show="●")
        # SMTP Server
        self._sh_email_row(email_card, "SMTP Server:", "sh_smtp",
                          self.config_data.get("STORAGE_ALERT_SMTP_SERVER", "smtp-mail.outlook.com"))
        # SMTP Port
        self._sh_email_row(email_card, "SMTP Port:", "sh_smtp_port",
                          str(self.config_data.get("STORAGE_ALERT_SMTP_PORT", 587)), width=80)

        # Spacer at bottom
        ctk.CTkFrame(email_card, fg_color="transparent", height=10).pack()

        # ── Save Settings Button ───────────────────────────────────────
        ctk.CTkButton(
            scroll,
            text="💾  Save Storage Monitor Settings",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=42,
            width=280,
            corner_radius=21,
            command=self._save_storage_settings
        ).pack(pady=(5, 20))

    def _sh_email_row(self, parent, label_text, attr_name, default_val, show=None, width=280):
        """Helper to create a labeled entry row for the email settings card."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=(0, 8))

        ctk.CTkLabel(
            row, text=label_text,
            font=ctk.CTkFont(size=12), text_color="#d1d5db",
            width=130, anchor="w"
        ).pack(side="left")

        entry = ctk.CTkEntry(row, width=width)
        if show:
            entry.configure(show=show)
        entry.pack(side="left", padx=(5, 0))
        entry.insert(0, default_val)
        setattr(self, attr_name, entry)

    def _save_storage_settings(self):
        """Saves all Server Health tab settings to config.json."""
        try:
            c_gb = int(self.sh_c_drive_entry.get().strip())
        except ValueError:
            c_gb = 30
        try:
            o_pct = int(self.sh_other_pct_entry.get().strip())
        except ValueError:
            o_pct = 90
        try:
            smtp_port = int(self.sh_smtp_port.get().strip())
        except ValueError:
            smtp_port = 587

        self.config_data["STORAGE_MONITOR_ENABLED"] = True
        self.config_data["STORAGE_C_DRIVE_ALERT_GB"] = max(1, min(c_gb, 500))
        self.config_data["STORAGE_OTHER_DRIVES_ALERT_PERCENT"] = max(50, min(o_pct, 99))
        self.config_data["STORAGE_INCLUDE_NETWORK_DRIVES"] = bool(self.sh_include_network.get())
        self.config_data["STORAGE_ALERT_EMAIL_RECIPIENT"] = self.sh_recipient.get().strip()
        self.config_data["STORAGE_ALERT_SENDER_EMAIL"] = self.sh_sender.get().strip()
        self.config_data["STORAGE_ALERT_SENDER_PASSWORD"] = self.sh_password.get().strip()
        self.config_data["STORAGE_ALERT_SMTP_SERVER"] = self.sh_smtp.get().strip()
        self.config_data["STORAGE_ALERT_SMTP_PORT"] = smtp_port
        self.config_data["STORAGE_SCAN_FREQUENCY"] = self.sh_freq_var.get()

        ok, msg = save_config(self.config_data)
        if ok:
            messagebox.showinfo("Saved", "Storage monitor settings saved successfully.")
        else:
            messagebox.showerror("Error", f"Failed to save settings:\n{msg}")

    def _start_storage_scan_thread(self):
        """Launches the storage scan in a background thread to keep the UI fluid."""
        self.btn_scan_now.configure(state="disabled", text="Scanning...")
        self.sh_scan_status.configure(text="Status: Scanning drives...", text_color="#fbbf24")
        threading.Thread(target=self._execute_storage_scan, daemon=True).start()

    def _execute_storage_scan(self):
        """Background worker for the storage monitoring scan cycle."""
        from datetime import datetime as dt

        def status_update(text):
            self.after(0, lambda: self.sh_scan_status.configure(text=f"Status: {text}", text_color="#fbbf24"))

        try:
            # Save any threshold changes before scanning
            self.after(0, self._save_storage_settings)

            success, summary, drives, critical = run_storage_monitor(
                config=self.config_data,
                log_cb=self.append_log,
                status_cb=status_update
            )

            # Update UI with scan results on the main thread
            def _update_ui():
                # Update status bar
                now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")
                self.sh_last_scan.configure(text=f"Last Scan: {now_str}")

                if critical:
                    self.sh_scan_status.configure(
                        text=f"Status: ⚠️ {len(critical)} drive(s) critical!",
                        text_color="#f87171"
                    )
                else:
                    self.sh_scan_status.configure(
                        text="Status: ✅ All drives healthy",
                        text_color="#10b981"
                    )

                # Rebuild drive cards
                self._rebuild_drive_cards(drives, critical)

                # Re-enable scan button
                self.btn_scan_now.configure(state="normal", text="🔍  Scan Now")

            self.after(0, _update_ui)

        except Exception as e:
            def _err(e=e):
                self.sh_scan_status.configure(text=f"Status: Error — {e}", text_color="#f87171")
                self.btn_scan_now.configure(state="normal", text="🔍  Scan Now")
            self.after(0, _err)

    def _rebuild_drive_cards(self, drives, critical):
        """Destroys old drive cards and rebuilds them with fresh scan data."""
        # Clear existing cards
        for widget in self.sh_drives_frame.winfo_children():
            widget.destroy()

        if not drives:
            ctk.CTkLabel(
                self.sh_drives_frame,
                text="No drives detected.",
                font=ctk.CTkFont(size=13), text_color="#6b7280"
            ).pack(pady=20)
            return

        # Create a grid of drive cards (3 per row)
        critical_letters = {d["drive_letter"] for d in critical}
        cards_per_row = 3

        self.sh_drives_frame.columnconfigure(tuple(range(cards_per_row)), weight=1, uniform="dc")

        for idx, d in enumerate(drives):
            row_i = idx // cards_per_row
            col_i = idx % cards_per_row

            is_critical = d["drive_letter"] in critical_letters
            border_color = "#dc2626" if is_critical else "#374151"
            bg_color = ("#2a1515", "#1a0a0a") if is_critical else ("#1e293b", "#0f172a")

            card = ctk.CTkFrame(
                self.sh_drives_frame,
                corner_radius=10,
                fg_color=bg_color,
                border_width=2,
                border_color=border_color
            )
            card.grid(row=row_i, column=col_i, padx=5, pady=5, sticky="nsew")

            # Drive letter & type badge
            header_f = ctk.CTkFrame(card, fg_color="transparent")
            header_f.pack(fill="x", padx=12, pady=(10, 4))

            label_text = d["drive_letter"]
            if d.get("label"):
                label_text += f"  {d['label']}"

            ctk.CTkLabel(
                header_f,
                text=label_text,
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#f87171" if is_critical else "#e5e7eb"
            ).pack(side="left")

            type_color = "#818cf8" if d["drive_type"] == "Network" else "#6b7280"
            ctk.CTkLabel(
                header_f,
                text=d["drive_type"],
                font=ctk.CTkFont(size=10),
                text_color=type_color
            ).pack(side="right")

            # Usage progress bar
            pct_val = d["usage_percent"] / 100.0
            bar_color = "#dc2626" if is_critical else ("#f59e0b" if d["usage_percent"] > 80 else "#10b981")

            pbar = ctk.CTkProgressBar(
                card, width=180, height=10, corner_radius=5,
                progress_color=bar_color
            )
            pbar.pack(padx=12, pady=(4, 4))
            pbar.set(pct_val)

            # Stats
            ctk.CTkLabel(
                card,
                text=f"Total: {d['total_gb']:.1f} GB   |   Free: {d['free_gb']:.1f} GB   |   {d['usage_percent']}% used",
                font=ctk.CTkFont(size=11),
                text_color="#9ca3af"
            ).pack(padx=12, pady=(0, 4))

            # Critical alert reason
            if is_critical:
                reason = next((c.get("alert_reason", "") for c in critical if c["drive_letter"] == d["drive_letter"]), "")
                if reason:
                    ctk.CTkLabel(
                        card,
                        text=f"⚠️ {reason}",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        text_color="#fbbf24"
                    ).pack(padx=12, pady=(0, 8))
            else:
                ctk.CTkLabel(card, text="", height=8).pack()  # spacer

    def _open_storage_sheet(self):
        """Opens the Google Sheet Storage Monitor tab in the default browser."""
        sheet_id = self.config_data.get("GOOGLE_SHEET_ID", "")
        if sheet_id:
            import webbrowser
            webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sheet_id}")
        else:
            messagebox.showwarning("No Sheet ID", "Google Sheet ID is not configured in Settings.")

    def _test_storage_email(self):
        """Sends a test email to verify SMTP configuration."""
        # Save current settings first
        self._save_storage_settings()
        ok, msg = send_test_storage_email(self.config_data, log_cb=self.append_log)
        if ok:
            messagebox.showinfo("Test Email", msg)
        else:
            messagebox.showerror("Test Email Failed", msg)

    # =========================================================================
    # TAB 6: PERFORMANCE QUERY & DATABASE RE-INDEXING MAINTENANCE
    # =========================================================================
    def _build_performance_tab(self):
        """Builds the Performance Query & Re-Indexing tab with diagnostics and controls."""
        tab = self.tab_performance

        scroll = ctk.CTkScrollableFrame(tab, corner_radius=10, fg_color=("#374151", "#1f2937"))
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Section Header ─────────────────────────────────────────────
        ctk.CTkLabel(
            scroll,
            text="Database Performance & Re-Indexing Maintenance",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            scroll,
            text="Module 3: Analyzes index fragmentation, performs pre-maintenance safety backup, runs DBCC CHECKDB integrity validation, rebuilds indexes (FillFactor 80), and logs telemetry to Google Sheets.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=20, pady=(0, 15))

        # ── Target Database & Configuration Card ───────────────────────
        perf_cfg_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        perf_cfg_card.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            perf_cfg_card,
            text="TARGET DATABASE & MAINTENANCE PARAMETERS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8"
        ).pack(anchor="w", padx=15, pady=(12, 10))

        # Row 1: Target Database & SQL Instance
        row1 = ctk.CTkFrame(perf_cfg_card, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=(0, 10))

        ctk.CTkLabel(row1, text="Target Database:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))
        dbs_list = self.config_data.get("TARGET_DATABASES", [])
        if not dbs_list and self.config_data.get("DATABASE_NAME"):
            dbs_list = [self.config_data.get("DATABASE_NAME")]
        if not dbs_list:
            dbs_list = ["BARTONGLASS_TEST_NEW", "TuffCoGlass", "WAGlassKote", "TheDatabase"]

        self.perf_db_var = tk.StringVar(value=dbs_list[0] if dbs_list else "TheDatabase")
        self.perf_db_entry = ctk.CTkComboBox(row1, values=dbs_list, variable=self.perf_db_var, width=220)
        self.perf_db_entry.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(row1, text="SQL Instance:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))
        inst_default = self.config_data.get("SQL_SERVER_INSTANCE") or self.config_data.get("SQL_SERVER_NAME") or "localhost\\SQLDULLA"
        self.perf_inst_var = tk.StringVar(value=inst_default)
        self.perf_inst_entry = ctk.CTkEntry(row1, textvariable=self.perf_inst_var, width=180)
        self.perf_inst_entry.pack(side="left", padx=(0, 10))

        # Row 2: FillFactor and Safety Backup Toggle
        row2 = ctk.CTkFrame(perf_cfg_card, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(0, 12))

        self.perf_backup_chk = ctk.CTkCheckBox(
            row2,
            text="Execute Pre-Maintenance Safety Backup before re-indexing (Recommended)",
            font=ctk.CTkFont(size=12)
        )
        self.perf_backup_chk.pack(side="left", padx=(0, 25))
        self.perf_backup_chk.select()

        ctk.CTkLabel(row2, text="FillFactor:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        self.perf_ff_entry = ctk.CTkEntry(row2, width=60, justify="center")
        self.perf_ff_entry.insert(0, "80")
        self.perf_ff_entry.pack(side="left", padx=(0, 15))

        # ── Action Buttons Row ─────────────────────────────────────────
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))

        self.btn_run_perf_maint = ctk.CTkButton(
            btn_frame,
            text="⚡  Run Full Maintenance Now",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            height=42,
            width=230,
            corner_radius=21,
            command=self._start_performance_maint_thread
        )
        self.btn_run_perf_maint.pack(side="left", padx=(0, 10))

        self.btn_inspect_frag = ctk.CTkButton(
            btn_frame,
            text="🔍  Inspect Fragmentation Only",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=42,
            width=230,
            corner_radius=21,
            command=self._start_inspect_frag_thread
        )
        self.btn_inspect_frag.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_frame,
            text="📊  Open Performance Sheet",
            font=ctk.CTkFont(size=12),
            fg_color="#374151",
            hover_color="#4b5563",
            height=40,
            width=200,
            corner_radius=20,
            command=self._open_performance_sheet
        ).pack(side="left")

        # ── Status and Progress Bar ────────────────────────────────────
        self.perf_status_card = ctk.CTkFrame(scroll, fg_color=("#1e293b", "#0f172a"), corner_radius=8)
        self.perf_status_card.pack(fill="x", padx=20, pady=(0, 10))

        self.perf_status_lbl = ctk.CTkLabel(
            self.perf_status_card,
            text="Status: Ready to execute performance query suite.",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#9ca3af"
        )
        self.perf_status_lbl.pack(side="left", padx=15, pady=10)

        self.perf_progress = ctk.CTkProgressBar(scroll, width=600, height=8, corner_radius=4)
        self.perf_progress.pack(fill="x", padx=20, pady=(0, 15))
        self.perf_progress.set(0)

        # ── Results & Telemetry Metric Cards Grid ──────────────────────
        self.perf_metrics_frame = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#1e293b", "#111827"), border_width=1, border_color="#374151")
        self.perf_metrics_frame.pack(fill="x", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            self.perf_metrics_frame,
            text="LATEST MAINTENANCE DIAGNOSTICS & TELEMETRY",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10b981"
        ).pack(anchor="w", padx=15, pady=(12, 10))

        grid = ctk.CTkFrame(self.perf_metrics_frame, fg_color="transparent")
        grid.pack(fill="x", padx=15, pady=(0, 15))
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # 8 Metric Cards:
        self.tile_sql_ver = self._create_metric_tile(grid, 0, 0, "SQL VERSION", "Not Probed")
        self.tile_db_size = self._create_metric_tile(grid, 0, 1, "DATABASE SIZE", "-- MB")
        self.tile_checkdb = self._create_metric_tile(grid, 0, 2, "CHECKDB STATUS", "Pending")
        self.tile_prebackup = self._create_metric_tile(grid, 0, 3, "SAFETY BACKUP", "Pending")

        self.tile_frag_before = self._create_metric_tile(grid, 1, 0, "MAX FRAG (BEFORE)", "-- %")
        self.tile_frag_after = self._create_metric_tile(grid, 1, 1, "MAX FRAG (AFTER)", "-- %")
        self.tile_duration = self._create_metric_tile(grid, 1, 2, "RUN DURATION", "-- s")
        self.tile_sheet_status = self._create_metric_tile(grid, 1, 3, "CLOUD SHEET", "Awaiting Run")

        # ── Real-Time Console / Output Log Box ─────────────────────────
        ctk.CTkLabel(
            scroll,
            text="MAINTENANCE EXECUTION LOG & INDEX FRAGMENTATION REPORT",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#9ca3af"
        ).pack(anchor="w", padx=20, pady=(5, 5))

        self.perf_console = ctk.CTkTextbox(
            scroll,
            height=200,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0f172a",
            text_color="#e2e8f0"
        )
        self.perf_console.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.perf_console.insert("1.0", "Module 3 Performance Query Engine ready.\nClick 'Inspect Fragmentation Only' to preview index health, or 'Run Full Maintenance Now' to execute safety backup, CHECKDB, DBREINDEX, and cloud sync.\n")

    def _create_metric_tile(self, parent, row, col, title, initial_value):
        frame = ctk.CTkFrame(parent, corner_radius=6, fg_color=("#334155", "#0f172a"), border_width=1, border_color="#1e293b")
        frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=10, weight="bold"), text_color="#94a3b8").pack(anchor="w", padx=10, pady=(8, 2))
        lbl = ctk.CTkLabel(frame, text=initial_value, font=ctk.CTkFont(size=13, weight="bold"), text_color="#ffffff")
        lbl.pack(anchor="w", padx=10, pady=(0, 8))
        return lbl

    def _start_performance_maint_thread(self):
        """Starts full maintenance in background thread."""
        self.btn_run_perf_maint.configure(state="disabled", text="Running Maintenance...")
        self.btn_inspect_frag.configure(state="disabled")
        self.perf_status_lbl.configure(text="Status: Executing maintenance pipeline...", text_color="#fbbf24")
        self.perf_progress.set(0.1)
        threading.Thread(target=self._execute_performance_maint, daemon=True).start()

    def _execute_performance_maint(self):
        from backup_core import run_performance_query
        target_db = self.perf_db_var.get().strip()
        instance = self.perf_inst_var.get().strip()
        skip_backup = not bool(self.perf_backup_chk.get())
        try:
            ff = int(self.perf_ff_entry.get().strip())
        except Exception:
            ff = 80

        def log_cb(msg, level="info"):
            self.append_log(msg, level)
            def _append():
                self.perf_console.insert("end", f"{msg}\n")
                self.perf_console.see("end")
            self.after(0, _append)

        def status_cb(text):
            self.after(0, lambda: self.perf_status_lbl.configure(text=f"Status: {text}", text_color="#38bdf8"))

        def progress_cb(val):
            self.after(0, lambda: self.perf_progress.set(val))

        try:
            res = run_performance_query(
                config=self.config_data,
                target_db=target_db,
                instance=instance,
                mode="Manual",
                skip_backup=skip_backup,
                fill_factor=ff,
                inspect_only=False,
                log_cb=log_cb,
                status_cb=status_cb,
                progress_cb=progress_cb
            )

            def _update_ui():
                self.tile_sql_ver.configure(text=res.get("sql_version", "MSSQL")[:24])
                self.tile_db_size.configure(text=f"{res.get('db_size_mb', 0):,} MB")
                self.tile_checkdb.configure(text=res.get("checkdb_status", "Clean")[:22], text_color="#10b981" if "clean" in res.get("checkdb_status", "").lower() else "#ef4444")
                self.tile_prebackup.configure(text=res.get("pre_backup_status", "N/A")[:22])
                self.tile_frag_before.configure(text=f"{res.get('frag_before_max', 0):.1f}%", text_color="#f59e0b")
                self.tile_frag_after.configure(text=f"{res.get('frag_after_max', 0):.1f}%", text_color="#10b981")
                self.tile_duration.configure(text=f"{res.get('duration_secs', 0):.1f}s")
                self.tile_sheet_status.configure(text="✓ Logged to Sheet" if res.get("sheet_logged") else "Local Log Only", text_color="#10b981" if res.get("sheet_logged") else "#94a3b8")

                self.btn_run_perf_maint.configure(state="normal", text="⚡  Run Full Maintenance Now")
                self.btn_inspect_frag.configure(state="normal")
                self.perf_status_lbl.configure(text="Status: ✅ Maintenance completed successfully!", text_color="#10b981")
                messagebox.showinfo("Maintenance Complete", f"Database Maintenance Succeeded!\n\nDatabase: {target_db}\nCHECKDB: {res.get('checkdb_status')}\nFragmentation: {res.get('frag_before_max', 0):.1f}% -> {res.get('frag_after_max', 0):.1f}%\nDuration: {res.get('duration_secs')}s\nGoogle Sheet: {'Recorded' if res.get('sheet_logged') else 'Not Logged'}")

            self.after(0, _update_ui)
        except Exception as e:
            def _err(e=e):
                self.btn_run_perf_maint.configure(state="normal", text="⚡  Run Full Maintenance Now")
                self.btn_inspect_frag.configure(state="normal")
                self.perf_status_lbl.configure(text=f"Status: Error — {e}", text_color="#ef4444")
                messagebox.showerror("Maintenance Failed", f"Performance maintenance encountered an error:\n\n{e}")
            self.after(0, _err)

    def _start_inspect_frag_thread(self):
        """Starts fragmentation inspection in background thread."""
        self.btn_inspect_frag.configure(state="disabled", text="Inspecting...")
        self.btn_run_perf_maint.configure(state="disabled")
        self.perf_status_lbl.configure(text="Status: Sampling index fragmentation...", text_color="#38bdf8")
        self.perf_progress.set(0.2)
        threading.Thread(target=self._execute_inspect_frag, daemon=True).start()

    def _execute_inspect_frag(self):
        from backup_core import inspect_index_fragmentation
        target_db = self.perf_db_var.get().strip()
        instance = self.perf_inst_var.get().strip()

        try:
            self.after(0, lambda: self.perf_progress.set(0.5))
            tables, max_frag = inspect_index_fragmentation(target_db, instance=instance)
            self.after(0, lambda: self.perf_progress.set(1.0))

            def _update():
                self.tile_frag_before.configure(text=f"{max_frag:.1f}%", text_color="#f59e0b")
                self.perf_console.insert("end", f"\n--- Fragmentation Analysis for [{target_db}] ---\n")
                self.perf_console.insert("end", f"Found {len(tables)} fragmented indexes (>10%). Max: {max_frag:.2f}%\n")
                for t in tables[:30]:
                    self.perf_console.insert("end", f"  • {t.get('table')}.{t.get('index')} ({t.get('type')}): {t.get('fragmentation')}%\n")
                if len(tables) > 30:
                    self.perf_console.insert("end", f"  ... and {len(tables) - 30} more indexes.\n")
                self.perf_console.see("end")

                self.btn_inspect_frag.configure(state="normal", text="🔍  Inspect Fragmentation Only")
                self.btn_run_perf_maint.configure(state="normal")
                self.perf_status_lbl.configure(text=f"Status: Found {len(tables)} fragmented indexes (Max {max_frag:.1f}%)", text_color="#38bdf8")

            self.after(0, _update)
        except Exception as e:
            def _err(e=e):
                self.btn_inspect_frag.configure(state="normal", text="🔍  Inspect Fragmentation Only")
                self.btn_run_perf_maint.configure(state="normal")
                self.perf_status_lbl.configure(text=f"Status: Inspection Error — {e}", text_color="#ef4444")
            self.after(0, _err)

    def _open_performance_sheet(self):
        """Opens the Google Sheet in the browser."""
        sheet_id = self.config_data.get("GOOGLE_SHEET_ID", "")
        if sheet_id:
            import webbrowser
            webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sheet_id}")
        else:
            messagebox.showwarning("No Sheet ID", "Google Sheet ID is not configured in Settings.")



def main():
    """Launches the desktop GUI application."""
    app = BackupAutomationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
