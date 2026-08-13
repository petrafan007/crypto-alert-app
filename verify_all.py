import ast
import os

def get_blueprint_routes():
    bp_routes = set()
    bp_files = [
        'routes/auth.py',
        'routes/portfolio.py',
        'routes/system.py',
        'routes/ai.py',
        'routes/market.py',
        'routes/frontend.py'
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
                            bp_routes.add(node.name)
    return bp_routes

def extract_main_routes():
    routes = set()
    with open('main.py', 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename='main.py')
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr == 'route':
                        routes.add(node.name)
    return routes

if __name__ == '__main__':
    bp_routes = get_blueprint_routes()
    main_routes = extract_main_routes()
    
    missing = main_routes - bp_routes
    if missing:
        print(f"FAILED! Missing {len(missing)} routes from blueprints:")
        for r in missing:
            print(f"- {r}")
    else:
        print(f"SUCCESS! All {len(main_routes)} routes from main.py are now safely housed in blueprints!")
