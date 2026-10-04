"""
Batch Customer Setup

Provisions many customers in one run using the same logic as setup_new_customer.py.
  - Reads slugs from Tools/customer_slugs.txt (one per line; 'slug' or 'slug,Display Name')
  - Asks for the Broker URL ONCE and the Admin signing key passphrase ONCE
  - Prompts for a passphrase for EACH customer's private keys (14+ chars)
  - Skips customers that already have a package folder
  - Appends results to customers/enroll_codes.csv and customers/enroll_codes_for_sheet.tsv
    (the .tsv rows can be pasted straight into the Google Sheet 'Config' tab:
     column A = ENROLL_CODE, column B = code, column C = slug)
"""
import os, sys, json, getpass, secrets, shutil, csv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.dirname(__file__))

from setup_new_customer import SLUG_RE, URL_RE, generate_rsa_keypair
from admin.sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SLUG_FILE = os.path.join(os.path.dirname(__file__), "customer_slugs.txt")


def read_slugs():
    items = []
    with open(SLUG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",", 1)]
            slug = parts[0].lower()
            name = parts[1] if len(parts) > 1 else slug
            items.append((slug, name))
    return items


def ask_pw(label):
    while True:
        a = getpass.getpass(f"{label} (14+ chars): ")
        if len(a) < 14:
            print("  Too short.")
            continue
        if a == getpass.getpass("  Repeat: "):
            return a
        print("  Do not match.")


def main():
    if not os.path.exists(SLUG_FILE):
        print(f"Missing {SLUG_FILE}"); sys.exit(1)
    items = read_slugs()
    bad = [s for s, _ in items if not SLUG_RE.match(s)]
    dup = {s for s, _ in items if [x for x, _ in items].count(s) > 1}
    if bad or dup:
        print("Fix slug list first. Invalid:", bad, "Duplicates:", sorted(dup)); sys.exit(1)
    print(f"{len(items)} customers to provision.\n")

    while True:
        url = input("Apps Script Broker URL (https://script.google.com/macros/s/.../exec): ").strip()
        if URL_RE.match(url):
            break
        print("Invalid URL.")

    key_path = input("Admin Ed25519 key path [C:\\admin_ed25519.pem]: ").strip() or "C:\\admin_ed25519.pem"
    if not os.path.exists(key_path):
        if input("Not found. Create new admin key? (y/N): ").strip().lower() != "y":
            sys.exit(1)
        init_key(key_path, ask_pw("New Admin key passphrase"))
    while True:
        try:
            admin_priv = load_private(key_path, getpass.getpass("Admin key passphrase: "))
            break
        except Exception as e:
            print("Failed to load:", e)

    cust_dir = os.path.join(BASE, "customers")
    os.makedirs(cust_dir, exist_ok=True)
    client_pkg = os.path.abspath(os.path.join(BASE, "..", "Client_Installation_Package"))
    dist = os.path.join(BASE, "dist")
    installer = next((p for p in (os.path.join(client_pkg, "Setup_DatabaseBackup.exe"),
                                  os.path.join(dist, "Setup_DatabaseBackup.exe")) if os.path.exists(p)), None)
    appfiles = next((p for p in (os.path.join(client_pkg, "AppFiles"), os.path.join(dist, "AppFiles"))
                     if os.path.exists(p)), None)

    csv_path = os.path.join(cust_dir, "enroll_codes.csv")
    tsv_path = os.path.join(cust_dir, "enroll_codes_for_sheet.tsv")
    new_csv = not os.path.exists(csv_path)
    done = 0
    for i, (slug, name) in enumerate(items, 1):
        pkg = os.path.join(cust_dir, f"{slug}_package")
        keys = os.path.join(cust_dir, f"{slug}_keys")
        if os.path.exists(os.path.join(pkg, "bundle.json")):
            print(f"[{i}/{len(items)}] {name} ({slug}): already provisioned, skipping.")
            continue
        print(f"\n[{i}/{len(items)}] {name} ({slug})")
        pw = ask_pw("Passphrase for this customer's private keys")
        print("  Generating keys...")
        p_priv, p_pub = generate_rsa_keypair(pw)
        e_priv, e_pub = generate_rsa_keypair(pw)
        code = secrets.token_urlsafe(16)
        try:
            b64, sig = sign_bundle(admin_priv, build_bundle(slug, url, p_pub, e_pub, enroll_code=code))
        except BundleError as e:
            print("  FAILED:", e); continue
        os.makedirs(pkg, exist_ok=True); os.makedirs(keys, exist_ok=True)
        for path, data in ((os.path.join(keys, "backup_private.pem"), p_priv),
                           (os.path.join(keys, "escrow_private.pem"), e_priv),
                           (os.path.join(pkg, "backup_public.pem"), p_pub),
                           (os.path.join(pkg, "escrow_public.pem"), e_pub)):
            with open(path, "wb") as f:
                f.write(data)
        with open(os.path.join(pkg, "bundle.json"), "w", encoding="utf-8") as f:
            json.dump({"BUNDLE_B64": b64, "SIGNATURE_B64": sig}, f, indent=2)
        if installer:
            shutil.copy2(installer, os.path.join(pkg, "Setup_DatabaseBackup.exe"))
            if appfiles:
                shutil.copytree(appfiles, os.path.join(pkg, "AppFiles"), dirs_exist_ok=True)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_csv:
                w.writerow(["slug", "customer_name", "ENROLL_CODE"]); new_csv = False
            w.writerow([slug, name, code])
        with open(tsv_path, "a", encoding="utf-8") as f:
            f.write(f"ENROLL_CODE\t{code}\t{slug}\n")
        done += 1
        print(f"  Done -> {pkg}")

    print(f"\nFinished. {done} new customers provisioned.")
    print(f"Paste rows from {tsv_path} into the Google Sheet 'Config' tab (cols A, B, C).")
    print("KEEP the *_keys folders and enroll_codes files private; do NOT send them to customers.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
