#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct
import zlib


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cramfs(path):
    image = path.read_bytes()
    assert struct.unpack_from('<I', image)[0] == 0x28cd3d45
    entries, contents = {}, {}

    def u32(pos):
        return struct.unpack_from('<I', image, pos)[0]

    def payload(offset, size):
        blocks = (size + 4095) // 4096
        previous_end = offset + 4 * blocks
        result = bytearray()
        for block in range(blocks):
            pointer = u32(offset + block * 4)
            raw, direct = bool(pointer & 0x80000000), bool(pointer & 0x40000000)
            pointer &= 0x3fffffff
            remaining = min(4096, size - block * 4096)
            if direct:
                start = pointer << 2
                if raw:
                    end = start + remaining
                else:
                    length = struct.unpack_from('<H', image, start)[0]
                    start += 2
                    end = start + length
            else:
                start, end = previous_end, pointer
            assert 0 <= start <= end <= len(image)
            data = image[start:end]
            decoded = (data if raw else zlib.decompress(data)) if data else bytes(remaining)
            assert len(decoded) >= remaining
            result.extend(decoded[:remaining])
            previous_end = end
        assert len(result) == size
        return bytes(result)

    def walk(pos, name, parents=()):
        a, b, c = struct.unpack_from('<III', image, pos)
        mode, uid, size, gid, offset = a & 65535, a >> 16, b & 0xffffff, b >> 24, (c >> 6) << 2
        assert name not in entries
        entry = {'mode': oct(mode), 'uid': uid, 'gid': gid, 'size': size}
        entries[name] = entry
        if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            data = payload(offset, size)
            contents[name] = data
            entry['sha256'] = digest(data)
        elif stat.S_ISDIR(mode) and size:
            assert offset not in parents and offset + size <= len(image)
            end = offset + size
            while offset < end:
                length = (u32(offset + 8) & 63) << 2
                assert length and offset + 12 + length <= end
                child = image[offset + 12:offset + 12 + length].rstrip(b'\0').decode()
                assert '/' not in child and child not in ('.', '..')
                walk(offset, name.rstrip('/') + '/' + child, parents + ((c >> 6) << 2,))
                offset += 12 + length
            assert offset == end
    walk(64, '/')
    return entries, contents


def jffs2_nodes(path):
    image = path.read_bytes()
    nodes, names = {}, {1: (None, '')}
    pos = 0
    while pos + 12 <= len(image):
        if image[pos:pos + 4] == b'\xff' * 4:
            pos = (pos // 65536 + 1) * 65536
            continue
        magic, kind, length = struct.unpack_from('<HHI', image, pos)
        assert magic == 0x1985 and 12 <= length <= len(image) - pos
        node = image[pos:pos + length]
        if kind == 0xe001:
            parent, version, ino = struct.unpack_from('<III', node, 12)
            name = node[40:40 + node[28]].decode()
            names[ino] = (parent, name)
            key = ('dirent', parent, version)
        elif kind == 0xe002:
            ino, version = struct.unpack_from('<II', node, 12)
            key = ('inode', ino, version)
        elif kind == 0x2003:
            key = ('cleanmarker', pos // 65536, 0)
        else:
            raise ValueError(f'Unexpected JFFS2 node type {kind:#x}')
        assert key not in nodes
        nodes[key] = {'sha256': digest(node), 'bytes': length}
        pos += (length + 3) & ~3
    def pathname(ino):
        parent, name = names[ino]
        return '' if parent is None else pathname(parent) + '/' + name
    for key, node in nodes.items():
        if key[0] == 'inode':
            node['path'] = pathname(key[1])
    return nodes


def compare(left, right):
    manifests = [json.loads((root / 'artifacts/build-manifest.json').read_text()) for root in (left, right)]
    artifacts = {}
    assert manifests[0]['sha256'].keys() == manifests[1]['sha256'].keys()
    for name in manifests[0]['sha256']:
        values = []
        for root, manifest in zip((left, right), manifests):
            data = (root / 'artifacts' / name).read_bytes()
            sha = digest(data)
            assert sha == manifest['sha256'][name], (root, name)
            values.append({'sha256': sha, 'bytes': len(data)})
        artifacts[name] = {'identical': values[0] == values[1], 'left': values[0], 'right': values[1]}
    trees = [cramfs(root / 'artifacts/rootfs.cramfs') for root in (left, right)]
    diffs = {}
    for name in sorted(trees[0][0].keys() | trees[1][0].keys()):
        a, b = trees[0][0].get(name), trees[1][0].get(name)
        if a != b:
            diffs[name] = {'left': a, 'right': b}
    shadow = []
    for tree in trees:
        shadow.append({fields[0]: fields[1:] for line in tree[1]['/etc/shadow'].decode().splitlines()
                       if (fields := line.split(':'))})
    shadow_differences = {}
    for name in sorted(shadow[0].keys() | shadow[1].keys()):
        a, b = shadow[0].get(name), shadow[1].get(name)
        if a != b:
            shadow_differences[name] = {'present_in_both': a is not None and b is not None,
                                      'non_password_fields_equal': bool(a and b and a[1:] == b[1:]),
                                      'hash_algorithm_ids': [v[0].split('$')[1] if v and v[0].startswith('$') else None
                                                             for v in (a, b)]}
    configurations = {}
    for name in manifests[0]['configuration_sha256'].keys() | manifests[1]['configuration_sha256'].keys():
        hashes = [digest((root / 'artifacts/configs' / name).read_bytes()) for root in (left, right)]
        for sha, manifest in zip(hashes, manifests):
            assert sha == manifest['configuration_sha256'][name]
        configurations[name] = {'identical': hashes[0] == hashes[1], 'sha256': hashes}
    writable = [jffs2_nodes(root / 'artifacts/etc.jffs2') for root in (left, right)]
    jffs_diffs = []
    for key in sorted(writable[0].keys() | writable[1].keys()):
        a, b = writable[0].get(key), writable[1].get(key)
        if a != b:
            jffs_diffs.append({'key': key, 'left': a, 'right': b})
    return {'left_directory': str(left), 'right_directory': str(right),
            'source_commits': [m['source_commit'] for m in manifests],
            'same_source_commit': manifests[0]['source_commit'] == manifests[1]['source_commit'],
            'container_image_ids': [m['container_image_id'] for m in manifests],
            'all_artifacts_identical': all(a['identical'] for a in artifacts.values()),
            'artifacts': artifacts, 'configurations': configurations,
            'rootfs_entry_counts': [len(t[0]) for t in trees], 'rootfs_differences': diffs,
            'shadow_differences_redacted': shadow_differences,
            'etc_jffs2_node_counts': [len(nodes) for nodes in writable],
            'etc_jffs2_node_differences': jffs_diffs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = compare(args.left.resolve(), args.right.resolve())
    output = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(output)
    print(output)
