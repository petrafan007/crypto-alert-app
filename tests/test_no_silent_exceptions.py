"""Guard: broad exception handlers must not swallow errors silently."""
import ast
import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NoSilentBroadExceptTests(unittest.TestCase):
    def test_no_broad_handler_is_only_pass(self):
        offenders = []
        patterns = ('*.py', 'routes/*.py', 'services/*.py', 'core/*.py', 'strategy_service/*.py')
        for pattern in patterns:
            for path in glob.glob(os.path.join(ROOT, pattern)):
                with open(path) as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ExceptHandler):
                        continue
                    broad = node.type is None or ast.unparse(node.type) in ('Exception', 'BaseException')
                    if broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        offenders.append(f'{os.path.relpath(path, ROOT)}:{node.lineno}')
        self.assertEqual(offenders, [], 'Log, narrow or handle these instead of passing: ' + ', '.join(offenders))

    def test_no_module_imports_the_removed_routes_trading(self):
        hits = []
        for pattern in ('*.py', 'routes/*.py', 'services/*.py'):
            for path in glob.glob(os.path.join(ROOT, pattern)):
                with open(path) as handle:
                    if 'routes.trading import' in handle.read():
                        hits.append(os.path.relpath(path, ROOT))
        self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
