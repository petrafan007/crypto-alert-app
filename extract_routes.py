import ast

def extract_routes(filepath):
    routes = []
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
                            routes.append((path, methods, node.name))
    return routes

if __name__ == '__main__':
    routes = extract_routes('main.py')
    # Sort routes alphabetically for easier tracking
    routes.sort(key=lambda x: x[0])
    
    print(f"Total Routes found in main.py: {len(routes)}")
    
    with open('route_checklist.md', 'w') as f:
        f.write("# Endpoint Migration Checklist\n\n")
        f.write("## Endpoints\n")
        for path, methods, func in routes:
            f.write(f"- [ ] `{methods} {path}` -> function `{func}`\n")
    
    print("Generated route_checklist.md")
