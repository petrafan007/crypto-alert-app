import ast
import os
import re

def get_blueprint_routes():
    bp_routes = set()
    bp_files = [
        'routes/auth.py',
        'routes/portfolio.py',
        'routes/system.py',
        'routes/ai.py'
    ]
    for filepath in bp_files:
        if not os.path.exists(filepath):
            continue
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                        if decorator.func.attr == 'route':
                            if len(decorator.args) > 0 and isinstance(decorator.args[0], ast.Constant):
                                path = decorator.args[0].value
                                methods = "['GET']"
                                for kw in decorator.keywords:
                                    if kw.arg == 'methods':
                                        if isinstance(kw.value, ast.List):
                                            methods = str([el.value for el in kw.value.elts if isinstance(el, ast.Constant)])
                                bp_routes.add((path, node.name))
    return bp_routes

if __name__ == '__main__':
    bp_routes = get_blueprint_routes()
    task_file = '/home/jcavallarojr/.gemini/antigravity-ide/brain/50354d94-3fae-4189-b6d6-f32da7983b1e/task.md'
    
    with open(task_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        match = re.search(r'- \[ \] `.*? (.*?)` -> function `(.*?)`', line)
        if match:
            path, func = match.groups()
            if (path, func) in bp_routes:
                lines[i] = line.replace('- [ ]', '- [x]')
                
    with open(task_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)
        
    print(f"Updated task.md. Found {len(bp_routes)} routes across blueprints.")
