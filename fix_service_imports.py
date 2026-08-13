import glob

files = glob.glob('routes/*.py')
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        if line.startswith('from services.') and line.endswith('Service'):
            continue
        new_lines.append(line)
        
    with open(f, 'w', encoding='utf-8') as file:
        file.write('\n'.join(new_lines))
        
print("Removed invalid Service class imports from all blueprints!")
