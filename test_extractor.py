import ast
import re

def extract_function_source(filepath, func_name):
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            # We want to extract from the first decorator to the end of the function
            start_lineno = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            # This is simple slicing, wait, ast doesn't easily give end lineno in all python versions,
            # but in python 3.8+ we have end_lineno
            end_lineno = getattr(node, 'end_lineno', -1)
            
            lines = source.splitlines()
            if end_lineno != -1:
                return '\n'.join(lines[start_lineno-1:end_lineno])
    return None

if __name__ == '__main__':
    # Test extraction
    print(extract_function_source('main.py', 'api_coin_data')[:100])
