import re
with open("services/scheduler_tasks.py", "r") as f:
    content = f.read()

# find where thread starts
replacement = """    t_opt = threading.Thread(target=options_thesis_refresh_loop, args=(app,))
    t_opt.daemon = True
    t_opt.start()
    
    return {
"""
content = re.sub(r'    return {', replacement, content)

with open("services/scheduler_tasks.py", "w") as f:
    f.write(content)
