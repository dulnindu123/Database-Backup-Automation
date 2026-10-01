"""
Zero-Trust Build Secret Guard Audit
Scans dist/ directory to ensure no private keys, tokens, or credentials are leaked.
"""
import os
import sys

dist_dir = 'dist'
forbidden_files = ['client_secret.json', 'credentials.json', 'token.json', 'broker_token.dat', 'backup_log.txt']
violations = []

if not os.path.exists(dist_dir):
    print('[ERROR] dist directory does not exist.')
    sys.exit(1)

for root, dirs, files in os.walk(dist_dir):
    for f in files:
        if f in forbidden_files:
            violations.append(os.path.join(root, f))
        elif f.endswith('.pem'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                if 'PRIVATE KEY' in fp.read():
                    violations.append(path + ' (CONTAINS PRIVATE KEY)')

if violations:
    print('[CRITICAL ERROR] Secret guard failure! Discovered secrets in dist/:', violations)
    sys.exit(1)
else:
    print('[OK] Secret Guard Audit Passed: 0 secret files or private keys present in dist/')
