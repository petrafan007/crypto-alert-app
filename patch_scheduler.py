import sys

with open("services/scheduler_tasks.py", "r") as f:
    content = f.read()

# Add the function at the bottom
new_function = """

def options_thesis_refresh_loop(app):
    import time
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                logger.info("Running hourly options thesis refresh...")
                # TODO: Implement Webull / internal DB pending options thesis refresh
                pass
            
            iteration()
            time.sleep(3600)  # Hourly
"""

content += new_function

# Add the thread in start_background_jobs
# Find: logger.info("All background threads initiated.")
#     return {
old_start = """    logger.info("All background threads initiated.")
    
    return {"""

new_start = """    logger.info("All background threads initiated.")
    
    t_opt = threading.Thread(target=options_thesis_refresh_loop, args=(app,), daemon=True)
    t_opt.start()
    
    return {
        "options_thesis": t_opt,"""

content = content.replace(old_start, new_start)

with open("services/scheduler_tasks.py", "w") as f:
    f.write(content)
