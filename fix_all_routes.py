import os

routes_dir = 'routes'
for filename in os.listdir(routes_dir):
    if filename.endswith('.py') and filename != '__init__.py':
        path = os.path.join(routes_dir, filename)
        with open(path, 'r') as f:
            content = f.read()
        
        # Point to services instead of main
        content = content.replace('from main import (', '# Import from services\nfrom services.helpers import (')
        content = content.replace('from services.helpers import (\n    serve_react_app,', 'from services.helpers import (\n    # serve_react_app removed,')
        
        with open(path, 'w') as f:
            f.write(content)
        print(f"Refactored {filename}")
