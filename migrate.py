"""Explicit, idempotent desktop migration. Source files are read only.

Run --dry-run first. Credentials and manifest must remain outside source control.
"""
import argparse
import hashlib
import json
import mimetypes
from pathlib import Path

from legacy_core import parse_card
from storage import Store, digest


def normalize_fields(fm):
    """Decode quoted YAML scalar strings retained by the desktop parser."""
    result = dict(fm)
    for key, value in fm.items():
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                decoded = json.loads(value)
                if isinstance(decoded, str):
                    result[key] = decoded
            except ValueError:
                pass
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            result[key] = value[1:-1].replace("''", "'")
    return result


def scan(config):
    root = Path(config['vault']).resolve()
    kt = Path(config['kt']).resolve()
    cards, assets = [], []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(p.startswith('.') and p != '.crm-trash' for p in rel.parts):
            continue
        raw = path.read_bytes()
        deleted = '.crm-trash' in rel.parts
        kind = 'kt' if path.is_relative_to(kt) else 'customer'
        fm, body, valid = parse_card(raw.decode('utf-8-sig')) if path.suffix.lower() == '.md' else ({}, '', False)
        # Reports also have YAML headers; only files at a card root/trash count as cards.
        card_parent = path.parent in (root, kt) or (deleted and path.parent.parent.name == '.crm-trash')
        if valid and fm.get('상호') and card_parent:
            fm = normalize_fields(fm)
            cards.append({'id': 'legacy_' + digest(str(rel)), 'fm': fm, 'body': body,
                          'kind': kind, 'deleted': deleted, 'source': str(rel)})
        else:
            assets.append({'path': path, 'name': str(rel), 'sha256': hashlib.sha256(raw).hexdigest(),
                           'type': mimetypes.guess_type(path.name)[0] or 'application/octet-stream'})
    return cards, assets


def migrate(store, cards, assets):
    report = {'cards': [], 'assets': []}
    for card in cards:
        ident, created = store.create(card['fm'], card['body'], kind=card['kind'],
                                     source_id=card['fm'].get('설문응답ID') or None,
                                     legacy_id=card['id'], deleted=card['deleted'])
        saved = store.get(ident)
        if created and (saved['fm'] != card['fm'] or saved['body'] != card['body']):
            raise RuntimeError('Migrated card verification failed')
        report['cards'].append({'id': ident, 'source': card['source'], 'created': created})
    for asset in assets:
        raw = asset['path'].read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset['sha256']:
            raise RuntimeError('Source changed during migration; rerun the scan')
        ident = store.put_asset(asset['name'], raw, asset['type'], 'legacy')
        _, verified = store.get_asset(ident)
        if verified != raw:
            raise RuntimeError('Migrated asset verification failed')
        report['assets'].append({'id': ident, 'source': asset['name'], 'sha256': asset['sha256']})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--credentials')
    parser.add_argument('--owner')
    parser.add_argument('--manifest')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    cards, assets = scan(json.loads(Path(args.config).read_text(encoding='utf-8-sig')))
    print(json.dumps({'cards': len(cards), 'deleted': sum(c['deleted'] for c in cards),
                      'kt': sum(c['kind'] == 'kt' for c in cards), 'assets': len(assets)}))
    if not args.dry_run:
        if not all((args.credentials, args.owner, args.manifest)):
            parser.error('credentials, owner and private manifest destination are required')
        store = Store(json.loads(Path(args.credentials).read_text(encoding='utf-8-sig')), args.owner)
        report = migrate(store, cards, assets)
        dest = Path(args.manifest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Migration complete; every newly created card and every asset verified.')
