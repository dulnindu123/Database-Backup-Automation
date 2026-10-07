"""
Admin Recovery Wizard - Standalone Desktop Decryption Tool (v4.2.0)
=============================================================================
RESTRICTED: Internal Admin Workstation Tool Only (Air-Gapped Disaster Recovery).
Never distribute this tool or private keys to client machines!

Features:
- Decrypts .dbk2 archives using either Customer Primary or Admin Escrow RSA-4096 private key.
- Authenticates 128-bit AES-GCM MAC tags and header context bindings.
- Atomic decryption: zero incomplete/corrupted output left on disk if tampering occurs.
- Graphical user interface using standard Python Tkinter (zero external GUI dependencies).
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Resolve path to crypto_stream
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from crypto_stream import decrypt_file, DecryptionError
except ImportError:
    # Standalone fallback if copied outside repo
    try:
        from .crypto_stream import decrypt_file, DecryptionError
    except Exception:
        raise ImportError("crypto_stream module could not be located.")


class AdminRecoveryWizardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🛡️ Enterprise Disaster Recovery Wizard - Admin Decryption Suite")
        self.geometry("780x620")
        self.minsize(700, 560)
        self.configure(bg="#1e1e2e")

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._configure_styles()

        self._build_ui()

    def _configure_styles(self):
        self.style.configure(".", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#89b4fa", background="#1e1e2e")
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9), foreground="#a6adc8", background="#1e1e2e")
        self.style.configure("Card.TFrame", background="#252538", relief="ridge", borderwidth=1)
        self.style.configure("FieldLabel.TLabel", font=("Segoe UI", 9, "bold"), foreground="#bac2de", background="#252538")
        self.style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), background="#a6e3a1", foreground="#11111b", borderwidth=0)
        self.style.map("Action.TButton", background=[("active", "#94e2d5")])
        self.style.configure("Browse.TButton", font=("Segoe UI", 9), background="#45475a", foreground="#cdd6f4", borderwidth=0)
        self.style.map("Browse.TButton", background=[("active", "#585b70")])

    def _build_ui(self):
        # Header banner
        hdr_frame = ttk.Frame(self, padding="20 15 20 10")
        hdr_frame.pack(fill="x")
        ttk.Label(hdr_frame, text="🔒 Admin Disaster Recovery Tool (Air-Gapped)", style="Header.TLabel").pack(anchor="w")
        ttk.Label(hdr_frame, text="Decrypt .dbk2 archives using offline Primary or Escrow RSA-4096 private keys.", style="SubHeader.TLabel").pack(anchor="w")

        # Main Card
        card = ttk.Frame(self, style="Card.TFrame", padding="20")
        card.pack(fill="x", padx=20, pady=10)

        # 1. Encrypted file input
        ttk.Label(card, text="1. Encrypted Backup File (.dbk2):", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.src_var = tk.StringVar()
        self.src_entry = ttk.Entry(card, textvariable=self.src_var, width=60, font=("Segoe UI", 9))
        self.src_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(0, 12))
        ttk.Button(card, text="Browse...", style="Browse.TButton", command=self._browse_src).grid(row=1, column=1, sticky="w", pady=(0, 12))

        # 2. Private Key input
        ttk.Label(card, text="2. Offline RSA Private Key (.pem):", style="FieldLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 2))
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(card, textvariable=self.key_var, width=60, font=("Segoe UI", 9))
        self.key_entry.grid(row=3, column=0, sticky="ew", padx=(0, 10), pady=(0, 12))
        ttk.Button(card, text="Browse Key...", style="Browse.TButton", command=self._browse_key).grid(row=3, column=1, sticky="w", pady=(0, 12))

        # 3. Key Passphrase
        ttk.Label(card, text="3. Private Key Passphrase (if encrypted):", style="FieldLabel.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 2))
        self.pass_var = tk.StringVar()
        self.pass_entry = ttk.Entry(card, textvariable=self.pass_var, show="•", width=60, font=("Segoe UI", 9))
        self.pass_entry.grid(row=5, column=0, sticky="ew", padx=(0, 10), pady=(0, 12))

        # 4. Output Restored File
        ttk.Label(card, text="4. Destination Restored File (.zip / .bak):", style="FieldLabel.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 2))
        self.dst_var = tk.StringVar()
        self.dst_entry = ttk.Entry(card, textvariable=self.dst_var, width=60, font=("Segoe UI", 9))
        self.dst_entry.grid(row=7, column=0, sticky="ew", padx=(0, 10), pady=(0, 12))
        ttk.Button(card, text="Save As...", style="Browse.TButton", command=self._browse_dst).grid(row=7, column=1, sticky="w", pady=(0, 12))

        card.columnconfigure(0, weight=1)

        # Action Button Frame
        act_frame = ttk.Frame(self, padding="20 5 20 10")
        act_frame.pack(fill="x")
        self.btn_decrypt = ttk.Button(act_frame, text="⚡ Decrypt & Verify Integrity", style="Action.TButton", command=self._start_decryption)
        self.btn_decrypt.pack(fill="x", ipady=8)

        # Progress / Output Log Box
        log_frame = ttk.Frame(self, padding="20 0 20 15")
        log_frame.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="Verification Log & Metadata:", font=("Segoe UI", 9, "bold"), foreground="#a6adc8").pack(anchor="w", pady=(0, 4))
        
        self.log_text = tk.Text(log_frame, bg="#181825", fg="#cdd6f4", font=("Consolas", 9), relief="flat", wrap="word", height=8)
        self.log_text.pack(fill="both", expand=True)

    def _browse_src(self):
        f = filedialog.askopenfilename(
            title="Select Encrypted Backup File",
            filetypes=[("DBK2 Backup Files", "*.dbk2"), ("All Files", "*.*")]
        )
        if f:
            self.src_var.set(f)
            # Auto populate output path
            base, _ = os.path.splitext(f)
            self.dst_var.set(base + "_restored.zip")

    def _browse_key(self):
        f = filedialog.askopenfilename(
            title="Select RSA Private Key File",
            filetypes=[("PEM Private Key", "*.pem"), ("All Files", "*.*")]
        )
        if f:
            self.key_var.set(f)

    def _browse_dst(self):
        f = filedialog.asksaveasfilename(
            title="Select Restored Output Destination",
            filetypes=[("ZIP Archive", "*.zip"), ("SQL Server Backup", "*.bak"), ("All Files", "*.*")]
        )
        if f:
            self.dst_var.set(f)

    def _log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def _start_decryption(self):
        src = self.src_var.get().strip()
        key = self.key_var.get().strip()
        dst = self.dst_var.get().strip()
        pw = self.pass_var.get()

        if not src or not os.path.exists(src):
            messagebox.showerror("Error", "Please select a valid encrypted .dbk2 file.")
            return
        if not key or not os.path.exists(key):
            messagebox.showerror("Error", "Please select a valid private key .pem file.")
            return
        if not dst:
            messagebox.showerror("Error", "Please specify a destination file path.")
            return

        self.btn_decrypt.config(state="disabled")
        self.log_text.delete("1.0", "end")
        self._log(f"[*] Starting decryption of: {os.path.basename(src)}")
        self._log(f"[*] Reading private key: {os.path.basename(key)}")

        t = threading.Thread(target=self._decrypt_worker, args=(src, dst, key, pw), daemon=True)
        t.start()

    def _decrypt_worker(self, src, dst, key, pw):
        try:
            self._log("[*] Unwrapping AES-256 session key via RSA-OAEP SHA-256...")
            meta = decrypt_file(src, dst, key, password=pw if pw else None)
            
            self._log("[+] SUCCESS! File decrypted and 128-bit MAC tag verified.")
            if meta:
                self._log("\n--- Cryptographic Context Binding Verified ---")
                self._log(f"  • Database Name : {meta.get('db')}")
                self._log(f"  • Host Machine  : {meta.get('host')}")
                self._log(f"  • UTC Timestamp : {meta.get('utc_time')}")
                self._log(f"  • Original File : {meta.get('file_name')}")
                self._log(f"  • Output Stored : {dst}")
                self._log("----------------------------------------------\n")
            
            messagebox.showinfo("Success", f"Backup restored and verified successfully!\n\nSaved to: {dst}")
        except DecryptionError as e:
            self._log(f"[-] CRYPTOGRAPHIC ERROR: {e}")
            messagebox.showerror("Decryption Failed", f"Cryptographic integrity check failed:\n{e}")
        except Exception as e:
            self._log(f"[-] ERROR: {e}")
            messagebox.showerror("Error", f"Failed to decrypt backup:\n{e}")
        finally:
            self.btn_decrypt.config(state="normal")


def main():
    app = AdminRecoveryWizardApp()
    app.mainloop()


if __name__ == "__main__":
    main()
