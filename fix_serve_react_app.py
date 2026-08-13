import glob

def fix_serve_react_app():
    # 1. Append the real serve_react_app to routes/helpers.py
    helper_code = """
from pathlib import Path
import re
from flask import current_app, Response

def serve_react_app():
    \"\"\"Serve the built React index with cache-busting headers so UI updates ship instantly.\"\"\"
    index_path = Path(current_app.static_folder or '') / 'index.html'
    logger.info(f"Serving React index from {index_path}")
    try:
        content = index_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        logger.warning("React index file missing, falling back to send_static_file")
        return current_app.send_static_file('index.html')

    build_token = str(int(index_path.stat().st_mtime))
    logger.info(f"Serving React index with cache-bust token {build_token}")

    def _add_version(match):
        path = match.group(1)
        quote = match.group(2)
        if '?v=' in path:
            return match.group(0)
        return f'{path}?v={build_token}{quote}'

    content = re.sub(r'(/static/[^"\\']+)(["\\'])', _add_version, content)
    return Response(content, mimetype='text/html')
"""
    with open('routes/helpers.py', 'a', encoding='utf-8') as f:
        f.write("\n" + helper_code + "\n")

    # 2. Remove any dummy serve_react_app functions from blueprints
    files = glob.glob('routes/*.py')
    for filepath in files:
        if filepath == 'routes/helpers.py':
            continue
            
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        new_lines = []
        skip_next = False
        for i, line in enumerate(lines):
            if 'def serve_react_app(' in line and 'return' in line:
                # it's a one-liner dummy
                continue
            if 'def serve_react_app' in line:
                skip_next = True
                continue
            if skip_next:
                # skip body of the dummy function
                if line.strip() == '' or line.startswith('    ') or line.startswith('\t'):
                    continue
                else:
                    skip_next = False
                    
            if not skip_next:
                new_lines.append(line)
                
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("".join(new_lines))

if __name__ == '__main__':
    fix_serve_react_app()
    print("Fixed serve_react_app!")
