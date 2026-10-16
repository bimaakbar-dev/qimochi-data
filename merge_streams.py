#!/usr/bin/env python3
"""
Merge episodes/streams/*.json → episodes/*.json

- Format streams: array → { quality: [url, url] }
- Format downloads: array → { quality: { size, urls: [...] } }
- Merge metadata (title, aired, duration) kalau ada
- Re-chunk jadi 6 episode per file
- Hapus folder streams/
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path

# ====== CONFIG ======
DRY_RUN = os.environ.get('DRY_RUN', '1') == '1'
CHUNK_SIZE = 6
DATA_DIR = Path('data/anime')
# ====================

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  Failed to read {path}: {e}")
        return None

def convert_streams(raw):
    """
    OLD: [{"quality": "720p", "servers": [{"name": "...", "url": "..."}]}]
    NEW: {"720p": ["url1", "url2"]}
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    result = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        quality = entry.get('quality') or 'unknown'
        servers = entry.get('servers') or []
        urls = [
            s.get('url') for s in servers
            if isinstance(s, dict) and s.get('url')
        ]
        if urls:
            result.setdefault(quality, []).extend(urls)
    return result

def convert_downloads(raw):
    """
    OLD: [{"quality": "720p", "size": "119.1 MB", "servers": [{"name": "...", "url": "..."}]}]
    NEW: {"720p": {"size": "119.1 MB", "urls": ["url1", "url2"]}}
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    result = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        quality = entry.get('quality') or 'unknown'
        size = entry.get('size') or ''
        servers = entry.get('servers') or []
        urls = [
            s.get('url') for s in servers
            if isinstance(s, dict) and s.get('url')
        ]
        if urls:
            result[quality] = {'size': size, 'urls': urls}
    return result

def process_anime(slug_dir):
    slug = slug_dir.name
    episodes_dir = slug_dir / 'episodes'
    streams_dir = episodes_dir / 'streams'

    if not episodes_dir.exists():
        return None

    # Load metadata (files di episodes/*.json, exclude streams/)
    metadata_by_num = {}
    for f in episodes_dir.glob('*.json'):
        data = load_json(f)
        if not isinstance(data, list):
            continue
        for ep in data:
            if not isinstance(ep, dict):
                continue
            n = ep.get('number')
            if isinstance(n, int):
                metadata_by_num[n] = ep

    # Load streams (files di episodes/streams/*.json)
    streams_by_num = {}
    if streams_dir.exists():
        for f in streams_dir.glob('*.json'):
            data = load_json(f)
            if not isinstance(data, list):
                continue
            for ep in data:
                if not isinstance(ep, dict):
                    continue
                n = ep.get('number')
                if isinstance(n, int):
                    streams_by_num[n] = ep

    # Merge
    all_numbers = sorted(set(metadata_by_num.keys()) | set(streams_by_num.keys()))
    if not all_numbers:
        return None

    merged = []
    for n in all_numbers:
        meta = metadata_by_num.get(n, {})
        stream = streams_by_num.get(n, {})

        episode = {
            'number': n,
            'title': meta.get('title') or None,
            'aired': meta.get('aired') or None,
            'duration': meta.get('duration') or None,
            'streams': convert_streams(stream.get('streams')),
            'downloads': convert_downloads(stream.get('downloads')),
        }

        # Buang field null/empty
        if not episode['title']:
            episode.pop('title', None)
        if not episode['aired']:
            episode.pop('aired', None)
        if not episode['duration']:
            episode.pop('duration', None)
        if not episode['streams']:
            episode.pop('streams', None)
        if not episode['downloads']:
            episode.pop('downloads', None)

        merged.append(episode)

    return {
        'slug': slug,
        'episodes': merged,
        'episodes_dir': episodes_dir,
        'streams_dir': streams_dir,
        'had_metadata': bool(metadata_by_num),
        'had_streams': bool(streams_by_num),
    }

def write_chunks(result, dry_run=True):
    episodes = result['episodes']
    episodes_dir = result['episodes_dir']
    streams_dir = result['streams_dir']

    # Delete old files
    old_files = list(episodes_dir.glob('*.json'))
    old_streams = list(streams_dir.glob('*.json')) if streams_dir.exists() else []

    if dry_run:
        return {
            'delete_old': len(old_files),
            'delete_streams': len(old_streams),
            'new_chunks': (len(episodes) + CHUNK_SIZE - 1) // CHUNK_SIZE,
        }

    # Remove old metadata files
    for f in old_files:
        f.unlink()

    # Remove streams folder
    if streams_dir.exists():
        shutil.rmtree(streams_dir)

    # Write new chunks
    chunk_count = 0
    for i in range(0, len(episodes), CHUNK_SIZE):
        chunk = episodes[i:i + CHUNK_SIZE]
        if not chunk:
            continue
        start = chunk[0]['number']
        end = chunk[-1]['number']
        out_path = episodes_dir / f'{start}-{end}.json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, indent=2, ensure_ascii=False)
            f.write('\n')
        chunk_count += 1

    return {
        'delete_old': len(old_files),
        'delete_streams': len(old_streams),
        'new_chunks': chunk_count,
    }

def main():
    if not DATA_DIR.exists():
        print(f"❌ {DATA_DIR} tidak ditemukan")
        sys.exit(1)

    print(f"🔧 Mode: {'DRY RUN' if DRY_RUN else 'EXECUTE'}")
    print(f"🔧 Chunk size: {CHUNK_SIZE}")
    print(f"🔧 Scanning: {DATA_DIR}")
    print("")

    anime_dirs = sorted([d for d in DATA_DIR.iterdir() if d.is_dir()])
    print(f"📁 Total anime: {len(anime_dirs)}")
    print("")

    processed = 0
    skipped = 0
    total_old = 0
    total_new = 0
    errors = []

    for slug_dir in anime_dirs:
        try:
            result = process_anime(slug_dir)
            if not result:
                skipped += 1
                continue

            stats = write_chunks(result, dry_run=DRY_RUN)
            processed += 1
            total_old += stats['delete_old'] + stats['delete_streams']
            total_new += stats['new_chunks']

            if processed <= 5:
                print(f"  ✅ {result['slug']}: {len(result['episodes'])} ep → "
                      f"{stats['new_chunks']} chunks "
                      f"(delete: {stats['delete_old']}+{stats['delete_streams']})")

        except Exception as e:
            errors.append(f"{slug_dir.name}: {e}")
            print(f"  ❌ {slug_dir.name}: {e}")

    print("")
    print("════════════════════════════════════════")
    print(f"  📊 RESULT")
    print("════════════════════════════════════════")
    print(f"  Processed:  {processed} anime")
    print(f"  Skipped:    {skipped} (kosong, no episode)")
    print(f"  Deleted:    {total_old} old files")
    print(f"  Created:    {total_new} new chunks")
    print(f"  Errors:     {len(errors)}")
    print("════════════════════════════════════════")

    if errors:
        print("")
        print("Errors:")
        for e in errors[:20]:
            print(f"  • {e}")

    if DRY_RUN:
        print("")
        print("🧪 DRY RUN — tidak ada file diubah")
        print("▶️  Eksekusi: run workflow dengan dry_run: false")

if __name__ == '__main__':
    main()