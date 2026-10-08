"""
build_word_docs.py
=============================================================================
Generates two comprehensive, publication-grade Microsoft Word documents (.docx):
1. ADMIN_INSTALLATION_AND_OPERATIONS_GUIDE.docx
2. CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx

Features:
- Professional corporate formatting (Executive Navy & Slate palette).
- Styled headings, bullet lists, numbered steps, and tables.
- Visual callout boxes (Notes, Warnings, Security Notices).
- Syntax-styled code blocks for PowerShell, T-SQL, Command Line, and JSON.
- Comprehensive step-by-step installation, operations, and UNINSTALL processes.
"""

import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# Color Palette
COLOR_PRIMARY = RGBColor(26, 54, 93)      # Deep Navy #1A365D
COLOR_SECONDARY = RGBColor(43, 108, 176)  # Slate Blue #2B6CB0
COLOR_TEXT = RGBColor(45, 55, 72)         # Charcoal Text #2D3748
COLOR_MUTED = RGBColor(113, 128, 150)     # Gray #718096
COLOR_WARN = RGBColor(197, 48, 48)        # Crimson #C53030
COLOR_SUCCESS = RGBColor(40, 116, 73)     # Forest Green #287449

HEX_PRIMARY = "1A365D"
HEX_SECONDARY = "2B6CB0"
HEX_LIGHT_BG = "F7FAFC"
HEX_CALLOUT_BG = "EDF2F7"
HEX_WARN_BG = "FFF5F5"
HEX_SUCCESS_BG = "F0FFF4"
HEX_BORDER = "CBD5E0"

def set_cell_background(cell, fill_hex):
    """Sets background shading of a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets internal padding (in twips) of a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def add_callout(doc, text, title="NOTE", callout_type="info"):
    """Adds a visual callout box with a colored left accent border."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    cell = table.rows[0].cells[0]
    cell.width = Inches(6.5)

    bg_hex = HEX_CALLOUT_BG
    border_hex = HEX_SECONDARY
    title_color = COLOR_SECONDARY

    if callout_type == "warn":
        bg_hex = HEX_WARN_BG
        border_hex = "E53E3E"
        title_color = COLOR_WARN
    elif callout_type == "success":
        bg_hex = HEX_SUCCESS_BG
        border_hex = "38A169"
        title_color = COLOR_SUCCESS

    set_cell_background(cell, bg_hex)
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)

    # Set left border only
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="none"/>'
        f'<w:left w:val="single" w:sz="36" w:space="0" w:color="{border_hex}"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(4)
    run_t = p.add_run(f"[{title}] ")
    run_t.bold = True
    run_t.font.name = "Segoe UI"
    run_t.font.size = Pt(10)
    run_t.font.color.rgb = title_color

    run_b = p.add_run(text)
    run_b.font.name = "Segoe UI"
    run_b.font.size = Pt(9.5)
    run_b.font.color.rgb = COLOR_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

def add_code_block(doc, code_text):
    """Adds a shaded, monospaced code snippet container."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    cell = table.rows[0].cells[0]
    cell.width = Inches(6.5)
    set_cell_background(cell, "1E293B")  # Dark slate background #1E293B
    set_cell_margins(cell, top=120, bottom=120, left=180, right=180)

    # Subtle border
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="6" w:space="0" w:color="334155"/>'
        f'<w:left w:val="single" w:sz="6" w:space="0" w:color="334155"/>'
        f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="334155"/>'
        f'<w:right w:val="single" w:sz="6" w:space="0" w:color="334155"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15

    run = p.add_run(code_text.strip())
    run.font.name = "Consolas"
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor(241, 245, 249)  # Light slate #F1F5F9

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

def format_table(table, col_widths, headers, rows):
    """Applies clean executive styling to a table with widths and headers."""
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # Header Row
    hdr_cells = table.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].text = title
        hdr_cells[i].width = col_widths[i]
        set_cell_background(hdr_cells[i], HEX_PRIMARY)
        set_cell_margins(hdr_cells[i], top=100, bottom=100, left=120, right=120)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for r in p.runs:
            r.font.name = "Segoe UI"
            r.font.size = Pt(9.5)
            r.font.bold = True
            r.font.color.rgb = RGBColor(255, 255, 255)

    # Data Rows
    for r_idx, row_data in enumerate(rows):
        row = table.add_row()
        fill_hex = HEX_LIGHT_BG if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row_data):
            cell = row.cells[c_idx]
            cell.text = str(val)
            cell.width = col_widths[c_idx]
            set_cell_background(cell, fill_hex)
            set_cell_margins(cell, top=80, bottom=80, left=120, right=120)

            # Borders
            tcPr = cell._tc.get_or_add_tcPr()
            b = parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                f'<w:top w:val="single" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>'
                f'<w:left w:val="none"/>'
                f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>'
                f'<w:right w:val="none"/>'
                f'</w:tcBorders>'
            )
            tcPr.append(b)

            p = cell.paragraphs[0]
            for r in p.runs:
                r.font.name = "Segoe UI"
                r.font.size = Pt(9)
                r.font.color.rgb = COLOR_TEXT

def build_admin_doc(output_path):
    """Builds the comprehensive Admin Installation & Operations Word Document."""
    doc = docx.Document()

    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        section.page_width = Inches(8.5)
        section.page_height = Inches(11.0)

    # Title Banner
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(20)
    title_p.paragraph_format.space_after = Pt(4)
    run_title = title_p.add_run("ENTERPRISE DATABASE CLOUD BACKUP & MAINTENANCE")
    run_title.font.name = "Segoe UI"
    run_title.font.size = Pt(22)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_PRIMARY

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(16)
    run_sub = sub_p.add_run("Administrator Installation, Provisioning, Disaster Recovery & Operations Manual · v4.2.0")
    run_sub.font.name = "Segoe UI"
    run_sub.font.size = Pt(12)
    run_sub.font.color.rgb = COLOR_SECONDARY

    # Metadata Banner
    meta_table = doc.add_table(rows=1, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = [Inches(1.6), Inches(1.6), Inches(1.6), Inches(1.7)]
    headers = ["Document Version", "Target Audience", "Classification", "Release Track"]
    data = [["v4.2.0 Production", "IT Administrators / DevOps", "RESTRICTED (Internal IT Only)", "Zero-Trust Architecture"]]
    format_table(meta_table, widths, headers, data)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    add_callout(
        doc,
        "CONFIDENTIAL & RESTRICTED: This package and documentation must ONLY be used on the central IT Administrator workstation. "
        "It contains master encryption tools, private signing keys, disaster recovery decryptors, and customer provisioning logic. "
        "DO NOT distribute this package or any of its tools to customer servers.",
        title="SECURITY NOTICE",
        callout_type="warn"
    )

    # Table of Contents
    h1 = doc.add_heading("Table of Contents", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY
    toc_items = [
        "1. Executive Overview & Zero-Trust Architecture",
        "2. Admin Workstation Prerequisites & 1-Click Setup",
        "3. Google Apps Script Broker & Cloud Storage Deployment",
        "4. Auto-Generating 70+ Customer Tabs in Google Sheets",
        "5. Customer Provisioning Workflows (Single Customer & 70+ Batch)",
        "6. Air-Gapped Disaster Recovery & SQL Server Restoration",
        "7. Complete Step-by-Step Uninstallation & Decommissioning Processes",
        "8. Key Management & Long-Term Security Protocols"
    ]
    for item in toc_items:
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(item)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)
        r.font.color.rgb = COLOR_TEXT

    doc.add_page_break()

    # Section 1
    h1 = doc.add_heading("1. Executive Overview & Zero-Trust Architecture", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "The Enterprise Database Cloud Backup & Maintenance Suite provides autonomous, cryptographically verified "
        "database protection and maintenance across 70+ customer SQL Server deployments. Backups are encrypted 100% "
        "client-side with AES-256-GCM and dual RSA-4096 envelope encryption before uploading via a serverless Google "
        "Apps Script broker to Google Drive. The architecture strictly isolates administrative powers from customer servers."
    )
    p.runs[0].font.name = "Segoe UI"

    table_arch = doc.add_table(rows=1, cols=3)
    widths_arch = [Inches(1.8), Inches(2.3), Inches(2.4)]
    headers_arch = ["Component", "Location", "Security Role & Guarantees"]
    rows_arch = [
        ["Admin Installation Package", "IT Admin Workstation", "Houses customer provisioning scripts, bundle signing keys (Ed25519), and offline recovery decryptors."],
        ["Client Installation Package", "Customer Server", "Holds ONLY public keys (backup_public.pem). Can encrypt backups but CANNOT decrypt them. Zero Python."],
        ["Google Apps Script Broker", "Google Cloud / Workspace", "Stateless serverless gateway. Uploads chunks to Google Drive and logs telemetry to Google Sheets without GCP billing."]
    ]
    format_table(table_arch, widths_arch, headers_arch, rows_arch)
    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # Section 2
    h1 = doc.add_heading("2. Admin Workstation Prerequisites & 1-Click Setup", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph("Follow these exact steps to prepare your administrative machine:")
    p.runs[0].font.name = "Segoe UI"

    steps_s2 = [
        "Step 1: Verify Python 3.9 or newer is installed on your Windows workstation. Ensure 'Add Python to PATH' was checked during installation.",
        "Step 2: Navigate to the Admin_Installation_Package root folder.",
        "Step 3: Double-click Setup_Admin_Environment.bat (or execute it in Command Prompt).",
        "Step 4: The automated script creates an isolated virtual environment (.venv), upgrades pip, installs cryptography, requests, and google-api-client, and validates imports.",
        "Step 5: You will see the green confirmation banner: 'ADMIN ENVIRONMENT IS 100% READY!'."
    ]
    for s in steps_s2:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    add_code_block(doc, "cd C:\\Admin_Installation_Package\nSetup_Admin_Environment.bat")

    # Section 3
    h1 = doc.add_heading("3. Google Apps Script Broker & Cloud Storage Deployment", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "The Google Apps Script Master Broker (Code.gs) acts as the secure, zero-billing relay between all 70+ client servers "
        "and your central Google Drive & Sheets repositories."
    )
    p.runs[0].font.name = "Segoe UI"

    steps_s3 = [
        "Step 1: Open Google Drive in your web browser using your administrative account.",
        "Step 2: Create a parent folder for all backups, e.g., 'Enterprise Customer Backups'. Note its Folder ID from the URL (the string after /folders/).",
        "Step 3: Create a master Google Sheet named 'Application report'. Note its Spreadsheet ID from the URL (the string between /d/ and /edit).",
        "Step 4: Go to https://script.google.com and click 'New project' (or open your spreadsheet -> Extensions -> Apps Script).",
        "Step 5: Replace all code in Code.gs with the complete content of 3_Cloud_Broker_Deployment\\Code.gs.",
        "Step 6: Update lines 12-13 with your Spreadsheet ID and Parent Drive Folder ID.",
        "Step 7: In the left sidebar, click Project Settings (Gear icon) -> check 'Show appsscript.json manifest in editor' -> paste the content from 3_Cloud_Broker_Deployment\\appsscript.json.",
        "Step 8: Click the Deploy button -> New deployment -> Select type: Web App.",
        "Step 9: Configure: Execute as: 'Me' (your admin account), Who has access: 'Anyone'. Click Deploy.",
        "Step 10: Copy and save the resulting Web App URL (starts with https://script.google.com/macros/s/.../exec)."
    ]
    for s in steps_s3:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    add_callout(
        doc,
        "Always select 'Anyone' for 'Who has access'. This enables zero-trust client servers to upload encrypted ciphertext "
        "and post telemetry via HTTPS without requiring client Google account credentials.",
        title="CRITICAL DEPLOYMENT SETTING",
        callout_type="info"
    )

    # Section 4
    h1 = doc.add_heading("4. Auto-Generating 70+ Customer Tabs in Google Sheets", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "To save hours of manual spreadsheet configuration, Code.gs includes an automated initialization routine "
        "that instantly generates all 70+ customer tabs in your Master 'Application report' spreadsheet."
    )
    p.runs[0].font.name = "Segoe UI"

    steps_s4 = [
        "Step 1: In the Google Apps Script editor, locate the toolbar function dropdown menu (defaults to doGet or doPost).",
        "Step 2: Select the function named 'setupApplicationReportTabs'.",
        "Step 3: Click the Run button.",
        "Step 4: When prompted, grant permissions to allow the script to manage spreadsheet tabs.",
        "Step 5: The script executes in ~10 seconds and automatically generates individual formatted tabs for all 70+ customers (adelaideglass, bnd, viridian, etc.) with frozen header rows."
    ]
    for s in steps_s4:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    # Section 5
    h1 = doc.add_heading("5. Customer Provisioning Workflows (Single & 70+ Batch)", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "Customer provisioning generates unique 4096-bit RSA keys, seals the configuration in a cryptographically "
        "signed bundle.json, and outputs a customer-ready deployment package with zero secret leakage."
    )
    p.runs[0].font.name = "Segoe UI"

    doc.add_heading("Option A: Batch Provisioning All 70+ Customers in One Pass", level=2).runs[0].font.color.rgb = COLOR_SECONDARY
    steps_s5a = [
        "Step 1: Open command prompt in Admin_Installation_Package\\1_Customer_Provisioning.",
        "Step 2: Verify or edit customer_slugs.txt (one customer per line: slug,Display Name).",
        "Step 3: Run: python batch_setup_customers.py",
        "Step 4: Paste your Apps Script Broker URL when prompted.",
        "Step 5: Enter your Admin Ed25519 signing key path and passphrase.",
        "Step 6: Choose whether to use a shared passphrase or individual passphrases for recovery keys.",
        "Step 7: The wizard generates keys, signs bundles, and creates customers\\<slug>_package for all customers.",
        "Step 8: Open customers\\enroll_codes_for_sheet.tsv and paste the rows directly into columns A, B, C of your Google Sheet 'Config' tab."
    ]
    for s in steps_s5a:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    add_code_block(doc, "cd C:\\Admin_Installation_Package\\1_Customer_Provisioning\npython batch_setup_customers.py")

    doc.add_heading("Option B: Single Customer Provisioning Wizard", level=2).runs[0].font.color.rgb = COLOR_SECONDARY
    steps_s5b = [
        "Step 1: Run: python setup_new_customer.py",
        "Step 2: Enter customer slug (e.g. acme) and Apps Script Broker URL.",
        "Step 3: Choose a strong passphrase (14+ characters) for the customer's private keys.",
        "Step 4: Provide your Admin Signing Key to sign bundle.json.",
        "Step 5: Copy the output row (ENROLL_CODE <code-string> acme) into your Google Sheet Config tab.",
        "Step 6: The customer deployment package is saved in customers\\acme_package."
    ]
    for s in steps_s5b:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    # Section 6
    h1 = doc.add_heading("6. Air-Gapped Disaster Recovery & SQL Server Restoration", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "If a customer server suffers ransomware, hardware failure, or corruption, use the air-gapped recovery suite "
        "to decrypt the raw database (.bak) and restore it to SQL Server."
    )
    p.runs[0].font.name = "Segoe UI"

    doc.add_heading("Step-by-Step Restoration Runbook:", level=2).runs[0].font.color.rgb = COLOR_SECONDARY
    steps_s6 = [
        "Step 1: Download the target encrypted backup file (.dbk2) from the customer's folder in Google Drive.",
        "Step 2: Place the file on your Admin workstation or secure restoration server.",
        "Step 3: Double-click 2_Disaster_Recovery\\Launch_Recovery_Wizard.bat (or run python decrypt_gui.py).",
        "Step 4: Click 'Browse Encrypted File' and select the downloaded .dbk2 file.",
        "Step 5: Click 'Browse Private Key' and select the customer's backup_private.pem (or the master escrow_private.pem).",
        "Step 6: Enter the key passphrase and choose the output folder for the restored database.",
        "Step 7: Click 'Start Decryption & Integrity Verification'. The tool verifies the 128-bit AES-GCM MAC tag and produces the authentic .bak file.",
        "Step 8: Open SQL Server Management Studio (SSMS) -> right click Databases -> Restore Database -> Device -> select the decrypted .bak file -> click OK."
    ]
    for s in steps_s6:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    add_code_block(doc, "-- SQL Server T-SQL Fast Restore Script\nRESTORE DATABASE [TheDatabase]\nFROM DISK = N'C:\\Restores\\TheDatabase_Restored.bak'\nWITH REPLACE, RECOVERY, STATS = 10;\nGO")

    # Section 7
    h1 = doc.add_heading("7. Complete Step-by-Step Uninstallation & Decommissioning Processes", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "When an administrator needs to decommission an agent or guide a customer through complete removal, "
        "follow these strict uninstallation procedures to ensure zero orphaned scheduled tasks or credential leaks."
    )
    p.runs[0].font.name = "Segoe UI"

    table_uninst = doc.add_table(rows=1, cols=3)
    widths_un = [Inches(1.8), Inches(2.2), Inches(2.5)]
    headers_un = ["Method", "Target Environment", "Action & Scope"]
    rows_un = [
        ["PowerShell Uninstaller (uninstall_agent.ps1)", "Server Core / Headless / PowerShell Agent Track", "Terminates active processes, deletes all 3 scheduled tasks, shreds token.dpapi with random bytes, deletes scripts and directories."],
        ["Windows 1-Click Uninstaller (Uninstall.bat)", "Windows Desktop / Full GUI Track", "Self-elevating batch uninstaller. Cleans Program Files, ProgramData, registry uninstall keys, and shortcuts across all profiles."],
        ["Windows Settings / appwiz.cpl", "Standard Windows Control Panel", "Invokes registered UninstallString from registry. Silently or interactively executes clean uninstallation."]
    ]
    format_table(table_uninst, widths_un, headers_un, rows_un)
    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    doc.add_heading("Admin Decommissioning Checklist:", level=2).runs[0].font.color.rgb = COLOR_SECONDARY
    steps_s7 = [
        "1. Instruct customer to run uninstall_agent.ps1 or Uninstall.bat on their server.",
        "2. Open the Master Google Sheet -> go to the 'Tokens' tab -> delete the enrolled row corresponding to the decommissioned server.",
        "3. Go to the 'Config' tab -> clear the customer's ENROLL_CODE row.",
        "4. In Google Drive, archive or retention-lock the customer's historical backup folder according to company compliance policies.",
        "5. Move the customer's offline private keys (<slug>_keys) into long-term encrypted archive vault."
    ]
    for s in steps_s7:
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    # Section 8
    h1 = doc.add_heading("8. Key Management & Long-Term Security Protocols", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    table_keys = doc.add_table(rows=1, cols=3)
    widths_k = [Inches(2.0), Inches(2.0), Inches(2.5)]
    headers_k = ["Key Identifier", "Algorithm & Key Size", "Storage Policy & Restrictions"]
    rows_k = [
        ["Admin Signing Key (admin_ed25519.pem)", "Ed25519 (256-bit elliptic curve)", "Admin hardware only. Never in cloud-synced folders (OneDrive/Dropbox). Protected by 14+ char passphrase."],
        ["Customer Primary Key (<slug>_private.pem)", "RSA-4096 (PKCS#8 Encrypted)", "Stored offline in 2_Disaster_Recovery\\keys. Used for customer restoration requests."],
        ["Enterprise Escrow Key (escrow_private.pem)", "RSA-4096 (PKCS#8 Encrypted)", "Master emergency recovery key. Can decrypt any archive if customer key is lost. Keep in physical offline safe."]
    ]
    format_table(table_keys, widths_k, headers_k, rows_k)

    doc.save(output_path)
    print(f"[OK] Admin Word Guide created: {output_path} ({os.path.getsize(output_path):,} bytes)")


def build_client_doc(output_path):
    """Builds the comprehensive Client / Customer Installation & Operations Word Document."""
    doc = docx.Document()

    # Page Margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)
        section.page_width = Inches(8.5)
        section.page_height = Inches(11.0)

    # Title Banner
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(20)
    title_p.paragraph_format.space_after = Pt(4)
    run_title = title_p.add_run("ENTERPRISE DATABASE CLOUD BACKUP & MAINTENANCE")
    run_title.font.name = "Segoe UI"
    run_title.font.size = Pt(22)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_PRIMARY

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(16)
    run_sub = sub_p.add_run("Customer Server Installation, Operations, Monitoring & Uninstallation Guide · v4.2.0")
    run_sub.font.name = "Segoe UI"
    run_sub.font.size = Pt(12)
    run_sub.font.color.rgb = COLOR_SECONDARY

    # Metadata Banner
    meta_table = doc.add_table(rows=1, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = [Inches(1.6), Inches(1.6), Inches(1.6), Inches(1.7)]
    headers = ["Software Version", "Target Audience", "Client Runtime", "Encryption Standard"]
    data = [["v4.2.0 Production", "Server Admins / DBA / IT Staff", "Zero Python Required", "AES-256-GCM + RSA-4096"]]
    format_table(meta_table, widths, headers, data)

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    add_callout(
        doc,
        "ZERO PYTHON REQUIRED & ZERO CLOUD CREDENTIALS: This software runs natively on Windows Server using built-in "
        "Windows PowerShell 5.1+ and .NET Cryptography. No Python runtime or compilers are needed. The client server holds "
        "NO Google passwords, OAuth secrets, or service account keys.",
        title="SECURITY GUARANTEE",
        callout_type="success"
    )

    # Table of Contents
    h1 = doc.add_heading("Table of Contents", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY
    toc_items = [
        "1. Overview & The Three Autonomous Maintenance Modules",
        "2. System Requirements & Pre-Installation Checklist",
        "3. Installation Track 1: Native Windows PowerShell Agent (Recommended)",
        "4. Installation Track 2: Graphical Setup Wizard (Setup_DatabaseBackup.exe)",
        "5. Configuration Settings Reference (config.json)",
        "6. Manual Testing & Operational Verification",
        "7. Complete Step-by-Step Uninstallation Procedures",
        "8. Log Files, Monitoring & Troubleshooting"
    ]
    for item in toc_items:
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(item)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)
        r.font.color.rgb = COLOR_TEXT

    doc.add_page_break()

    # Section 1
    h1 = doc.add_heading("1. Overview & The Three Autonomous Maintenance Modules", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "This software suite automates three essential database maintenance and protection operations on your Windows Server:"
    )
    p.runs[0].font.name = "Segoe UI"

    table_mod = doc.add_table(rows=1, cols=3)
    widths_mod = [Inches(1.8), Inches(2.2), Inches(2.5)]
    headers_mod = ["Maintenance Module", "Engine Script", "Operational Capabilities"]
    rows_mod = [
        ["Module 1: Database Backup Engine", "backup_agent.ps1", "Creates native compressed SQL dumps (.bak), encrypts client-side using AES-256-GCM + RSA-4096 into .dbk2 archives, and uploads directly to your dedicated cloud folder."],
        ["Module 2: Server Cleanup Scan", "storage_monitor.ps1", "Monitors disk capacity, enforces retention policies by deleting staging files older than RETENTION_DAYS, and initiates emergency cleanup if disk exceeds threshold (85%)."],
        ["Module 3: Database Performance & Re-indexing", "performance_query.ps1", "Samples table index fragmentation, executes a pre-maintenance safety backup, runs DBCC CHECKDB, rebuilds indexes with DBCC DBREINDEX at FillFactor 80, updates stats (sp_updatestats), and reports metrics."]
    ]
    format_table(table_mod, widths_mod, headers_mod, rows_mod)
    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # Section 2
    h1 = doc.add_heading("2. System Requirements & Pre-Installation Checklist", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    table_req = doc.add_table(rows=1, cols=2)
    widths_req = [Inches(2.5), Inches(4.0)]
    headers_req = ["Requirement", "Specification"]
    rows_req = [
        ["Operating System", "Windows Server 2012 R2, 2016, 2019, 2022, 2025, or Windows 10/11 (64-bit)"],
        ["Permissions", "Local Administrator rights (required for Windows Task Scheduler and DPAPI vault)"],
        ["Database Engine", "Microsoft SQL Server 2012 through 2025 (Express, Standard, or Enterprise)"],
        ["PowerShell Version", "Windows PowerShell 5.1 (built into Windows) or PowerShell 7+"],
        ["Network Connectivity", "Outbound HTTPS (Port 443) to script.google.com and drive.google.com"],
        ["Client Python Requirement", "ABSOLUTELY NOT REQUIRED (Zero Runtime footprint)"],
        ["Disk Space", "50 MB for PowerShell agent; staging directory requires ~2.5x database size"]
    ]
    format_table(table_req, widths_req, headers_req, rows_req)
    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # Section 3
    h1 = doc.add_heading("3. Installation Track 1: Native Windows PowerShell Agent (Recommended)", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "This is the recommended, lightweight deployment track for servers. It uses out-of-the-box Windows OS tools "
        "with zero external binaries or compilers."
    )
    p.runs[0].font.name = "Segoe UI"

    steps_s3 = [
        "Step 1: Extract the provided client package zip file to a local staging folder, such as C:\\Temp\\Client_Package.",
        "Step 2: Open an elevated PowerShell prompt: Click Windows Start -> search 'PowerShell' -> right-click 'Windows PowerShell' -> select 'Run as Administrator'.",
        "Step 3: Navigate into the shell_client folder:\n   cd C:\\Temp\\Client_Package\\shell_client",
        "Step 4: Execute the agent installer script:\n   powershell.exe -ExecutionPolicy Bypass -File .\\install_agent.ps1",
        "Step 5: The installer validates the signed bundle.json, seals the machine authentication token into Windows DPAPI (LocalMachine scope), copies scripts into C:\\Program Files\\DatabaseBackupApp, and registers the 3 Windows Scheduled Tasks.",
        "Step 6: You will see the green success banner confirming installation is complete."
    ]
    for s in steps_s3:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    add_code_block(doc, "cd C:\\Temp\\Client_Package\\shell_client\npowershell.exe -ExecutionPolicy Bypass -File .\\install_agent.ps1")

    # Section 4
    h1 = doc.add_heading("4. Installation Track 2: Graphical Setup Wizard (Setup_DatabaseBackup.exe)", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph("If you prefer an interactive desktop wizard with graphical controls:")
    p.runs[0].font.name = "Segoe UI"

    steps_s4 = [
        "Step 1: In the extracted package root, locate Setup_DatabaseBackup.exe.",
        "Step 2: Right-click Setup_DatabaseBackup.exe and select 'Run as administrator'.",
        "Step 3: The setup wizard opens. Review the installation directory (defaults to C:\\Program Files\\DatabaseBackupApp).",
        "Step 4: Confirm background schedule registration and desktop shortcuts.",
        "Step 5: Click Install. The setup wizard copies runtime files, sets permissions, registers background tasks, and creates desktop/Start menu shortcuts."
    ]
    for s in steps_s4:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    # Section 5
    h1 = doc.add_heading("5. Configuration Settings Reference (config.json)", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph("Configuration parameters are stored in C:\\ProgramData\\DatabaseBackupApp\\config.json:")
    p.runs[0].font.name = "Segoe UI"

    table_cfg = doc.add_table(rows=1, cols=3)
    widths_cfg = [Inches(2.2), Inches(1.5), Inches(2.8)]
    headers_cfg = ["Parameter", "Default Value", "Description"]
    rows_cfg = [
        ["CUSTOMER_SLUG", "Provided in bundle", "Your unique organization identifier for cloud storage routing."],
        ["BROKER_URL", "Apps Script Web App", "The HTTPS endpoint of the cloud broker."],
        ["DATABASE_NAME", "TheDatabase", "The target SQL Server database to protect and maintain."],
        ["SQL_SERVER_INSTANCE", "localhost", "The SQL Server instance name (e.g., localhost or .\\SQLEXPRESS)."],
        ["BACKUP_FOLDER", "C:\\SQLBackups", "Local temporary staging folder for database dumps."],
        ["RETENTION_DAYS", "30", "Number of days before local staging backups are purged."],
        ["CLEANUP_THRESHOLD_PERCENT", "85", "Disk usage percentage that triggers emergency local staging purge."],
        ["PERFORMANCE_SCHEDULE_DAY", "Sunday", "Day of the week for index re-indexing (Daily or Sunday..Saturday)."],
        ["PERFORMANCE_SCHEDULE_TIME", "03:30", "Fixed time of day (24h format) for index rebuild execution."]
    ]
    format_table(table_cfg, widths_cfg, headers_cfg, rows_cfg)
    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # Section 6
    h1 = doc.add_heading("6. Manual Testing & Operational Verification", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph("You can test each module immediately from an elevated PowerShell terminal:")
    p.runs[0].font.name = "Segoe UI"

    doc.add_heading("1. Test Database Backup Module:", level=3).runs[0].font.color.rgb = COLOR_SECONDARY
    add_code_block(doc, "powershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\backup_agent.ps1\" -DatabaseName \"TheDatabase\"")

    doc.add_heading("2. Test Server Cleanup Scan Module:", level=3).runs[0].font.color.rgb = COLOR_SECONDARY
    add_code_block(doc, "powershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\storage_monitor.ps1\"")

    doc.add_heading("3. Test Performance Maintenance Module:", level=3).runs[0].font.color.rgb = COLOR_SECONDARY
    add_code_block(doc, "powershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\performance_query.ps1\" -DatabaseName \"TheDatabase\" -Mode Manual")

    doc.add_heading("4. Master Orchestrator (Runs All Modules):", level=3).runs[0].font.color.rgb = COLOR_SECONDARY
    add_code_block(doc, "powershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\run_automation.ps1\" -Task All -Mode Manual")

    # Section 7
    h1 = doc.add_heading("7. Complete Step-by-Step Uninstallation Procedures", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    p = doc.add_paragraph(
        "If you ever need to remove the software from the server, choose the uninstallation method that matches "
        "your deployment preference. Both methods perform complete, clean uninstallation with zero leftover background tasks."
    )
    p.runs[0].font.name = "Segoe UI"

    doc.add_heading("Method 1: Native PowerShell Agent Uninstaller (Fastest & Cleanest)", level=2).runs[0].font.color.rgb = COLOR_SECONDARY
    steps_u1 = [
        "Step 1: Open an elevated PowerShell prompt (Run as Administrator).",
        "Step 2: Run the uninstaller script:\n   powershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\uninstall_agent.ps1\"",
        "Step 3: Confirm with 'Y' when prompted.",
        "Step 4: The script performs 6 clean phases:\n   • Archives audit logs to Desktop (DatabaseBackup_Logs_Archive)\n   • Terminates running backup and query processes\n   • Unregisters all Windows Scheduled Tasks\n   • Shreds DPAPI machine authentication tokens\n   • Purges C:\\Program Files\\DatabaseBackupApp and C:\\ProgramData\\DatabaseBackupApp\n   • Deletes all desktop and start menu shortcuts",
        "Step 5: Displays green confirmation: 'UNINSTALLATION COMPLETE (100% CLEAN)'."
    ]
    for s in steps_u1:
        p = doc.add_paragraph(style='List Number')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    add_code_block(doc, "# Interactive Uninstallation (prompts before delete & archives logs)\npowershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\uninstall_agent.ps1\"\n\n# Silent Unattended Uninstallation (for RMM / Automated scripts)\npowershell.exe -ExecutionPolicy Bypass -File \"C:\\Program Files\\DatabaseBackupApp\\uninstall_agent.ps1\" -Force")

    doc.add_heading("Method 2: Windows Settings / Control Panel / Start Menu", level=2).runs[0].font.color.rgb = COLOR_SECONDARY
    steps_u2 = [
        "Option A (Settings): Open Windows Settings -> Apps -> Installed apps -> locate 'Database Cloud Backup' -> click Uninstall.",
        "Option B (Start Menu): Click Windows Start -> locate 'Uninstall Database Cloud Backup' -> click to run.",
        "Option C (Batch File): Navigate to C:\\Program Files\\DatabaseBackupApp (or package root) -> double-click Uninstall.bat.",
        "Follow on-screen prompt -> Click Yes to confirm -> The uninstaller cleanly wipes tasks, shortcuts, registry entries, and program directories."
    ]
    for s in steps_u2:
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(s)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)

    # Section 8
    h1 = doc.add_heading("8. Log Files, Monitoring & Troubleshooting", level=1)
    h1.runs[0].font.color.rgb = COLOR_PRIMARY

    table_logs = doc.add_table(rows=1, cols=2)
    widths_l = [Inches(3.0), Inches(3.5)]
    headers_l = ["Log File / Monitor", "Description & Usage"]
    rows_l = [
        ["C:\\ProgramData\\DatabaseBackupApp\\logs\\backup.log", "Chronological log of database backups, compression ratios, and cloud uploads."],
        ["C:\\ProgramData\\DatabaseBackupApp\\logs\\storage_cleanup.log", "Disk space scan results, free space percentages, and staging purge records."],
        ["C:\\ProgramData\\DatabaseBackupApp\\logs\\performance_query.log", "Index fragmentation measurements (before/after), CHECKDB integrity output, and DBREINDEX duration."],
        ["Windows Task Scheduler (taskschd.msc)", "Inspect Task Scheduler Library -> tasks prefixed with 'DatabaseBackup_' to review last run time and exit codes (0x0 = Success)."]
    ]
    format_table(table_logs, widths_l, headers_l, rows_l)

    doc.save(output_path)
    print(f"[OK] Client Word Guide created: {output_path} ({os.path.getsize(output_path):,} bytes)")


def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    admin_targets = [
        os.path.join(base_dir, "Admin_Installation_Package", "ADMIN_INSTALLATION_AND_OPERATIONS_GUIDE.docx"),
        os.path.join(base_dir, "Admin_Installation_Package", "4_Documentation", "ADMIN_INSTALLATION_AND_OPERATIONS_GUIDE.docx"),
        os.path.join(base_dir, "BackupAutomation", "docs", "ADMIN_INSTALLATION_AND_OPERATIONS_GUIDE.docx")
    ]

    client_targets = [
        os.path.join(base_dir, "Client_Installation_Package", "CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx"),
        os.path.join(base_dir, "BackupAutomation", "CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx"),
        os.path.join(base_dir, "BackupAutomation", "docs", "CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx")
    ]

    # Generate primary Admin doc
    primary_admin = admin_targets[0]
    os.makedirs(os.path.dirname(primary_admin), exist_ok=True)
    build_admin_doc(primary_admin)

    import shutil
    for t in admin_targets[1:]:
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copy2(primary_admin, t)
        print(f"[SYNC] Copied Admin Guide to: {t}")

    # Generate primary Client doc
    primary_client = client_targets[0]
    os.makedirs(os.path.dirname(primary_client), exist_ok=True)
    build_client_doc(primary_client)

    for t in client_targets[1:]:
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copy2(primary_client, t)
        print(f"[SYNC] Copied Client Guide to: {t}")

    print("\n[SUCCESS] All Microsoft Word (.docx) guides built and synchronized perfectly!")

if __name__ == "__main__":
    main()
