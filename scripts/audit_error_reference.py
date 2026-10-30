"""Independent emission-site check for the generated diagnostic reference.

This intentionally does not import the collector or its expression/token parser.
It checks source literals at language-level failure sinks against the published
data, and checks dynamic sinks against the explicitly documented handoff owners.
It is a second coverage check, not a claim to enumerate external runtime text.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def literal_fragments(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.Constant):
                yield str(value.value)
    elif isinstance(node, ast.BinOp):
        yield from literal_fragments(node.left)
        if isinstance(node.op, ast.Add):
            yield from literal_fragments(node.right)
    elif isinstance(node, ast.IfExp):
        yield from literal_fragments(node.body)
        yield from literal_fragments(node.orelse)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for value in node.elts:
            yield from literal_fragments(value)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from literal_fragments(value)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
        yield from literal_fragments(node.func.value)
    elif isinstance(node, ast.Call) and node.args and (
        isinstance(node.func, ast.Attribute) and node.func.attr in {'tr', 'translate'}
        or isinstance(node.func, ast.Name) and node.func.id in {'tr', 'translate', 'str', 'repr', 'list', 'tuple', 'set'}
    ):
        yield from literal_fragments(node.args[-1])


def audit(root=ROOT):
    from cdmw.ui.shell.error_reference_data import ERROR_REFERENCE, MESSAGE_REFERENCE, DYNAMIC_REFERENCE, SOURCE_COVERAGE
    text_by_path = defaultdict(list)
    for row in ERROR_REFERENCE:
        for path in row['sources']:
            text_by_path[path].extend([row['code'], *row['messages']])
    for row in MESSAGE_REFERENCE:
        for path in row['sources']:
            text_by_path[path].append(row['message'])
    indexed = {path: '\n'.join(texts) for path, texts in text_by_path.items()}
    dynamic = {path for paths in DYNAMIC_REFERENCE.values() for path in paths}
    missing = []
    counts = defaultdict(int)
    sources = {path: (root / path).read_text(encoding='utf-8-sig') for path in SOURCE_COVERAGE}
    trees = {path: ast.parse(source) for path, source in sources.items() if path.endswith('.py')}
    constant_candidates = defaultdict(set)
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                parts = tuple(literal_fragments(node.value))
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    if parts and isinstance(target, ast.Name) and target.id.isupper():
                        constant_candidates[target.id].add(parts)
    constants = {name: list(next(iter(values))) for name, values in constant_candidates.items() if len(values) == 1}

    def check(path, line, parts, kind):
        parts = [' '.join(part.split()) for part in parts if re.search(r'[A-Za-z]{2}', part)]
        counts[kind] += 1
        if not parts:
            if path not in dynamic:
                missing.append((path, line, kind, '<dynamic handoff>'))
        else:
            for part in parts:
                if part not in indexed.get(path, ''):
                    missing.append((path, line, kind, part))

    for path in SOURCE_COVERAGE:
        source = sources[path]
        if path.endswith('.py'):
            tree = trees[path]
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            def scope(node):
                while node in parents:
                    node = parents[node]
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        return node
                return tree
            # Independently resolve the simple local aliases used by raises.
            aliases = defaultdict(list)
            for assignment in ast.walk(tree):
                if isinstance(assignment, (ast.Assign, ast.AnnAssign)):
                    for target in assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]:
                        if isinstance(target, ast.Name):
                            aliases[(scope(assignment), target.id)].extend(literal_fragments(assignment.value))

            def check_field(node, value):
                if isinstance(value, ast.Constant) and not isinstance(value.value, str):
                    return
                if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts:
                    return
                fragments = list(literal_fragments(value))
                if isinstance(value, ast.Name):
                    fragments = aliases[(scope(node), value.id)] or aliases[(tree, value.id)] or constants.get(value.id, [])
                if fragments and all(not part.strip() or re.fullmatch(r'#[0-9a-fA-F]{3,8}', part) for part in fragments):
                    return  # Empty labels and theme colours are not diagnostic text.
                fragments = [part for part in fragments if part.strip() and not re.fullmatch(r'#[0-9a-fA-F]{3,8}', part)]
                if fragments or not isinstance(value, ast.Constant):
                    check(path, node.lineno, fragments, 'Python diagnostic payload field')

            # Deliberately independent of the collector's field table and parser.
            field_name = re.compile(r'^(?:errors?|warnings?|warning_text|warning_badge|error_text|error_message|error_detail|failure_reason|failure_message|failure_detail|blocking_reason)$')
            report_name = re.compile(r'(?:^|[._])(?:lines|parts|notes|details)$')
            report_failure = re.compile(r'\b(?:error|failed|failure|invalid|unsupported|unavailable|missing|cannot|truncated|corrupt|timeout|denied)\b', re.I)
            for node in ast.walk(tree):
                value = None
                kind = ''
                if isinstance(node, ast.Raise):
                    kind = 'Python raise'
                    value = node.exc.args[0] if isinstance(node.exc, ast.Call) and node.exc.args else node.exc
                elif isinstance(node, ast.Assert):
                    kind, value = 'Python assertion', node.msg
                elif isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    for keyword in node.keywords:
                        if keyword.arg and field_name.fullmatch(keyword.arg):
                            check_field(node, keyword.value)
                    if isinstance(node.func, ast.Attribute) and node.func.attr in {'append', 'extend'} and report_name.search(ast.unparse(node.func.value)) and node.args:
                        for fragment in literal_fragments(node.args[0]):
                            if report_failure.search(fragment):
                                check(path, node.lineno, [fragment], 'Python diagnostic report fragment')
                    if name.endswith(('.warning', '.critical')) and 'QMessageBox' in name and len(node.args) >= 3:
                        kind, value = 'Qt warning/critical dialog', node.args[2]
                    elif name.split('.')[-1] == 'QMessageBox' and len(node.args) >= 3 and ast.unparse(node.args[0]).endswith(('.Warning', '.Critical')):
                        kind, value = 'Qt warning/critical dialog', node.args[2]
                    elif name.endswith(('.error', '.exception', '.fatal')) and node.args:
                        kind, value = 'Python error log', node.args[0]
                elif isinstance(node, ast.Dict):
                    if len(node.values) > 1 and all(isinstance(value, ast.Attribute) and value.attr.isupper() for value in node.values):
                        continue
                    for key, value_node in zip(node.keys, node.values):
                        if isinstance(key, ast.Constant) and isinstance(key.value, str) and field_name.fullmatch(key.value):
                            check_field(node, value_node)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else str(target.slice.value) if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) else ''
                        if node.value is not None and field_name.fullmatch(name):
                            check_field(node, node.value)
                        elif report_name.search(name):
                            for fragment in literal_fragments(node.value):
                                if report_failure.search(fragment):
                                    check(path, node.lineno, [fragment], 'Python diagnostic report fragment')
                if kind:
                    fragments = aliases[(scope(node), value.id)] or aliases[(tree, value.id)] if isinstance(value, ast.Name) else literal_fragments(value)
                    check(path, node.lineno, fragments, kind)
        else:
            # Deliberately separate regex recognizer for direct native throws,
            # Rust error attributes/macros and C# exception messages. Ignore
            # comments and inline Rust test modules before looking at sinks.
            text = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', lambda m: '\n' * m[0].count('\n'), source)
            text = re.split(r'#\[cfg\(test\)\]', text)[0]
            pattern = r'(?:throw\s+(?:new\s+)?[\w:]+\s*\(|(?:bail|panic|ensure)!\s*\(|#\[error\s*\()\s*(?:\$|L|u8)?"((?:\\[\s\S]|[^"\\])*)"'
            for match in re.finditer(pattern, text):
                literal = re.sub(r'\\\r?\n\s*', '', match[1])
                literal = re.sub(r'\\([\\"nrt])', lambda m: {'n':'\n','r':'\r','t':'\t'}.get(m[1],m[1]), literal)
                # Pure formatting placeholders are upstream details rather than
                # a locally authored sentence (e.g. panic!("{error}")).
                parts = [] if not re.search('[A-Za-z]', re.sub(r'\{[^}]*\}', '', literal)) else [literal]
                check(path, text.count('\n', 0, match.start()) + 1, parts, 'Native direct failure literal')
    return dict(sorted(counts.items())), missing


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    counts, missing = audit()
    for kind, count in counts.items():
        print(f'{kind}: {count}')
    for row in missing[:50]:
        print('MISSING', *row)
    print(f'Unaccounted emission sites/fragments: {len(missing)}')
    raise SystemExit(bool(missing))
