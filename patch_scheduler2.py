import sys

with open("services/scheduler_tasks.py", "r") as f:
    lines = f.readlines()

# Add the function at the bottom
new_function = """

def options_thesis_refresh_loop(app):
    import time
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                logger.info("Running hourly options thesis refresh...")
                pass
            
            iteration()
            time.sleep(3600)  # Hourly
"""

# find the exact line for "    logger.info("All background threads initiated.")"
idx = 0
for i, line in enumerate(lines):
    if "logger.info(\"All background threads initiated.\")" in line:
        idx = i
        break

if idx > 0:
    lines.insert(idx + 1, "    t_opt = threading.Thread(target=options_thesis_refresh_loop, args=(app,), daemon=True)\n")
    lines.insert(idx + 2, "    t_opt.start()\n")
    
# Now find the return dict to add it
for i in range(idx + 3, len(lines)):
    if "return {" in lines[i]:
        lines.insert(i + 1, '        "options_thesis": t_opt,\n')
        break

content = "".join(lines) + new_function

with open("services/scheduler_tasks.py", "w") as f:
    f.write(content)
