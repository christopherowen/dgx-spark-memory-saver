# SPDX-License-Identifier: MIT
"""Packaging checks only. Never import or execute the CUDA test programs."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def code_sha256(text):
    # Comment text removed, line structure kept: this identifies the compiled code.
    return hashlib.sha256('\n'.join(re.sub(r'\s*//.*', '', line)
                                    for line in text.splitlines()).encode()).hexdigest()


class RepositoryChecks(unittest.TestCase):
    def test_profile_manifests_hashes_and_allocator_equivalence(self):
        registry = json.loads((ROOT / 'compatibility.json').read_text())
        changes = []
        for version, profile in registry['drivers'].items():
            manifest = json.loads((ROOT / profile['manifest']).read_text())
            self.assertEqual(manifest['upstream']['tag'], version)
            self.assertTrue(set(profile['kernels']) <= set(registry['kernels']))
            patch = (ROOT / profile['patch']).read_bytes()
            self.assertEqual(hashlib.sha256(patch).hexdigest(), profile['patch_sha256'])
            changes.append([line for line in patch.decode().splitlines()
                            if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))])
        self.assertTrue(all(change == changes[0] for change in changes))

    def test_historical_artifact_hashes(self):
        manifest = json.loads((ROOT / 'provenance.json').read_text())
        for name, record in manifest['copied_files'].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
                                 record['sha256'])

    def test_patch_comment_revisions_keep_validated_code(self):
        for manifest_name in ['provenance.json', 'provenance-610.json']:
            manifest = json.loads((ROOT / manifest_name).read_text())
            records = [(name, record) for name, record in manifest['copied_files'].items()
                       if 'code_sha256' in record]
            if 'port' in manifest:
                records.append((manifest['port']['patch'], manifest['port']))
            self.assertTrue(records)
            for name, record in records:
                with self.subTest(manifest=manifest_name, file=name):
                    self.assertEqual(code_sha256((ROOT / name).read_text()), record['code_sha256'])

    def test_json_and_python_syntax_without_execution(self):
        for path in [ROOT / 'provenance.json', *ROOT.glob('results/**/*.json')]:
            with self.subTest(file=str(path)):
                json.loads(path.read_text())
        for path in ROOT.glob('tests/*.py'):
            with self.subTest(file=str(path)):
                ast.parse(path.read_text(), filename=str(path))

    def test_patch_parses(self):
        # Syntax only: source application and target compilation are separate.
        result = subprocess.run(
            ['git', 'apply', '--numstat', str(ROOT / 'patches/0001-pack-user-leaf-tables.patch')],
            cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual({line.split('\t')[2] for line in result.stdout.splitlines()},
                         {'nvidia-uvm/uvm_mmu.c', 'nvidia-uvm/uvm_mmu.h'})

    def test_local_documentation_links(self):
        for path in [*ROOT.glob('*.md'), *ROOT.glob('docs/*.md')]:
            for href in re.findall(r'\[[^\]]*\]\(([^)]+)\)', path.read_text()):
                if href.startswith(('https://', 'http://', '#')):
                    continue
                target = unquote(href.split('#', 1)[0])
                with self.subTest(file=path.name, link=href):
                    self.assertTrue((path.parent / target).exists())


if __name__ == '__main__':
    unittest.main()
