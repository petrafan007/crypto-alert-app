import sys
with open("services/scheduler_tasks.py", "r") as f:
    content = f.read()

bad_loop = """def options_thesis_refresh_loop(app):
    import time
    with app.app_context():
        while True:
            @safe_background_iteration
            def iteration():
                logger.info("Running hourly options thesis refresh...")
                pass
            
            iteration()
            time.sleep(3600)  # Hourly"""

good_loop = """def options_thesis_refresh_loop(app):
    import time
    while True:
        with app.app_context():
            @safe_background_iteration
            def iteration():
                logger.info("Running hourly options thesis refresh...")
                pass
            
            iteration()
        time.sleep(3600)  # Hourly"""

content = content.replace(bad_loop, good_loop)

with open("services/scheduler_tasks.py", "w") as f:
    f.write(content)
